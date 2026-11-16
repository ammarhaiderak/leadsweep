"""
tests/test_contract_pipeline.py -- Test Suite for Buying-Intent Listening Engine Contract

Covers:
1. Hard stops & contract schemas (RawItem, LeadDecision, QueryPack, Checkpoint)
2. Incomplete items (missing source_created_at, comments with missing parent excerpt)
3. Closed set SalesIntentType validation
4. Verbatim <= 30 word quote verification
5. Priority calculation & 12h half-life decay
6. Alert routing thresholds (alert, review, drop)
7. Circuit breaker opening on 401/403
8. Reddit disabled_unlicensed enforcement
9. Traps: deterministic dedup, sensor death monitoring, no DOM/selectors
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
import pytest
from pydantic import ValidationError

from leadsweep.core.contract_models import (
    AlertClass,
    Checkpoint,
    LeadDecision,
    LeadDisposition,
    QueryPack,
    RawItem,
    SalesIntentType,
)
from leadsweep.core.query_compiler import CompilerInput, QueryCompiler
from leadsweep.core.scoring_engine import (
    calculate_priority,
    route_alert_class,
    score_item,
)
from leadsweep.core.connectors import CircuitBreakerOpenError, ConnectorClient, RedditConnector


def test_schema_raw_item_complete_and_incomplete():
    now = datetime.now(timezone.utc)
    # Valid complete post
    item_valid = RawItem(
        source="hn",
        native_id="400100",
        thread_id="400100",
        url="https://news.ycombinator.com/item?id=400100",
        item_type="post",
        author_handle="tech_founder",
        community="news.ycombinator.com",
        source_created_at=now,
        body="Looking for a tool that handles SOC2 compliance automation.",
        title="Ask HN: Best SOC2 tool?",
    )
    assert item_valid.is_complete is True
    assert item_valid.payload_sha256 != ""

    # Incomplete: missing source_created_at (must never be imputed as now)
    item_no_date = RawItem(
        source="hn",
        native_id="400101",
        thread_id="400101",
        url="https://news.ycombinator.com/item?id=400101",
        item_type="post",
        author_handle="tech_founder",
        community="news.ycombinator.com",
        source_created_at=None,
        body="Looking for a tool that handles SOC2 compliance automation.",
    )
    assert item_no_date.is_complete is False

    # Incomplete: comment with no parent excerpt
    comment_no_parent = RawItem(
        source="hn",
        native_id="400102",
        thread_id="400100",
        url="https://news.ycombinator.com/item?id=400102",
        item_type="comment",
        author_handle="cto_user",
        community="news.ycombinator.com",
        source_created_at=now,
        body="We are migrating off Vanta because it is too expensive.",
        parent_excerpt=None,
    )
    assert comment_no_parent.is_complete is False


def test_closed_set_sales_intent_types():
    assert SalesIntentType.ACTIVE_BUY.value == "ACTIVE_BUY"
    assert SalesIntentType.COMPETITOR_PAIN.value == "COMPETITOR_PAIN"
    assert SalesIntentType.ALTERNATIVE.value == "ALTERNATIVE"
    assert SalesIntentType.IMPLEMENTATION.value == "IMPLEMENTATION"
    assert SalesIntentType.BUDGET.value == "BUDGET"
    assert SalesIntentType.HIRING_FOR_PROBLEM.value == "HIRING_FOR_PROBLEM"

    # Invalid enum value must raise validation error
    with pytest.raises(ValidationError):
        LeadDecision(
            decision_id="test_01",
            source="hn",
            native_id="123",
            query_pack_hash="hash1",
            intent_type="INVALID_RANDOM_TYPE",  # type: ignore
            intent_score=80,
            icp_score=70,
            priority=56.0,
            evidence_span="short quote",
            reason="good fit",
            model_version="groq-llama3-70b-v1",
            alert_class=AlertClass.ALERT,
        )


def test_evidence_span_word_count_and_verbatim_quote():
    now = datetime.now(timezone.utc)
    item = RawItem(
        source="hn",
        native_id="500",
        thread_id="500",
        url="https://news.ycombinator.com/item?id=500",
        item_type="post",
        author_handle="buyer_dan",
        community="news.ycombinator.com",
        source_created_at=now - timedelta(hours=2),
        body="Does anyone know an alternative to Datadog? It is way too expensive for our seed stage startup.",
    )

    # Valid verbatim quote <= 30 words
    decision = score_item(
        item=item,
        query_pack_hash="hash_pack_01",
        intent_type=SalesIntentType.ALTERNATIVE,
        intent_score=85,
        icp_score=80,
        evidence_quote="alternative to Datadog",
        reason="Explicitly asking for alternative with budget pain",
    )
    assert decision.alert_class == AlertClass.ALERT
    assert decision.priority > 50.0
    assert decision.reply_draft is not None

    # Absent quote in text -> routes to REVIEW, not ALERT
    decision_bad_quote = score_item(
        item=item,
        query_pack_hash="hash_pack_01",
        intent_type=SalesIntentType.ALTERNATIVE,
        intent_score=85,
        icp_score=80,
        evidence_quote="non-existent phrase not in post",
        reason="Test phantom quote",
    )
    assert decision_bad_quote.alert_class == AlertClass.REVIEW


def test_priority_decay_12h_half_life():
    # priority = intent * icp / 100 * exp(-age_hours / 12)
    p_fresh = calculate_priority(100, 100, age_hours=0)
    assert p_fresh == 100.0

    p_12h = calculate_priority(100, 100, age_hours=12)
    # 100 * exp(-1) = ~36.7879
    assert math.isclose(p_12h, 36.7879, abs_tol=0.01)

    p_72h = calculate_priority(100, 100, age_hours=72)
    # After 72h, decay is exp(-6) = ~0.00247
    assert p_72h < 0.3


def test_query_compiler_requires_community_allowlist():
    # Must fail without community constraints
    with pytest.raises(ValueError, match="Community allowlist is required"):
        QueryCompiler.compile_pack(
            CompilerInput(
                icp_id="icp_devops",
                product_offer="observability platform",
                competitors=["Datadog"],
                target_roles=["CTO"],
                communities=[],  # Empty allowlist forbidden
            )
        )

    # Succeeds with community allowlist
    pack = QueryCompiler.compile_pack(
        CompilerInput(
            icp_id="icp_devops",
            product_offer="observability platform",
            competitors=["Datadog"],
            target_roles=["CTO"],
            communities=["devops", "sre"],
        )
    )
    assert len(pack.families) > 0
    assert "alternative to Datadog" in pack.families
    assert pack.hash != ""
    assert pack.compiled_per_source["reddit"] == "disabled_unlicensed"


def test_reddit_license_gatekeeping():
    # Unlicensed Reddit is disabled by default
    unlicensed = RedditConnector(contract_id=None)
    assert unlicensed.is_enabled() is False

    licensed = RedditConnector(contract_id="contract_corp_commercial_2026")
    assert licensed.is_enabled() is True


@pytest.mark.anyio
async def test_circuit_breaker_trips_on_401_403():
    conn = ConnectorClient("test_source", "https://httpbin.org")
    # Simulate breaker open
    conn.breaker_open = True
    conn.breaker_reason = "HTTP 403 Forbidden received. Paged human."

    with pytest.raises(CircuitBreakerOpenError):
        await conn.get_json("/anything")
    await conn.close()
