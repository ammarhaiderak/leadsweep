# NEW FEATURE: Unit and Integration Tests for Telegram Public HTTP Scraper
"""
Tests for TelegramPublicScraper ($0, zero-account, web-preview based scraper).
Tests:
- URL normalization & rejection of private invite links.
- Parsing of realistic t.me/s/ HTML fixture.
- Parsing of empty channel HTML.
- Handling of preview-disabled / private channels (ACCESS_RESTRICTED).
- Pagination (?before=) and deduplication.
- Timeout and retry error handling.
- Judge evaluation integration on Telegram messages.
"""
import pytest
from unittest.mock import AsyncMock, patch
import httpx

from leadsweep.services.telegram_public_scraper import (
    TelegramPublicScraper,
    normalize_channel_handle,
    PublicTelegramMessage,
)
from leadsweep.leadintel.judge import judge_candidate
from leadsweep.leadintel.models import DirectionLabel


SAMPLE_TELEGRAM_HTML = """
<!DOCTYPE html>
<html>
<head><title>Remote Jobs - Telegram</title></head>
<body>
  <div class="tgme_channel_info_header_title">Remote Tech Jobs</div>
  <div class="tgme_channel_info_header_username">@remotejobs_dev</div>
  
  <div class="tgme_widget_message_wrap">
    <div class="tgme_widget_message" data-post="remotejobs_dev/101">
      <div class="tgme_widget_message_text">
        Looking for a Senior Python Developer with FastAPI and Postgres experience.
        Budget: $7,000 - $9,000 / month.
        Apply here: https://company.com/apply or message @tech_recruiter
      </div>
      <div class="tgme_widget_message_views">1.5K</div>
      <div class="tgme_widget_message_forwards">12</div>
      <time datetime="2026-10-16T12:00:00+00:00">12:00 PM</time>
    </div>
  </div>

  <div class="tgme_widget_message_wrap">
    <div class="tgme_widget_message" data-post="remotejobs_dev/102">
      <div class="tgme_widget_message_text">
        Need someone to build an MVP smart contract on Solana. Paid project.
      </div>
      <div class="tgme_widget_message_photo_wrap"></div>
      <div class="tgme_widget_message_views">850</div>
      <time datetime="2026-10-16T13:30:00+00:00">1:30 PM</time>
    </div>
  </div>
</body>
</html>
"""

EMPTY_CHANNEL_HTML = """
<!DOCTYPE html>
<html>
<body>
  <div class="tgme_channel_info_header_title">Empty Channel</div>
  <div class="tgme_widget_message_empty">No posts yet</div>
</body>
</html>
"""

PRIVATE_OR_RESTRICTED_HTML = """
<!DOCTYPE html>
<html>
<body>
  <div class="tgme_page_action">
    <a href="tg://resolve?domain=secret_group">View in Telegram</a>
  </div>
</body>
</html>
"""


def test_telegram_handle_normalization():
    """Verify input normalization and strict rejection of private invite links."""
    assert normalize_channel_handle("remotejobs_dev") == "remotejobs_dev"
    assert normalize_channel_handle("@remotejobs_dev") == "remotejobs_dev"
    assert normalize_channel_handle("https://t.me/remotejobs_dev") == "remotejobs_dev"
    assert normalize_channel_handle("https://t.me/s/remotejobs_dev/") == "remotejobs_dev"
    assert normalize_channel_handle("telegram.me/s/crypto_leads") == "crypto_leads"

    # Rejection of private links (C5)
    with pytest.raises(ValueError, match="Private groups and chats can't be read without joining with an account. Only public channels with a web preview are supported."):
        normalize_channel_handle("https://t.me/joinchat/AAAAAFc_xyz")

    with pytest.raises(ValueError, match="Private groups and chats can't be read without joining with an account. Only public channels with a web preview are supported."):
        normalize_channel_handle("https://t.me/+AbCdEfGhIjK")

    with pytest.raises(ValueError, match="cannot be empty"):
        normalize_channel_handle("   ")

    with pytest.raises(ValueError, match="Invalid Telegram channel"):
        normalize_channel_handle("invalid!channel#name")


def test_telegram_page_parser_success():
    """Verify DOM extraction of authentic message fields without synthetic padding."""
    scraper = TelegramPublicScraper()
    messages, oldest_id, channel_title = scraper.parse_page_html(SAMPLE_TELEGRAM_HTML, "remotejobs_dev")

    assert channel_title == "Remote Tech Jobs"
    assert len(messages) == 2
    assert oldest_id == 101

    m1 = messages[0]
    assert m1.message_id == 101
    assert m1.channel == "remotejobs_dev"
    assert "Looking for a Senior Python Developer" in m1.text
    assert m1.views == 1500
    assert m1.forwards == 12
    assert m1.date == "2026-10-16T12:00:00+00:00"
    assert m1.post_url == "https://t.me/remotejobs_dev/101"
    assert "https://company.com/apply" in m1.links
    assert m1.has_media is False

    m2 = messages[1]
    assert m2.message_id == 102
    assert m2.views == 850
    assert m2.has_media is True
    assert m2.media_type == "photo"


def test_telegram_empty_channel_parsing():
    """Verify clean handling of channels with zero messages."""
    scraper = TelegramPublicScraper()
    messages, oldest_id, channel_title = scraper.parse_page_html(EMPTY_CHANNEL_HTML, "empty_channel")

    assert channel_title == "Empty Channel"
    assert len(messages) == 0
    assert oldest_id is None


@pytest.mark.asyncio
async def test_telegram_fetch_access_restricted():
    """Verify that private groups or preview-disabled channels return ACCESS_RESTRICTED status."""
    scraper = TelegramPublicScraper()

    mock_client = AsyncMock()
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.text = PRIVATE_OR_RESTRICTED_HTML
    mock_resp.url = "https://t.me/s/private_channel"
    mock_client.get = AsyncMock(return_value=mock_resp)

    status, html, err, transport = await scraper.fetch_channel_page(mock_client, "private_channel")
    assert status == "ACCESS_RESTRICTED"
    assert err.startswith("Channel is private or does not exist")


@pytest.mark.asyncio
async def test_telegram_fetch_timeout_and_retry_exhaustion():
    """Verify that connection failures properly exhaust retries and return SOURCE_UNAVAILABLE cleanly."""
    scraper = TelegramPublicScraper(max_retries=2)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectTimeout("Connect timed out"))

    status, html, err, transport = await scraper.fetch_channel_page(mock_client, "timeout_channel")
    assert status == "SOURCE_UNAVAILABLE"
    assert "timeout" in err.lower() or "failed" in err.lower()


@pytest.mark.asyncio
async def test_telegram_streaming_and_deduplication():
    """Verify that pagination backwards stops correctly and deduplicates repeated message IDs."""
    scraper = TelegramPublicScraper(max_pages_cap=2, request_delay=0)

    with patch.object(scraper, "fetch_channel_page", AsyncMock(return_value=("OK", SAMPLE_TELEGRAM_HTML, None, "direct"))):
        collected = []
        async for msg in scraper.scrape_channel("remotejobs_dev", limit=10):
            collected.append(msg)

        # Since sample has 2 items and subsequent page returns same mock, deduplication must keep only 2 unique items
        assert len(collected) == 2
        assert collected[0].message_id == 101
        assert collected[1].message_id == 102
        assert collected[0].transport_used == "direct"


def test_judge_integration_on_telegram_messages():
    """Verify that authentic Telegram text runs through judge_candidate with exact verbatim quote verification."""
    from leadsweep.leadintel.brief import LeadBrief

    brief = LeadBrief(
        query="python developer",
        target_role="founder",
        industry="tech",
        offer="Senior Python Development Services",
        negative_signals=[]
    )
    # Lead post matching RE_BUYER_SIGNAL
    lead_text = "We are launching next month and need a developer to build our backend. Budget: $10,000."
    score_res = judge_candidate(lead_text, author_bio="Tech Founder", author_followers=1200, brief=brief)
    assert score_res.direction in (DirectionLabel.BUYER_SIGNAL, DirectionLabel.HIRING_SIGNAL)
    assert score_res.final_score >= 60
    assert score_res.quote_verified is True
    assert score_res.evidence_quote != ""
    assert score_res.evidence_quote in lead_text

    # Irrelevant / Job Seeker post in channel
    seeker_text = "Seeking opportunities as a Junior Frontend Developer. Available for hire immediately."
    seeker_score = judge_candidate(seeker_text, author_bio="Telegram user", brief=brief)
    assert seeker_score.direction == DirectionLabel.JOB_SEEKER
    assert seeker_score.final_score <= 20  # Direction cap enforced
