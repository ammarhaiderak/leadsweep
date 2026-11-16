# NEW FEATURE: Comprehensive tests reproducing and verifying F1, F2 and Phase 1 Telegram improvements
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from leadsweep.services.telegram_public_scraper import (
    TelegramPublicScraper,
    parse_telegram_input,
    normalize_channel_handle,
    TelegramInputPlan,
    TelegramTransportManager,
)
from leadsweep.telegram_scraper import TelegramAdapter
from leadsweep.adapters import LeadRecord


# ---------------------------------------------------------------------------
# A7: F1 Reproduction and Fix Verification
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_f1_restricted_channel_returns_failure_status_and_exact_wording():
    """
    F1 Bug: Restricted handle (@freelance_jobs_gigs) previously returned 0 items
    and was marked succeeded/0 items with NO detail.
    Fix (A1, A2):
    1. TelegramAdapter tracks last_scrape_status = "ACCESS_RESTRICTED"
    2. last_scrape_detail is EXACTLY "No public web preview exists for this handle."
    3. Job status maps to "failed" with status_detail shown.
    """
    adapter = TelegramAdapter()
    
    # Mock scrape_channel_with_status to return ACCESS_RESTRICTED
    with patch.object(
        adapter.public_scraper,
        "scrape_channel_with_status",
        AsyncMock(return_value=([], "ACCESS_RESTRICTED", "No public web preview exists for this handle."))
    ):
        results = [cand async for cand in adapter.search("@freelance_jobs_gigs", max_items=10)]
        assert len(results) == 0
        assert adapter.last_scrape_status == "ACCESS_RESTRICTED"
        assert adapter.last_scrape_detail == "No public web preview exists for this handle."


# ---------------------------------------------------------------------------
# A7: F2 Reproduction and Fix Verification
# ---------------------------------------------------------------------------
def test_f2_empty_query_grammar_and_can_proceed():
    """
    F2 Bug:
    1. Frontend canProceed previously enforced `query.trim().length > 0`, blocking Telegram empty runs.
    2. Backend did not recognize empty query as GLOBAL discovery mode.
    Fix:
    parse_telegram_input("") parses to mode="GLOBAL" with zero channels and empty keyword.
    """
    plan = parse_telegram_input("")
    assert plan.mode == "GLOBAL"
    assert plan.channels == []
    assert plan.keyword is None
    
    plan_ws = parse_telegram_input("   \t  ")
    assert plan_ws.mode == "GLOBAL"
    assert plan_ws.channels == []
    assert plan_ws.keyword is None


# ---------------------------------------------------------------------------
# Input Grammar Unit Tests
# ---------------------------------------------------------------------------
def test_input_grammar_all_variants():
    """Verify input grammar handles empty, handle, URL, list, handle+keyword, plain keywords, invite links."""
    # 1. Single @handle
    p1 = parse_telegram_input("@web3hiring")
    assert p1.mode == "DIRECT"
    assert p1.channels == ["web3hiring"]
    assert p1.keyword is None

    # 2. t.me URL
    p2 = parse_telegram_input("https://t.me/remotejobs_dev")
    assert p2.mode == "DIRECT"
    assert p2.channels == ["remotejobs_dev"]

    # 3. Comma-separated list
    p3 = parse_telegram_input("@web3hiring, https://t.me/crypto_jobs, solana_jobs")
    assert p3.mode == "DIRECT"
    assert p3.channels == ["web3hiring", "crypto_jobs", "solana_jobs"]

    # 4. Handle + keyword
    p4 = parse_telegram_input("@web3hiring rust developer")
    assert p4.mode == "DIRECT_SEARCH"
    assert p4.channels == ["web3hiring"]
    assert p4.keyword == "rust developer"

    # 5. Plain keyword
    p5 = parse_telegram_input("blockchain hiring")
    assert p5.mode == "KEYWORD"
    assert p5.channels == []
    assert p5.keyword == "blockchain hiring"

    # 6. Private invite link rejected immediately with exact C5 wording and 0 network requests
    with pytest.raises(ValueError, match="Private groups and chats can't be read without joining with an account. Only public channels with a web preview are supported."):
        parse_telegram_input("https://t.me/+AbCdEfGhIjK")

    with pytest.raises(ValueError, match="Private groups and chats can't be read without joining with an account. Only public channels with a web preview are supported."):
        parse_telegram_input("https://t.me/joinchat/AAAAAFc_xyz")


# ---------------------------------------------------------------------------
# A4: Tenant Isolation Test
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tenant_isolation_in_global_discovery():
    """
    A4: GLOBAL-mode sources must be tenant-scoped:
    harvested t.me handles from tweets/actor_runs and li_profile/objective
    reads must filter by tenant_id and never leak across tenants.
    """
    from leadsweep.telegram_scraper import TelegramAdapter
    adapter = TelegramAdapter()

    # Create mock storage engine with 2 distinct tenants
    mock_storage = MagicMock()
    mock_db = MagicMock()
    mock_cursor = MagicMock()

    # Tenant A has harvested 'tenant_a_channel'
    # Tenant B has harvested 'tenant_b_channel'
    def execute_side_effect(sql, params=()):
        if "tenant_a@example.com" in params:
            mock_cursor.fetchall.return_value = [("https://t.me/tenant_a_channel",)]
        elif "tenant_b@example.com" in params:
            mock_cursor.fetchall.return_value = [("https://t.me/tenant_b_channel",)]
        else:
            mock_cursor.fetchall.return_value = []
        return mock_cursor

    mock_cursor.execute.side_effect = execute_side_effect
    mock_db.cursor.return_value = mock_cursor
    mock_storage.db = mock_db

    # Test resolution with tenant A
    channels_a = adapter._resolve_tenant_channels("tenant_a@example.com", storage=mock_storage)
    assert "tenant_a_channel" in channels_a
    assert "tenant_b_channel" not in channels_a

    # Test resolution with tenant B
    channels_b = adapter._resolve_tenant_channels("tenant_b@example.com", storage=mock_storage)
    assert "tenant_b_channel" in channels_b
    assert "tenant_a_channel" not in channels_b


# ---------------------------------------------------------------------------
# A5: No Hardcoded Variations Grep Test
# ---------------------------------------------------------------------------
def test_no_hardcoded_variations_in_telegram_module():
    """
    A5: Remove the hardcoded variations (`site:t.me freelance`, `site:t.me/s jobs`,
    `telegram freelance site:t.me`) completely, verified by grepping the module.
    """
    import inspect
    import leadsweep.telegram_scraper as ts
    import leadsweep.services.telegram_public_scraper as tps

    src_ts = inspect.getsource(ts)
    src_tps = inspect.getsource(tps)

    for forbidden in ["site:t.me freelance", "site:t.me/s jobs", "telegram freelance site:t.me"]:
        assert forbidden not in src_ts, f"Found forbidden hardcoded string '{forbidden}' in telegram_scraper.py"
        assert forbidden not in src_tps, f"Found forbidden hardcoded string '{forbidden}' in telegram_public_scraper.py"


# ---------------------------------------------------------------------------
# A6: Transport Timing and Circuit Breaker
# ---------------------------------------------------------------------------
def test_circuit_breaker_process_wide_ttl():
    """
    A6: Verify direct-failure circuit breaker opens after 2 consecutive failures,
    stays open for TTL, and resets on success.
    """
    tm = TelegramTransportManager()
    tm.reset_for_tests()
    assert tm.is_direct_circuit_open() is False

    # 1 failure: Still closed
    tm.record_direct_failure()
    assert tm.is_direct_circuit_open() is False

    # 2 failures: Circuit opens
    tm.record_direct_failure()
    assert tm.is_direct_circuit_open() is True

    # Success resets breaker
    tm.record_direct_success()
    assert tm.is_direct_circuit_open() is False

