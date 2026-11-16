"""
leadsweep/core/scoring_engine.py -- Pinned Scoring Engine

Calculates:
- intent_score (0..100) from text only
- icp_score (0..100) from role, community, geo hints
- priority = (intent_score * icp_score / 100) * exp(-age_hours / 12)
- evidence_span verification: must be <= 30 words and verbatim inside post text
- alert | review | drop threshold routing
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Optional

from .contract_models import (
    AlertClass,
    LeadDecision,
    LeadDisposition,
    PAGING_INTENT_TYPES,
    RawItem,
    SalesIntentType,
)

PINNED_MODEL_VERSION = "groq-llama3-70b-v1"


def calculate_priority(intent_score: int, icp_score: int, age_hours: float) -> float:
    """Calculates contract priority with 12h half-life:
    priority = (intent_score * icp_score / 100) * exp(-age_hours / 12)
    """
    base = (intent_score * icp_score) / 100.0
    decay = math.exp(-max(0.0, age_hours) / 12.0)
    return round(base * decay, 4)


def route_alert_class(
    intent_score: int,
    icp_score: int,
    age_hours: float,
    intent_type: SalesIntentType,
    has_valid_quote: bool,
) -> AlertClass:
    """Contract routing defaults:
    - If no quote -> review, not alert
    - alert if intent >= 70 and icp >= 50 and age <= 72h and type is a sales type
    - review if intent >= 40, or (sales type and icp >= 70)
    - else drop
    """
    is_sales_type = intent_type in PAGING_INTENT_TYPES

    if not has_valid_quote:
        # No quote or quote absent in text -> review, not alert
        return AlertClass.REVIEW if (intent_score >= 40 or icp_score >= 50) else AlertClass.DROP

    if intent_score >= 70 and icp_score >= 50 and age_hours <= 72.0 and is_sales_type:
        return AlertClass.ALERT

    if intent_score >= 40 or (is_sales_type and icp_score >= 70):
        return AlertClass.REVIEW

    return AlertClass.DROP


def score_item(
    item: RawItem,
    query_pack_hash: str,
    intent_type: SalesIntentType,
    intent_score: int,
    icp_score: int,
    evidence_quote: str,
    reason: str,
    model_version: str = PINNED_MODEL_VERSION,
) -> LeadDecision:
    """Evaluates raw item into LeadDecision adhering strictly to contract thresholds."""
    now = datetime.now(timezone.utc)
    
    # Calculate age hours
    if item.source_created_at:
        dt = item.source_created_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (now - dt).total_seconds() / 3600.0)
    else:
        age_hours = 999.0  # Incomplete items have high age

    # Clean and verify quote presence
    quote_clean = evidence_quote.strip()
    words = quote_clean.split()
    if len(words) > 30:
        quote_clean = " ".join(words[:30])

    # Check verbatim presence in post body or title
    full_text = f"{item.title or ''} {item.body}".lower()
    has_valid_quote = bool(quote_clean and quote_clean.lower() in full_text)

    # Compute priority
    priority = calculate_priority(intent_score, icp_score, age_hours)

    # Determine alert class
    alert_class = route_alert_class(intent_score, icp_score, age_hours, intent_type, has_valid_quote)

    # Deterministic decision ID
    decision_id = f"dec_{item.source}_{item.native_id}_{model_version[:8]}"

    # Reply draft (alert only, not_sent, human-send only)
    reply_draft = None
    if alert_class == AlertClass.ALERT:
        reply_draft = f"Hi @{item.author_handle}, saw you're looking for solutions regarding '{quote_clean[:40]}'. Happy to share how we tackle this."

    return LeadDecision(
        decision_id=decision_id,
        source=item.source,
        native_id=item.native_id,
        query_pack_hash=query_pack_hash,
        intent_type=intent_type,
        intent_score=intent_score,
        icp_score=icp_score,
        priority=priority,
        evidence_span=quote_clean,
        reason=reason,
        model_version=model_version,
        alert_class=alert_class,
        decided_at=now,
        disposition=LeadDisposition.NEW,
        reply_draft=reply_draft,
    )
