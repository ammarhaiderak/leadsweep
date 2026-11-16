"""Unit and mock tests for Telegram Scraper and Platform Isolation."""
import asyncio
import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from leadsweep.adapters import PlatformAdapterRegistry
from leadsweep.telegram_scraper import TelegramMessageRecord, TelegramScraper, TelegramAdapter, TelegramChannelInfo


def test_telegram_handle_cleaning():
    """Verify clean_handle extracts pure usernames from handles, URLs, and t.me paths."""
    assert TelegramScraper.clean_handle("@remotejobs_dev") == "remotejobs_dev"
    assert TelegramScraper.clean_handle("https://t.me/remotejobs_dev") == "remotejobs_dev"
    assert TelegramScraper.clean_handle("https://telegram.me/s/crypto_jobs/") == "crypto_jobs"
    assert TelegramScraper.clean_handle("ai_jobs") == "ai_jobs"


def test_telegram_message_record_to_lead_record():
    """Verify TelegramMessageRecord converts accurately to canonical LeadRecord without hallucinations."""
    rec = TelegramMessageRecord(
        message_id=4521,
        channel="remotejobs_dev",
        channel_id=-1001234567,
        sender_id=987654321,
        sender_username="recruiter_bob",
        sender_name="Bob Talent Lead",
        text="Hiring a Senior Python Engineer for a verified fintech contract. $8000/month.",
        date="2026-10-16T12:00:00Z",
        views=1520,
        forwards=14,
        reactions_count=42,
        reply_to_msg_id=None,
        media_type=None,
        links=["https://example.com/apply"],
        mentions=["@recruiter_bob"],
        raw_url="https://t.me/remotejobs_dev/4521"
    )
    lead = rec.to_lead_record()
    assert lead.platform == "telegram"
    assert lead.source_id == "4521"
    assert lead.source_url == "https://t.me/remotejobs_dev/4521"
    assert lead.username == "recruiter_bob"
    assert lead.name == "Bob Talent Lead"
    assert "Hiring a Senior Python Engineer" in lead.content
    assert lead.engagement["views"] == 1520
    assert lead.engagement["forwards"] == 14
    assert lead.engagement["reactions"] == 42


@pytest.mark.asyncio
async def test_mock_telethon_scrape_channel_messages():
    """Mock Telethon client.iter_messages to test Telegram channel message extraction."""
    scraper = TelegramScraper(api_id=12345, api_hash="mock_hash")

    mock_msg = MagicMock()
    mock_msg.id = 7788
    mock_msg.message = "Urgent: We need a React frontend developer for 2-month milestone project. Budget: $5000."
    mock_msg.text = mock_msg.message
    mock_msg.date = datetime.datetime(2026, 10, 16, 10, 30, tzinfo=datetime.timezone.utc)
    mock_msg.views = 680
    mock_msg.forwards = 5
    mock_msg.reply_to_msg_id = None
    mock_msg.media = None

    # Sender mock
    mock_sender = MagicMock()
    mock_sender.id = 554433
    mock_sender.username = "founder_mike"
    mock_sender.first_name = "Mike"
    mock_sender.last_name = "Founder"

    mock_msg.sender = mock_sender

    mock_reactions = MagicMock()
    mock_reaction_count = MagicMock()
    mock_reaction_count.count = 18
    mock_reactions.results = [mock_reaction_count]
    mock_msg.reactions = mock_reactions

    # Async generator for iter_messages
    async def mock_iter_messages(*args, **kwargs):
        yield mock_msg

    mock_client = MagicMock()
    mock_client.is_connected.return_value = True
    mock_client.is_user_authorized = AsyncMock(return_value=True)
    mock_client.iter_messages = mock_iter_messages
    mock_client.get_entity = AsyncMock(return_value=MagicMock(id=100111, username="test_channel"))

    with patch.object(scraper, "_get_client", AsyncMock(return_value=mock_client)):
        messages = []
        async for m in scraper.scrape_channel_messages("@test_channel", limit=5):
            messages.append(m)

        assert len(messages) == 1
        msg = messages[0]
        assert msg.message_id == 7788
        assert msg.sender_username == "founder_mike"
        assert msg.sender_name == "Mike Founder"
        assert msg.reactions_count == 18
        assert "Urgent: We need a React frontend developer" in msg.text
        assert msg.raw_url == "https://t.me/test_channel/7788"


@pytest.mark.asyncio
async def test_telegram_channel_not_found_handling():
    """Verify that non-existent channel raises ValueError cleanly instead of crashing."""
    from telethon.errors import UsernameNotOccupiedError

    scraper = TelegramScraper(api_id=12345, api_hash="mock_hash")
    mock_client = MagicMock()
    mock_client.get_entity = AsyncMock(side_effect=UsernameNotOccupiedError(request=None))

    with patch.object(scraper, "_get_client", AsyncMock(return_value=mock_client)):
        with pytest.raises(ValueError, match="does not exist"):
            await scraper.get_channel_info("@this_channel_definitely_does_not_exist_9999")


@pytest.mark.asyncio
async def test_platform_registry_isolation():
    """Verify PlatformAdapterRegistry cleanly provides isolated adapters without cross-pollution."""
    twitter_adapter = PlatformAdapterRegistry.get("twitter")
    telegram_adapter = PlatformAdapterRegistry.get("telegram")

    assert twitter_adapter.platform_name == "twitter"
    assert telegram_adapter.platform_name == "telegram"
    assert twitter_adapter is not telegram_adapter
    assert type(twitter_adapter) is not type(telegram_adapter)


def test_telegram_published_at_preserved_and_not_fetch_time():
    """Verify that Telegram source_published_at (<time datetime>) is preserved as created_at and never overwritten with fetch time."""
    from leadsweep.adapters import LeadRecord
    from datetime import datetime, timezone

    rec = TelegramMessageRecord(
        message_id=999,
        channel="web3jobs",
        channel_id=123,
        sender_id=456,
        sender_username="web3jobs",
        sender_name="Web3 Jobs",
        text="Rust developer wanted",
        date="2026-10-14T04:29:00+00:00",
        views=100,
        forwards=5,
        reactions_count=10,
        reply_to_msg_id=None,
        media_type=None,
    )
    lead = rec.to_lead_record()
    assert lead.published_at == "2026-10-14T04:29:00+00:00"
    tweet = lead.to_tweet_compat()
    assert tweet.created_at is not None
    assert tweet.created_at.isoformat() == "2026-10-14T04:29:00+00:00"

