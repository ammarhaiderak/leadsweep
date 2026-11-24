"""
Regression tests for the Telegram hotfix (ignored_archive/fix-prompt.md).

Covers:
- Channel normalization (@channel, https://t.me/channel, t.me/s/channel, junk around it).
- HTML message extraction from t.me/s/ markup, including optional/missing fields.
- Flexible query matching ("We need to hire new developer" ~ "Hiring a Python developer").
- Adapter status: reachable channel with 0 matches -> EMPTY (never a failure);
  private/missing channel -> ACCESS_RESTRICTED with a human-readable message.
- Job lifecycle via /v1/scrape: 0 matches / NO_CANDIDATES -> succeeded with 0 items;
  private channel -> failed with "Channel is private or does not exist".
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import scripts._mock_guard  # noqa: F401

from leadsweep.services import telegram_public_scraper as tps
from leadsweep.services.telegram_public_scraper import (
    ACCESS_RESTRICTED_DETAIL,
    PublicTelegramMessage,
    TelegramPublicScraper,
    matches_query,
    normalize_channel_handle,
    query_match_score,
    search_term_for_query,
)
from leadsweep.telegram_scraper import TelegramAdapter

QUERY = "We need to hire new developer"


@pytest.fixture(autouse=True)
def _reset_transport_state():
    tps._PAGE_CACHE.clear()
    tps._TRANSPORT_MGR.reset_for_tests()
    yield
    tps._PAGE_CACHE.clear()
    tps._TRANSPORT_MGR.reset_for_tests()


# ---------------------------------------------------------------------------
# 1. Channel normalization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw",
    [
        "remotejobs_dev",
        "@remotejobs_dev",
        "  @remotejobs_dev  ",
        "@remotejobs_dev/",
        "https://t.me/remotejobs_dev",
        "http://t.me/remotejobs_dev/",
        "t.me/remotejobs_dev",
        "t.me/s/remotejobs_dev",
        "https://t.me/s/remotejobs_dev/",
        "https://t.me/s/remotejobs_dev?before=120",
        "https://t.me/remotejobs_dev/5197",
        "https://www.telegram.me/remotejobs_dev",
        "<https://t.me/remotejobs_dev>",
        '"@remotejobs_dev"',
    ],
)
def test_normalize_channel_variants(raw):
    assert normalize_channel_handle(raw) == "remotejobs_dev"


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "https://t.me/joinchat/AAAAAE", "t.me/+AbCdEf123", "https://t.me/s/", "@a b c"],
)
def test_normalize_channel_rejects_invalid(raw):
    with pytest.raises(ValueError):
        normalize_channel_handle(raw)


# ---------------------------------------------------------------------------
# 2. HTML extraction from t.me/s/ markup
# ---------------------------------------------------------------------------

TME_S_HTML = """
<html><body>
<div class="tgme_channel_info">
  <div class="tgme_channel_info_header_title"><span>Remote Work Jobs</span></div>
  <div class="tgme_channel_info_description">Remote vacancies every day</div>
</div>
<section class="tgme_channel_history js-message_history">
  <div class="tgme_widget_message_wrap js-widget_message_wrap">
    <div class="tgme_widget_message text_not_supported_wrap js-widget_message" data-post="remoteworkers/501">
      <div class="tgme_widget_message_bubble">
        <div class="tgme_widget_message_text js-message_text" dir="auto">
          <b>Hiring</b> a Python developer<br/>Remote, full time. Apply: <a href="https://jobs.example.com/py">link</a>
        </div>
        <div class="tgme_widget_message_footer">
          <span class="tgme_widget_message_from_author">Jane Recruiter</span>
          <span class="tgme_widget_message_views">2.3K</span>
          <a class="tgme_widget_message_date" href="https://t.me/remoteworkers/501">
            <time datetime="2026-11-20T09:15:00+00:00" class="time">09:15</time>
          </a>
        </div>
      </div>
    </div>
  </div>
  <div class="tgme_widget_message_wrap js-widget_message_wrap">
    <div class="tgme_widget_message js-widget_message">
      <div class="tgme_widget_message_bubble">
        <div class="tgme_widget_message_text js-message_text">Looking for a dev to build an MVP</div>
        <a class="tgme_widget_message_date" href="https://t.me/remoteworkers/502">
          <time datetime="2026-11-21T10:00:00+00:00">10:00</time>
        </a>
      </div>
    </div>
  </div>
  <div class="tgme_widget_message_wrap js-widget_message_wrap">
    <div class="tgme_widget_message js-widget_message" data-post="remoteworkers/503">
      <div class="tgme_widget_message_photo_wrap"></div>
    </div>
  </div>
</section>
</body></html>
"""

PRIVATE_HTML = """
<html><body><div class="tgme_page"><div class="tgme_page_title">Some Name</div>
<div class="tgme_page_extra">If you have Telegram, you can contact @some_name right away.</div>
<a class="tgme_action_button_new">Send Message</a></div></body></html>
"""

NO_MATCH_HTML = """
<html><body><div class="tgme_channel_info"><div class="tgme_channel_info_header_title">Crypto News</div></div>
<div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="remoteworkers/700">
  <div class="tgme_widget_message_text">Bitcoin hits a new all-time high today</div>
  <time datetime="2026-11-22T08:00:00+00:00">08:00</time></div></div>
<div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="remoteworkers/701">
  <div class="tgme_widget_message_text">Weekly market recap and charts</div>
  <time datetime="2026-11-22T09:00:00+00:00">09:00</time></div></div>
</body></html>
"""


def test_parse_tme_s_markup_extracts_messages():
    msgs, oldest_id, title = TelegramPublicScraper().parse_page_html(TME_S_HTML, "remoteworkers")
    assert title == "Remote Work Jobs"
    assert [m.message_id for m in msgs] == [501, 502, 503]
    assert oldest_id == 501

    first = msgs[0]
    assert "Hiring" in first.text and "Python developer" in first.text
    assert first.author == "Jane Recruiter"
    assert first.views == 2300
    assert first.source_published_at == "2026-11-20T09:15:00+00:00"
    assert first.post_url == "https://t.me/remoteworkers/501"
    assert "https://jobs.example.com/py" in first.links
    assert first.channel_description == "Remote vacancies every day"

    # Missing data-post: ID recovered from the date permalink; optional fields absent.
    second = msgs[1]
    assert second.text == "Looking for a dev to build an MVP"
    assert second.author is None
    assert second.views is None

    # Media-only post with no text/date still parses.
    third = msgs[2]
    assert third.has_media and third.media_type == "photo"
    assert third.source_published_at is None


def test_parse_without_wrap_class_falls_back_to_data_post():
    html = TME_S_HTML.replace("tgme_widget_message_wrap", "tgme_widget_message_container_v2")
    msgs, _, _ = TelegramPublicScraper().parse_page_html(html, "remoteworkers")
    assert {501, 503} <= {m.message_id for m in msgs}


def _mock_client(html: str, status: int = 200, url: str = "https://t.me/s/remoteworkers"):
    resp = AsyncMock()
    resp.status_code = status
    resp.text = html
    resp.url = url
    resp.headers = {}
    client = AsyncMock()
    client.get = AsyncMock(return_value=resp)
    return client


@pytest.mark.asyncio
async def test_fetch_private_channel_reports_clear_message():
    status, _, err, _ = await TelegramPublicScraper().fetch_channel_page(_mock_client(PRIVATE_HTML), "some_name")
    assert status == "ACCESS_RESTRICTED"
    assert err.startswith("Channel is private or does not exist")


@pytest.mark.asyncio
async def test_fetch_redirect_off_preview_is_access_restricted():
    client = _mock_client(PRIVATE_HTML, url="https://t.me/some_name")
    status, _, err, _ = await TelegramPublicScraper().fetch_channel_page(client, "some_name")
    assert status == "ACCESS_RESTRICTED"
    assert err == ACCESS_RESTRICTED_DETAIL


# ---------------------------------------------------------------------------
# 3. Flexible query matching
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "Hiring a Python developer",
        "Looking for a dev",
        "We're recruiting backend engineers (remote)",
        "VACANCY: Senior Software Engineer",
        "we need to hire new developer asap",
    ],
)
def test_flexible_match_positive(text):
    assert matches_query(QUERY, text)


@pytest.mark.parametrize(
    "text",
    ["Bitcoin hits a new all-time high today", "Selling used furniture", "Weekly market recap", ""],
)
def test_flexible_match_negative(text):
    assert not matches_query(QUERY, text)


def test_exact_phrase_scores_full_and_search_term_is_specific():
    assert query_match_score(QUERY, "Update: we need to hire new developer for our team") == 1.0
    # Telegram's ?q= needs every word present; a full sentence finds nothing, so send one term.
    assert search_term_for_query(QUERY) == "developer"
    assert matches_query("", "anything at all")


# ---------------------------------------------------------------------------
# 4a. Adapter status: EMPTY vs ACCESS_RESTRICTED (no network)
# ---------------------------------------------------------------------------

def _msg(mid: int, text: str) -> PublicTelegramMessage:
    return PublicTelegramMessage(
        message_id=mid, channel="remoteworkers", channel_title="Remote Work Jobs", text=text,
        source_published_at="2026-11-22T08:00:00+00:00", date="2026-11-22T08:00:00+00:00",
        post_url=f"https://t.me/remoteworkers/{mid}",
    )


def _adapter_with(scrape_result) -> TelegramAdapter:
    adapter = TelegramAdapter()
    adapter.public_scraper = AsyncMock()
    adapter.public_scraper.scrape_channel_with_status = AsyncMock(return_value=scrape_result)
    adapter.scraper = None  # no Telethon fallback
    return adapter


async def _collect(adapter: TelegramAdapter, query: str, n: int = 5):
    return [r async for r in adapter.search(query, max_items=n)]


@pytest.mark.asyncio
async def test_adapter_flexible_match_yields_leads():
    adapter = _adapter_with(([_msg(1, "Hiring a Python developer"), _msg(2, "Market recap")], "OK", None))
    with patch.object(TelegramAdapter, "_llm_judge_configured", staticmethod(lambda: False)):
        leads = await _collect(adapter, f"@remoteworkers {QUERY}")
    assert [l.source_id for l in leads] == ["1"]
    assert adapter.last_scrape_status == "OK"
    # Telegram is searched with a short term, not the full sentence.
    first_call = adapter.public_scraper.scrape_channel_with_status.await_args_list[0]
    assert first_call.kwargs["search_q"] == "developer"


@pytest.mark.asyncio
async def test_adapter_no_match_is_empty_not_failure():
    adapter = _adapter_with(([_msg(1, "Bitcoin hits a new high"), _msg(2, "Market recap")], "OK", None))
    with patch.object(TelegramAdapter, "_llm_judge_configured", staticmethod(lambda: False)):
        leads = await _collect(adapter, f"@remoteworkers {QUERY}")
    assert leads == []
    assert adapter.last_scrape_status == "EMPTY"
    assert "remoteworkers" in adapter.last_scrape_detail


@pytest.mark.asyncio
async def test_adapter_no_match_passes_recent_posts_to_llm_judge():
    adapter = _adapter_with(([_msg(1, "Bitcoin hits a new high"), _msg(2, "Market recap")], "OK", None))
    with patch.object(TelegramAdapter, "_llm_judge_configured", staticmethod(lambda: True)):
        leads = await _collect(adapter, f"@remoteworkers {QUERY}")
    assert sorted(l.source_id for l in leads) == ["1", "2"]
    assert adapter.last_scrape_status == "OK"


@pytest.mark.asyncio
async def test_adapter_private_channel_is_access_restricted():
    adapter = _adapter_with(([], "ACCESS_RESTRICTED", ACCESS_RESTRICTED_DETAIL))
    leads = await _collect(adapter, f"@some_private {QUERY}")
    assert leads == []
    assert adapter.last_scrape_status == "ACCESS_RESTRICTED"
    assert adapter.last_scrape_detail.startswith("Channel is private or does not exist")
    # ACCESS_RESTRICTED is the same for every page: don't keep hammering the handle.
    assert adapter.public_scraper.scrape_channel_with_status.await_count == 1


# ---------------------------------------------------------------------------
# 4b. Job lifecycle through /v1/scrape
# ---------------------------------------------------------------------------

async def _run_telegram_job(query: str) -> dict:
    from leadsweep.api import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/v1/scrape", json={
            "type": "search", "query": query, "max_items": 3,
            "platform": "telegram", "user_email": "owner@example.com",
        })
        assert resp.status_code in (200, 201), resp.text
        run_id = resp.json()["id"]
        info: dict = {}
        for _ in range(60):
            r = await client.get(f"/v1/jobs/{run_id}")
            if r.status_code == 200:
                info = r.json()
                if info.get("status") in ("completed", "succeeded", "failed", "partial"):
                    break
            await asyncio.sleep(0.25)
        return info


def _fake_fetch(html: str, status: str = "OK", err: str | None = None):
    async def fetch(self, client, channel, before_id=None, search_q=None, job_id="default"):
        if before_id:  # single page only
            return "OK", "<html></html>", None, "direct"
        return status, html, err, "direct"
    return fetch


@pytest.mark.asyncio
async def test_job_no_matching_posts_completes_with_zero_leads():
    with patch.object(TelegramPublicScraper, "fetch_channel_page", _fake_fetch(NO_MATCH_HTML)), \
         patch.object(TelegramAdapter, "_llm_judge_configured", staticmethod(lambda: False)):
        info = await _run_telegram_job(f"@remoteworkers {QUERY}")
    assert info.get("status") in ("succeeded", "completed"), info
    assert info["itemsScraped"] == 0
    assert "NO_CANDIDATES" not in (info.get("error_detail") or "")
    assert (info.get("error_detail") or "").startswith("EMPTY")


@pytest.mark.asyncio
async def test_job_no_candidates_completes_not_failed():
    async def no_candidates(self, query, max_items=20, filters=None):
        self.last_scrape_status = "NO_CANDIDATES"
        self.last_scrape_detail = f"No public candidate channels found for query '{query}'."
        return
        yield  # pragma: no cover

    with patch.object(TelegramAdapter, "search", no_candidates):
        info = await _run_telegram_job(QUERY)
    assert info.get("status") in ("succeeded", "completed"), info
    assert (info.get("error_detail") or "").startswith("NO_CANDIDATES")


@pytest.mark.asyncio
async def test_job_private_channel_fails_with_clear_message():
    with patch.object(TelegramPublicScraper, "fetch_channel_page",
                      _fake_fetch("", "ACCESS_RESTRICTED", ACCESS_RESTRICTED_DETAIL)):
        info = await _run_telegram_job(f"@some_private {QUERY}")
    assert info.get("status") == "failed", info
    assert "Channel is private or does not exist" in (info.get("error_detail") or "")



@pytest.mark.asyncio
async def test_job_flexible_match_survives_relevance_gate():
    """A post that only loosely matches the query must reach the dataset, not be dropped downstream."""
    with patch.object(TelegramPublicScraper, "fetch_channel_page", _fake_fetch(TME_S_HTML)), \
         patch.object(TelegramAdapter, "_llm_judge_configured", staticmethod(lambda: False)):
        info = await _run_telegram_job(f"@remoteworkers {QUERY}")
    assert (info.get("itemsScraped") or 0) >= 1, info
    assert info.get("status") != "failed" or "AI evaluation" in (info.get("error_detail") or ""), info


@pytest.mark.parametrize(
    "text",
    [
        "Also in this update, users can join and create closed communities",
        "Developers can create flexible interfaces for bots using JavaScript",
    ],
)
def test_single_concept_does_not_match_two_concept_query(text):
    """Seen live on @telegram: product news mentioning only 'join' or 'developers' is not a hiring lead."""
    assert not matches_query(QUERY, text)
