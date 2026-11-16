"""Reddit integration unit tests (hermetic: no live network, no credentials).

Covers normalization, discovery planning, caching, de-duplication, rate-limit handling,
bounded retries, circuit breaking, error classification and export mapping.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from leadsweep.core.exporter import LEADS_EXPORT_COLUMNS, DatasetExporter
from leadsweep.integrations.reddit.authentication import (
    DEFAULT_ARCHIVE_BASE_URL,
    OFFLINE_FIXTURES,
    PROVIDER_ARCTIC_SHIFT,
    PROVIDER_REDDIT_JSON,
    PUBLIC_UNAUTHENTICATED,
    RedditAccessConfig,
    load_access_config,
)
from leadsweep.integrations.reddit.cache import RedditResponseCache, SeenRegistry, make_cache_key
from leadsweep.integrations.reddit.client import RedditClient
from leadsweep.integrations.reddit.discovery import build_plan, expand_intent_terms, split_terms
from leadsweep.integrations.reddit.exceptions import (
    RedditAccessDeniedError,
    RedditAuthRequiredError,
    RedditCircuitOpenError,
    RedditNotFoundError,
    RedditRateLimitedError,
    RedditServerError,
    classify_http_status,
)
from leadsweep.integrations.reddit.models import RedditPost
from leadsweep.integrations.reddit.normalizer import (
    normalize_author,
    normalize_comment,
    normalize_listing,
    normalize_post,
    normalize_subreddit,
)
from leadsweep.integrations.reddit.pagination import build_listing_params, clamp_page_size, extract_after
from leadsweep.integrations.reddit.rate_limiter import RedditRequestController
from leadsweep.integrations.reddit.service import RedditIngestionService
from leadsweep.integrations.reddit.subreddit import normalize_subreddit_target, parse_subreddit_list

FIXTURE_DIR = Path("tests/fixtures/reddit")


def make_config(**overrides) -> RedditAccessConfig:
    base = dict(
        enabled=True,
        mode=PUBLIC_UNAUTHENTICATED,
        user_agent="test-agent",
        base_url="https://www.reddit.com",
        max_requests_per_minute=6000,
        max_concurrent_requests=1,
        request_timeout=5.0,
        max_retries=1,
        cache_ttl_seconds=0,
        fixture_dir=FIXTURE_DIR,
        max_pages=1,
        page_size=25,
        comment_budget=0,
        circuit_breaker_ttl_s=300.0,
    )
    base.update(overrides)
    return RedditAccessConfig(**base)


def make_client(handler, config=None) -> RedditClient:
    cfg = config or make_config()
    controller = RedditRequestController(
        max_requests_per_minute=6000,
        max_retries=cfg.max_retries,
        backoff_base_s=0.1,
        circuit_breaker_ttl_s=cfg.circuit_breaker_ttl_s,
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return RedditClient(cfg, controller=controller, http_client=http)


# --------------------------------------------------------------------- configuration
def test_access_config_requires_no_credentials(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    cfg = load_access_config()
    assert cfg.mode in (PUBLIC_UNAUTHENTICATED, OFFLINE_FIXTURES)
    assert cfg.live_network_allowed is (cfg.mode == PUBLIC_UNAUTHENTICATED)
    described = cfg.describe()
    assert described["requires_credentials"] is False
    assert described["credentials_configured"] is False
    assert described["personal_account_required"] is False
    assert "oauth" in described["documented_access_note"].lower()


def test_invalid_access_mode_falls_back_to_public(monkeypatch):
    class S:
        reddit_enabled = True
        reddit_access_mode = "definitely-not-a-mode"

    cfg = load_access_config(S())
    assert cfg.mode == PUBLIC_UNAUTHENTICATED
    assert cfg.enabled is True


def test_disabled_mode_blocks_network():
    class S:
        reddit_enabled = True
        reddit_access_mode = "disabled"

    cfg = load_access_config(S())
    assert cfg.enabled is False
    assert cfg.live_network_allowed is False


# --------------------------------------------------------------------- normalization
def _fixture_children():
    payload = json.loads((FIXTURE_DIR / "sample_listing.json").read_text(encoding="utf-8"))
    return payload["data"]["children"]


def test_normalize_post_extracts_verifiable_fields():
    post = normalize_post(_fixture_children()[0])
    assert post.post_id == "aaa111"
    assert post.subreddit == "SaaS"
    assert post.author == "founder_sam"
    assert post.score == 27
    assert post.num_comments == 11
    assert post.upvote_ratio == pytest.approx(0.94)
    assert post.permalink.startswith("https://www.reddit.com/r/SaaS/comments/aaa111")
    assert post.created_at.startswith("2025-11-01") or post.created_at.startswith("2025-11-02")
    assert post.lead_id == "reddit_aaa111"
    assert post.removed is False


def test_normalize_missing_metrics_stay_missing():
    post = normalize_post(_fixture_children()[1])
    assert post.score is None
    assert post.upvote_ratio == pytest.approx(0.8)
    assert post.num_comments == 4
    tweet = post.to_tweet()
    meta = tweet.extra_metadata or {}
    assert meta["metrics_complete"] is False
    assert meta["score"] is None


def test_normalize_deleted_author_is_none():
    post = normalize_post(_fixture_children()[1])
    assert post.author is None
    assert normalize_author("[deleted]") is None
    assert normalize_author("u/real_user") == "real_user"


def test_removed_posts_are_flagged_not_rewritten():
    post = normalize_post(_fixture_children()[2])
    assert post.removed is True


def test_malformed_child_raises_response_error():
    from leadsweep.integrations.reddit.exceptions import RedditResponseError

    with pytest.raises(RedditResponseError):
        normalize_post({"kind": "t3"})


def test_listing_normalization_skips_malformed_children():
    payload = {"data": {"children": [{"kind": "t3", "data": {"id": "x1", "subreddit": "SaaS", "title": "t"}}, {"kind": "t3"}]}}
    posts = normalize_listing(payload)
    assert [p.post_id for p in posts] == ["x1"]


def test_normalize_comment_and_body_markers():
    children = _fixture_children()[0]["data"]["comments"]
    first = normalize_comment(children[0], "aaa111")
    assert first is not None and first.author == "agency_owner" and first.post_id == "aaa111"
    assert normalize_comment(children[1], "aaa111") is None  # [removed]
    assert normalize_comment({"kind": "more"}, "aaa111") is None


def test_subreddit_normalization():
    assert normalize_subreddit("r/SaaS/") == "SaaS"
    assert normalize_subreddit("/r/webdev") == "webdev"
    assert normalize_subreddit_target("https://www.reddit.com/r/SaaS/") == "SaaS"
    assert normalize_subreddit_target("r/webdev") == "webdev"
    assert normalize_subreddit_target("not a subreddit!") is None
    assert parse_subreddit_list("r/SaaS, webdev, invalid!!") == ["SaaS", "webdev"]


# --------------------------------------------------------------------- pagination
def test_pagination_bounds_and_params():
    assert clamp_page_size(0) == 1
    assert clamp_page_size(10_000) == 100
    params = build_listing_params(query="need a tool", sort="new", limit=500, restrict_to_subreddit=True)
    assert params["limit"] == 100
    assert params["restrict_sr"] == 1
    assert params["q"] == "need a tool"
    assert extract_after({"data": {"after": "t3_abc"}}) == "t3_abc"
    assert extract_after({"data": {"after": None}}) is None


# --------------------------------------------------------------------- discovery planning
def test_split_terms_and_intent_expansion():
    assert split_terms("need an agency or looking for a scraper") == ["need an agency", "looking for a scraper"]
    expanded = expand_intent_terms(["ai scraper"])
    assert "ai scraper" in expanded
    assert any("recommendation" in term for term in expanded)


def test_build_plan_with_subreddits_and_dates():
    plan = build_plan(
        "need an AI automation agency",
        {"subreddits": "r/SaaS, r/Entrepreneur", "includeComments": True, "dateFrom": "2026-01-01"},
    )
    assert plan.subreddits == ["SaaS", "Entrepreneur"]
    assert plan.terms[0] == "need an AI automation agency"
    assert plan.include_comments is True
    assert plan.date_from == "2026-01-01"
    assert plan.mode == "keyword_and_subreddit"


def test_build_plan_subreddit_only_query():
    plan = build_plan("r/SaaS", {})
    assert plan.subreddits == ["SaaS"]
    assert plan.terms == []
    assert plan.mode == "subreddit"


# --------------------------------------------------------------------- cache / dedupe
def test_cache_ttl_and_hits():
    cache = RedditResponseCache(ttl_seconds=60)
    key = make_cache_key("GET", "/r/SaaS/new.json", {"limit": 5})
    assert cache.get(key) is None
    cache.set(key, {"ok": True})
    assert cache.get(key) == {"ok": True}
    assert cache.hits == 1

    expired = RedditResponseCache(ttl_seconds=0)
    expired.set("k", "v")
    assert expired.get("k") is None


def test_seen_registry_counts_duplicates():
    registry = SeenRegistry()
    assert registry.first_seen("aaa") is True
    assert registry.first_seen("aaa") is False
    assert registry.duplicates == 1
    assert registry.first_seen("") is False


# --------------------------------------------------------------------- client behaviours
def test_client_success_and_cache_reuse():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"data": {"children": [], "after": None}})

    async def run():
        client = make_client(handler, make_config(cache_ttl_seconds=120))
        first = await client.fetch_listing("/r/SaaS/new.json", {"limit": 5})
        second = await client.fetch_listing("/r/SaaS/new.json", {"limit": 5})
        await client.aclose()
        return first, second

    first, second = asyncio.run(run())
    assert first == second == {"data": {"children": [], "after": None}}
    assert calls["n"] == 1  # second request served from cache


def test_client_403_is_terminal_and_opens_breaker():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(403, text="blocked")

    async def run():
        client = make_client(handler)
        with pytest.raises(RedditAccessDeniedError):
            await client.fetch_listing("/r/SaaS/new.json", {"limit": 5})
        opened = client.controller.circuit_open()
        await client.aclose()
        return opened

    assert asyncio.run(run()) is True
    assert calls["n"] == 1  # never retried
    assert RedditAccessDeniedError("denied").status_code == "ACCESS_RESTRICTED"


def test_client_401_classified_as_auth_required():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorised")

    async def run():
        client = make_client(handler)
        with pytest.raises(RedditAuthRequiredError):
            await client.fetch_listing("/r/SaaS/new.json", {"limit": 5})
        await client.aclose()

    asyncio.run(run())


def test_client_404_is_not_retried():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    async def run():
        client = make_client(handler)
        with pytest.raises(RedditNotFoundError):
            await client.fetch_listing("/r/missing/new.json", {"limit": 5})
        await client.aclose()

    asyncio.run(run())
    assert calls["n"] == 1


def test_client_429_honours_retry_after_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"data": {"children": [], "after": None}})

    async def run():
        client = make_client(handler, make_config(max_retries=2, cache_ttl_seconds=0))
        payload = await client.fetch_listing("/r/SaaS/new.json", {"limit": 5})
        limited = client.controller.rate_limited
        await client.aclose()
        return payload, limited

    payload, limited = asyncio.run(run())
    assert payload["data"]["children"] == []
    assert limited == 1
    assert calls["n"] == 2


def test_client_429_exhausts_bounded_retries():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "0"})

    async def run():
        client = make_client(handler, make_config(max_retries=1))
        with pytest.raises(RedditRateLimitedError):
            await client.fetch_listing("/r/SaaS/new.json", {"limit": 5})
        await client.aclose()

    asyncio.run(run())
    assert calls["n"] == 2  # initial + exactly one retry


def test_client_5xx_bounded_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    async def run():
        client = make_client(handler, make_config(max_retries=1))
        with pytest.raises(RedditServerError):
            await client.fetch_listing("/r/SaaS/new.json", {"limit": 5})
        await client.aclose()

    asyncio.run(run())
    assert calls["n"] == 2


def test_client_timeout_is_bounded():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("slow")

    async def run():
        from leadsweep.integrations.reddit.exceptions import RedditTimeoutError

        client = make_client(handler, make_config(max_retries=1))
        with pytest.raises(RedditTimeoutError):
            await client.fetch_listing("/r/SaaS/new.json", {"limit": 5})
        await client.aclose()

    asyncio.run(run())
    assert calls["n"] == 2


def test_error_classification_table():
    assert isinstance(classify_http_status(401), RedditAuthRequiredError)
    assert isinstance(classify_http_status(403), RedditAccessDeniedError)
    assert isinstance(classify_http_status(404), RedditNotFoundError)
    assert isinstance(classify_http_status(429, retry_after=30), RedditRateLimitedError)
    assert classify_http_status(429, retry_after=30).retry_after_s == 30
    assert isinstance(classify_http_status(500), RedditServerError)
    assert classify_http_status(403).status_code == "ACCESS_RESTRICTED"
    assert classify_http_status(418).status_code == "PARSE_ERROR"


def test_circuit_breaker_opens_and_blocks():
    controller = RedditRequestController(max_retries=0, circuit_breaker_ttl_s=60)
    controller.record_denial("403 from reddit")
    assert controller.circuit_open() is True
    with pytest.raises(RedditCircuitOpenError):
        controller.assert_available()
    controller.record_success()
    assert controller.circuit_open() is False


def test_backoff_respects_retry_after_and_caps():
    controller = RedditRequestController(max_retries=3, backoff_base_s=1.0, backoff_cap_s=10.0)
    assert controller.backoff_delay(3, retry_after_s=7) == pytest.approx(7.0)
    assert controller.backoff_delay(3, retry_after_s=999) == pytest.approx(10.0)
    delay = controller.backoff_delay(2)
    assert 0.5 <= delay <= 4.0


def test_pacing_enforces_minimum_interval():
    controller = RedditRequestController(max_requests_per_minute=60)  # 1 req/sec
    assert controller.min_interval_s == pytest.approx(1.0)
    assert controller.max_requests_per_minute == 60


# --------------------------------------------------------------------- offline service
def test_offline_service_streams_and_dedupes():
    cfg = make_config(mode=OFFLINE_FIXTURES, fixture_dir=FIXTURE_DIR, max_pages=1)

    async def run():
        service = RedditIngestionService(cfg)
        plan = build_plan("scraper agency", {"subreddits": "r/SaaS"}, max_pages=1)
        posts = [p async for p in service.stream(plan)]
        return posts, service.summary

    posts, summary = asyncio.run(run())
    ids = [p.post_id for p in posts]
    assert "aaa111" in ids
    assert "ccc333" not in ids  # removed post never ingested
    assert len(ids) == len(set(ids))
    assert summary.duplicates_skipped >= 1  # subreddit pass + keyword pass overlap
    assert summary.access_mode == OFFLINE_FIXTURES
    assert summary.paid_service_used is False
    assert summary.estimated_api_cost_usd == 0.0
    assert summary.status == "OK"


def test_offline_service_missing_fixtures_reports_cleanly(tmp_path):
    cfg = make_config(mode=OFFLINE_FIXTURES, fixture_dir=tmp_path / "empty")

    async def run():
        service = RedditIngestionService(cfg)
        posts = [p async for p in service.stream(build_plan("anything", {}))]
        return posts, service.summary

    posts, summary = asyncio.run(run())
    assert posts == []
    assert summary.status in ("CONFIG_ERROR", "EMPTY")
    assert summary.status_detail


def test_offline_service_comment_enrichment_is_bounded():
    cfg = make_config(mode=OFFLINE_FIXTURES, fixture_dir=FIXTURE_DIR, comment_budget=1)

    async def run():
        service = RedditIngestionService(cfg)
        posts = [p async for p in service.stream(build_plan("scraper", {"includeComments": True}))]
        return posts, service.summary

    posts, summary = asyncio.run(run())
    first = next(p for p in posts if p.post_id == "aaa111")
    assert len(first.comments) == 1  # [removed] comment filtered out
    assert first.comments[0].post_id == "aaa111"
    assert summary.comments_fetched == 1


def test_service_reports_access_restriction_without_crashing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="blocked")

    cfg = make_config(cache_ttl_seconds=0)
    client = make_client(handler, cfg)

    async def run():
        service = RedditIngestionService(cfg, client=client)
        posts = [p async for p in service.stream(build_plan("scraper", {}))]
        return posts, service.summary

    posts, summary = asyncio.run(run())
    assert posts == []
    assert summary.status == "ACCESS_RESTRICTED"
    assert summary.access_denied_responses == 1
    assert summary.paid_service_used is False


def test_status_payload_exposes_no_credentials():
    status = RedditIngestionService.status()
    assert status["requires_credentials"] is False
    assert status["personal_account_required"] is False
    assert "secret" not in json.dumps(status).lower()
    assert status["mode"] in (PUBLIC_UNAUTHENTICATED, OFFLINE_FIXTURES, "disabled")


# --------------------------------------------------------------------- domain mapping
def test_post_to_tweet_preserves_source_text_verbatim():
    post = normalize_post(_fixture_children()[0])
    tweet = post.to_tweet()
    assert tweet.platform == "reddit"
    assert tweet.id == "reddit_aaa111"
    assert tweet.url == post.permalink
    assert post.title in tweet.text and post.body in tweet.text
    assert tweet.reply_count == 11
    assert tweet.view_count is None  # Reddit exposes no view count
    meta = tweet.extra_metadata or {}
    assert meta["subreddit"] == "SaaS"
    assert meta["permalink"] == post.permalink


def test_reddit_maps_into_existing_16_column_export_schema():
    """Reddit must not change the shared export schema; it maps into existing columns."""
    assert len(LEADS_EXPORT_COLUMNS) == 16
    post = normalize_post(_fixture_children()[0])
    row = {
        "platform": "reddit",
        "author/channel": post.author,
        "post URL": post.permalink,
        "published date": post.created_at,
        "text": post.full_text(),
        "evaluator": "unevaluated",
        "model": "none",
        "category": "unevaluated",
        "score": "",
        "poster role": "unknown",
        "reason": "",
        "evidence quote": "",
        "likes": post.score,
        "replies": post.num_comments,
        "views": "",
        "job id": "run_test",
    }
    csv_text = DatasetExporter.to_csv([row], fieldnames=LEADS_EXPORT_COLUMNS)
    assert isinstance(csv_text, str)
    header = csv_text.lstrip("\ufeff").splitlines()[0]
    assert header == ",".join(f'"{c}"' for c in LEADS_EXPORT_COLUMNS)
    assert '"reddit"' in csv_text
    assert post.permalink in csv_text
    jsonl = DatasetExporter.to_jsonl([row])
    assert json.loads(jsonl.splitlines()[0])["platform"] == "reddit"


def test_reddit_post_model_requires_no_network():
    post = RedditPost(post_id="z1", subreddit="SaaS", title="t", body="b", author="a", permalink="https://r/z1")
    tweet = post.to_tweet()
    assert tweet.like_count == 0 and tweet.reply_count == 0  # absent metrics, not invented values
    assert (tweet.extra_metadata or {})["metrics_complete"] is False


# --------------------------------------------------------------------- live archive provider (arctic_shift)
def test_arctic_shift_listing_and_keyword_filtering():
    calls = {"paths": []}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["paths"].append((request.url.path, dict(request.url.params)))
        if request.url.path == "/api/posts/search":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "1xskgii",
                            "subreddit": "SaaS",
                            "title": "Looking for an AI automation agency to help with outbound",
                            "selftext": "We need help building a workflow pipeline.",
                            "author": "yuvals41",
                            "permalink": "/r/SaaS/comments/1xskgii/looking_for_an_ai_automation_agency/",
                            "created_utc": 1794309891,
                            "retrieved_on": 1794309910,
                            "score": 5,
                            "upvote_ratio": 1.0,
                            "num_comments": 3,
                            "over_18": False,
                            "locked": False,
                        },
                        {
                            "id": "1xsn3xf",
                            "subreddit": "SaaS",
                            "title": "Unrelated general discussion thread",
                            "selftext": "Just sharing weekend thoughts.",
                            "author": "founder_two",
                            "permalink": "/r/SaaS/comments/1xsn3xf/unrelated_general_discussion/",
                            "created_utc": 1794317873,
                            "retrieved_on": 1794317891,
                            "score": 1,
                            "upvote_ratio": 1.0,
                            "num_comments": 0,
                            "over_18": False,
                            "locked": False,
                        },
                    ]
                },
            )
        if request.url.path == "/api/comments/tree":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "kind": "t1",
                            "data": {
                                "id": "c_live_1",
                                "author": "helper_dev",
                                "body": "We built something similar last quarter.",
                                "created_utc": 1794310000,
                                "permalink": "/r/SaaS/comments/1xskgii/looking/c_live_1/",
                                "score": 2,
                            },
                        }
                    ]
                },
            )
        return httpx.Response(404)

    cfg = make_config(
        mode=PUBLIC_UNAUTHENTICATED,
        source_provider=PROVIDER_ARCTIC_SHIFT,
        base_url=DEFAULT_ARCHIVE_BASE_URL,
        cache_ttl_seconds=120,
        comment_budget=1,
    )
    client = make_client(handler, cfg)

    async def run():
        service = RedditIngestionService(cfg, client=client)
        plan = build_plan("automation agency", {"subreddits": "r/SaaS", "includeComments": True}, max_pages=1)
        posts = [p async for p in service.stream(plan)]
        return posts, service.summary

    posts, summary = asyncio.run(run())
    assert len(posts) == 2  # keyword match first + subreddit stream second (deduped)
    first = posts[0]
    assert first.post_id == "1xskgii"
    assert first.source_provider == PROVIDER_ARCTIC_SHIFT
    assert first.retrieved_on_archive == 1794309910
    assert first.validate_live_record() is True
    assert len(first.comments) == 1
    assert first.comments[0].comment_id == "c_live_1"
    assert summary.status == "OK"
    assert summary.ui_state == "LIVE SOURCE AVAILABLE"
    assert summary.duplicates_skipped >= 1
    # Cache ensured /api/posts/search was only hit once for r/SaaS across expanded terms + subreddit listing
    search_calls = [p for p, _ in calls["paths"] if p == "/api/posts/search"]
    assert len(search_calls) == 1


def test_validate_live_record_rejects_incomplete_or_removed_posts():
    valid = RedditPost(
        post_id="1xskgii",
        subreddit="SaaS",
        title="Need an automation agency",
        body="Looking for recommendations",
        author="yuvals41",
        permalink="https://www.reddit.com/r/SaaS/comments/1xskgii/need_an_automation_agency/",
        created_at="2026-11-10T11:24:51+00:00",
    )
    assert valid.validate_live_record() is True

    bad_url = RedditPost(
        post_id="1xskgii",
        subreddit="SaaS",
        title="Need an automation agency",
        body="Body",
        author="yuvals41",
        permalink="https://example.com/not-reddit",
        created_at="2026-11-10T11:24:51+00:00",
    )
    assert bad_url.validate_live_record() is False

    removed = RedditPost(
        post_id="1xskgii",
        subreddit="SaaS",
        title="Need an automation agency",
        body="Body",
        author="yuvals41",
        permalink="https://www.reddit.com/r/SaaS/comments/1xskgii/need_an_automation_agency/",
        created_at="2026-11-10T11:24:51+00:00",
        removed=True,
    )
    assert removed.validate_live_record() is False


def test_ui_state_transitions_across_modes():
    class LiveSettings:
        reddit_enabled = True
        reddit_access_mode = PUBLIC_UNAUTHENTICATED
        reddit_source_provider = PROVIDER_ARCTIC_SHIFT

    st_live = RedditIngestionService.status(LiveSettings())
    assert st_live["ui_state"] in ("LIVE SOURCE AVAILABLE", "SOURCE DEGRADED")
    assert st_live["source_provider"] == PROVIDER_ARCTIC_SHIFT

    class DirectJsonSettings:
        reddit_enabled = True
        reddit_access_mode = PUBLIC_UNAUTHENTICATED
        reddit_source_provider = PROVIDER_REDDIT_JSON

    st_direct = RedditIngestionService.status(DirectJsonSettings())
    assert st_direct["ui_state"] == "ACCESS RESTRICTED"

    class DisabledSettings:
        reddit_enabled = False
        reddit_access_mode = "disabled"

    st_disabled = RedditIngestionService.status(DisabledSettings())
    assert st_disabled["ui_state"] == "LIVE SOURCE UNAVAILABLE"

