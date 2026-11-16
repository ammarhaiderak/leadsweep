"""Reddit API/job integration tests (offline fixtures, no live Reddit calls).

Exercises the real FastAPI app: status endpoint, job creation through the existing JobWorker,
persistence into the shared store, Data Explorer payload, unified export and failure isolation.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def reddit_fixture_env(monkeypatch, tmp_db):
    """Point Reddit at offline fixtures so the job runs with zero network and zero credentials."""
    monkeypatch.setenv("LEADSWEEP_REDDIT_ACCESS_MODE", "offline_fixtures")
    monkeypatch.setenv("LEADSWEEP_REDDIT_FIXTURE_DIR", "tests/fixtures/reddit")
    return tmp_db


def _wait_terminal(client: TestClient, run_id: str, timeout_s: float = 45.0) -> dict:
    deadline = time.time() + timeout_s
    last: dict = {}
    while time.time() < deadline:
        resp = client.get(f"/v1/jobs/{run_id}")
        if resp.status_code == 200:
            last = resp.json()
            if str(last.get("status", "")).lower() in ("completed", "failed", "partial", "succeeded"):
                return last
        time.sleep(0.4)
    return last


def test_reddit_status_reports_no_credentials(client, reddit_fixture_env):
    resp = client.get("/v1/reddit/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["requires_credentials"] is False
    assert body["credentials_configured"] is False
    assert body["personal_account_required"] is False
    assert body["mode"] == "offline_fixtures"
    assert body["fixtures_present"] >= 1
    assert body["ready"] is True
    assert "oauth" in body["documented_access_note"].lower()


def test_reddit_job_runs_end_to_end_from_fixtures(client, reddit_fixture_env):
    payload = {
        "platform": "reddit",
        "type": "subreddit_posts",
        "query": "scraper agency",
        "maxItems": 5,
        "user_email": "owner@example.com",
        "options": {"subreddits": "r/SaaS", "includeComments": True},
    }
    resp = client.post("/v1/scrape", json=payload)
    assert resp.status_code in (200, 201), resp.text
    run_id = resp.json()["id"]

    job = _wait_terminal(client, run_id)
    assert str(job.get("status")).lower() in ("completed", "partial"), job
    assert int(job.get("itemsScraped") or 0) >= 1

    data = client.get(f"/v1/data/{run_id}?limit=50")
    assert data.status_code == 200, data.text
    items = data.json()
    assert items, "Reddit job produced no Data Explorer items"
    reddit_items = [i for i in items if i.get("platform") == "reddit"]
    assert reddit_items, items[:2]
    first = reddit_items[0]
    assert first["url"].startswith("https://www.reddit.com/r/")
    assert first["author_username"] in ("founder_sam", "r_SaaS", "r_webdev") or first["author_username"]
    assert first.get("subreddit") in ("SaaS", "webdev")


def test_reddit_jobs_deduplicate_across_runs(client, reddit_fixture_env):
    payload = {
        "platform": "reddit",
        "type": "intent_search",
        "query": "scraper agency",
        "maxItems": 5,
        "user_email": "owner@example.com",
        "options": {"subreddits": "r/SaaS"},
    }
    ids = []
    for _ in range(2):
        resp = client.post("/v1/scrape", json=payload)
        assert resp.status_code in (200, 201), resp.text
        ids.append(resp.json()["id"])
        _wait_terminal(client, ids[-1])

    import sqlite3

    con = sqlite3.connect(reddit_fixture_env)
    try:
        count = con.execute("SELECT COUNT(*) FROM tweets WHERE id = 'reddit_aaa111'").fetchone()[0]
        platform = con.execute("SELECT platform FROM tweets WHERE id = 'reddit_aaa111'").fetchone()
    finally:
        con.close()
    assert count == 1, "Duplicate Reddit post was inserted twice"
    assert platform[0] == "reddit"


def test_reddit_export_keeps_sixteen_column_schema(client, reddit_fixture_env):
    payload = {
        "platform": "reddit",
        "type": "search",
        "query": "scraper",
        "maxItems": 3,
        "user_email": "owner@example.com",
        "options": {"subreddits": "r/SaaS"},
    }
    resp = client.post("/v1/scrape", json=payload)
    assert resp.status_code in (200, 201), resp.text
    run_id = resp.json()["id"]
    _wait_terminal(client, run_id)

    export = client.get(f"/v1/data/export?scope=job&job_id={run_id}&format=csv&kind=leads")
    assert export.status_code == 200, export.text
    text = export.content.decode("utf-8-sig")
    header = text.splitlines()[0].split(",")
    assert len(header) == 16, header
    assert header[0] == '"platform"'
    assert header[-1] == '"job id"'
    assert "reddit" in text

    jsonl = client.get(f"/v1/data/export?scope=job&job_id={run_id}&format=jsonl&kind=leads")
    assert jsonl.status_code == 200
    assert '"platform": "reddit"' in jsonl.text


def test_reddit_access_denial_fails_isolated_and_reports_status(client, monkeypatch, tmp_db):
    """A Reddit refusal must fail that job only, with a clear reason, and never crash the app."""
    monkeypatch.setenv("LEADSWEEP_REDDIT_ACCESS_MODE", "public_unauthenticated")

    from leadsweep.integrations.reddit.client import RedditClient
    from leadsweep.integrations.reddit.exceptions import RedditAccessDeniedError

    async def _denied(self, *_args, **_kwargs):
        raise RedditAccessDeniedError("Reddit refused this request (HTTP 403).")

    monkeypatch.setattr(RedditClient, "_get_json", _denied, raising=True)

    payload = {
        "platform": "reddit",
        "type": "search",
        "query": "need an agency",
        "maxItems": 3,
        "user_email": "owner@example.com",
    }
    resp = client.post("/v1/scrape", json=payload)
    assert resp.status_code in (200, 201), resp.text
    run_id = resp.json()["id"]
    job = _wait_terminal(client, run_id)

    assert str(job.get("status")).lower() == "failed", job
    detail = str(job.get("errorDetail") or job.get("status_detail") or "")
    assert "ACCESS_RESTRICTED" in detail, job

    # The rest of the application is unaffected.
    assert client.get("/health").status_code == 200
    assert client.get("/v1/reddit/status").status_code == 200
    assert client.get("/v1/jobs").status_code == 200


def test_existing_platform_dispatch_still_maps_x_and_telegram(client):
    """Regression guard: adding Reddit types must not change X/Telegram routing."""
    from leadsweep.adapters import PlatformAdapterRegistry

    for platform in ("twitter", "x", "telegram", "reddit"):
        assert platform in PlatformAdapterRegistry.supported_platforms()

    adapter = PlatformAdapterRegistry.get("reddit")
    assert adapter.platform_name == "reddit"
    # X routing is untouched.
    assert PlatformAdapterRegistry.get("twitter").platform_name == "twitter"
