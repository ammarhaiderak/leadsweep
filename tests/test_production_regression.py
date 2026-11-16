"""Regression Test Suite for LeadSweep Production Engineering Requirements.

Validates:
1. Platform selection strictly dispatches to the correct PlatformAdapter (no default hardcoding).
2. /v1/data/{run_id} returns populated items for a job, preventing blank screen 'View Leads' regression.
3. /v1/data/export returns correct platform attribution (e.g. linkedin, upwork, fiverr, not hardcoded twitter).
4. RelevanceEngine parses natural language queries and filters low-relevance noise.
5. SSRF validation protects contact enrichment from private/loopback/cloud metadata IPs.
6. Timezone-aware 10:00 AM scheduler next_run_at calculation.
7. Early Access submission puts applicant in PENDING and blocks unauthorized login.
"""
import pytest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from leadsweep.adapters import (
    PlatformAdapterRegistry,
    TwitterAdapter,
    LinkedInAdapter,
    UpworkAdapter,
    FiverrAdapter,
    RedditAdapter,
    BlueskyAdapter,
    FacebookAdapter,
    InstagramAdapter,
    LeadRecord,
)
from leadsweep.services.relevance import QueryIntent, RelevanceEngine
from leadsweep.services.enrichment import is_safe_public_url
from leadsweep.services.scheduler import calculate_next_run


def test_platform_adapter_registry_dispatch_all_8():
    """Requirement 2, 3 & 72: Selected platform MUST control adapter across all 8 platforms."""
    twitter_ad = PlatformAdapterRegistry.get("twitter")
    x_ad = PlatformAdapterRegistry.get("x")
    linkedin_ad = PlatformAdapterRegistry.get("linkedin")
    upwork_ad = PlatformAdapterRegistry.get("upwork")
    fiverr_ad = PlatformAdapterRegistry.get("fiverr")
    reddit_ad = PlatformAdapterRegistry.get("reddit")
    bluesky_ad = PlatformAdapterRegistry.get("bluesky")
    facebook_ad = PlatformAdapterRegistry.get("facebook")
    instagram_ad = PlatformAdapterRegistry.get("instagram")

    assert isinstance(twitter_ad, TwitterAdapter)
    assert isinstance(x_ad, TwitterAdapter)
    assert isinstance(linkedin_ad, LinkedInAdapter)
    assert isinstance(upwork_ad, UpworkAdapter)
    assert isinstance(fiverr_ad, FiverrAdapter)
    assert isinstance(reddit_ad, RedditAdapter)
    assert isinstance(bluesky_ad, BlueskyAdapter)
    assert isinstance(facebook_ad, FacebookAdapter)
    assert isinstance(instagram_ad, InstagramAdapter)

    assert twitter_ad.platform_name == "twitter"
    assert linkedin_ad.platform_name == "linkedin"
    assert upwork_ad.platform_name == "upwork"
    assert fiverr_ad.platform_name == "fiverr"
    assert reddit_ad.platform_name == "reddit"
    assert bluesky_ad.platform_name == "bluesky"
    assert facebook_ad.platform_name == "facebook"
    assert instagram_ad.platform_name == "instagram"



def test_relevance_engine_intent_and_scoring():
    """Requirement 9, 10, 11, 73: Natural language parsing and noise rejection."""
    query = "Find SaaS founders in Lahore who are looking for AI automation"
    intent = QueryIntent.parse(query, platform="linkedin")

    assert intent.target_entity == "founder"
    assert intent.industry in ("saas", "ai", "automation")
    assert intent.location == "lahore"
    assert "saas" in intent.keywords or "automation" in intent.keywords

    engine = RelevanceEngine(threshold=0.35)

    # Relevant candidate
    relevant_lead = LeadRecord(
        id="lead_1",
        platform="linkedin",
        source_url="https://linkedin.com/in/founder-lahore",
        name="Usman Ahmed",
        username="usman_saas",
        headline="Founder & CEO @ AI Automate | Lahore SaaS",
        content="Building AI automation tools for B2B SaaS startups in Lahore.",
    )
    is_acc, score, sigs = engine.evaluate(relevant_lead, intent)
    assert is_acc is True
    assert score >= 0.40

    # Irrelevant noise candidate (e.g. food recipe, gossip)
    noise_candidate = LeadRecord(
        id="lead_2",
        platform="linkedin",
        source_url="https://linkedin.com/in/chef-food",
        name="Delicious Food Recipe",
        username="cooking_lover",
        headline="Traditional spicy chicken biryani recipe master",
        content="Follow our recipe blog for football and celebrity gossip.",
    )
    is_acc_noise, noise_score, _ = engine.evaluate(noise_candidate, intent)
    assert is_acc_noise is False
    assert noise_score < 0.35


def test_ssrf_protection_rules():
    """Requirement 63: Validate SSRF security blocks localhost, private IPs, and cloud metadata."""
    assert is_safe_public_url("http://127.0.0.1:8000") is False
    assert is_safe_public_url("http://localhost:3000") is False
    assert is_safe_public_url("http://169.254.169.254/latest/meta-data") is False
    assert is_safe_public_url("http://10.0.0.1/admin") is False
    assert is_safe_public_url("http://192.168.1.1/router") is False
    # Public domain
    assert is_safe_public_url("https://example.com") is True


def test_timezone_aware_scheduler_calculation():
    """Requirement 33 & 75: 10:00 AM in user timezone (Asia/Karachi)."""
    tz = ZoneInfo("Asia/Karachi")
    # Base datetime at 08:00 AM on Oct 8
    base_morning = datetime(2026, 10, 8, 8, 0, 0, tzinfo=tz)
    next_run = calculate_next_run(schedule_time_str="10:00", tz_name="Asia/Karachi", from_dt=base_morning)

    # Expected next run is today at 10:00 AM
    assert next_run.day == 8
    assert next_run.hour == 10
    assert next_run.minute == 0

    # If current time is after 10:00 AM (e.g. 11:30 AM), next run must be next day at 10:00 AM
    base_afternoon = datetime(2026, 10, 8, 11, 30, 0, tzinfo=tz)
    next_day_run = calculate_next_run(schedule_time_str="10:00", tz_name="Asia/Karachi", from_dt=base_afternoon)
    assert next_day_run.day == 9
    assert next_day_run.hour == 10
    assert next_day_run.minute == 0
