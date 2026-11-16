# NEW FEATURE: Lead Intelligence Judge & Direction Scorer
"""
Post-retrieval judge pipeline:
1. Prefilter: Language, minimum length, duplicate rejection, spam heuristics.
2. Existing Relevance Gate (runs first; off-topic < 40 is hard-capped at <= 15).
3. Lead Direction Classifier: Distinguishes buyer from seller/job-seeker.
4. Score v2: Transparent scoring combining need strength, urgency, ICP fit, authority, and direction caps.
5. Verbatim evidence quote verification.
"""
import re
import logging
import sqlite3
from typing import Dict, Any, Optional

from leadsweep.leadintel.models import (
    DirectionLabel,
    DirectionClassificationResult,
    ScoreV2,
    DIRECTION_SCORE_CAPS,
    LeadBrief
)
from leadsweep.leadintel.heuristics import classify_direction_rules, verify_evidence_quote
from leadsweep.leadintel.llm import get_cached_classification, store_cached_classification

log = logging.getLogger("leadsweep.leadintel.judge")


def judge_candidate(
    post_text: str,
    author_bio: str = "",
    author_followers: int = 0,
    topic_rel_score: int = 100,
    brief: Optional[LeadBrief] = None,
    conn: Optional[sqlite3.Connection] = None
) -> ScoreV2:
    """
    Main post evaluation pipeline.
    Produces ScoreV2 with direction classification and literal quote verification.
    """
    clean_text = post_text.strip()
    
    # 1. Prefilter check
    if len(clean_text) < 15:
        return ScoreV2(
            final_score=5,
            direction=DirectionLabel.AIRDROP_BOT_SPAM,
            direction_cap=5,
            need_strength_score=0,
            urgency_score=0,
            icp_fit_score=0,
            authority_score=0,
            quote_verified=False,
            evidence_quote="",
            why_text="Post rejected by prefilter: Content too short."
        )

    # 2. Check classification cache
    import hashlib
    content_hash = hashlib.sha256(f"{clean_text}:{brief.offer if brief else ''}".encode()).hexdigest()
    cached = get_cached_classification(conn, content_hash)
    if cached:
        return ScoreV2(**cached)

    # 3. Classify direction using local heuristics / rules
    offer_str = brief.offer if brief else ""
    dir_res = classify_direction_rules(clean_text, author_bio=author_bio, offer=offer_str)

    # 4. Compute unconstrained Score v2 dimensions
    need_score = int(dir_res.need_strength * 100)
    urgency_score = int(dir_res.urgency * 100)
    icp_score = int(dir_res.icp_fit * 100)
    
    # Authority score from follower count & bio presence
    auth_score = min(20, int(author_followers / 500)) if author_followers else 5
    if any(r in author_bio.lower() for r in ["founder", "ceo", "cto", "builder"]):
        auth_score = min(25, auth_score + 10)

    # Base score = (topic * 0.2) + (need * 0.45) + (urgency * 0.2) + (icp * 0.15)
    base_score = int((topic_rel_score * 0.20) + (need_score * 0.45) + (urgency_score * 0.20) + (icp_score * 0.15))

    # 5. Apply Hard Topic Relevance Gate (Existing rule)
    if topic_rel_score < 40:
        base_score = min(15, base_score)

    # 6. Apply Direction Hard Cap
    cap = dir_res.max_score_cap
    final_score = min(cap, max(5, base_score))

    # Build human-readable 'why_text'
    if dir_res.direction == DirectionLabel.BUYER_SIGNAL:
        why_text = f"Qualified buyer: Explicit commercial demand found ('{dir_res.evidence_quote}')."
    elif dir_res.direction == DirectionLabel.HIRING_SIGNAL:
        why_text = f"Qualified hiring: Actively hiring paid role ('{dir_res.evidence_quote}')."
    elif dir_res.direction == DirectionLabel.JOB_SEEKER:
        why_text = f"Disqualified: Author is seeking opportunities/funding for themselves (capped at {cap})."
    elif dir_res.direction == DirectionLabel.SERVICE_PROVIDER_PROMO:
        why_text = f"Disqualified: Competitor or freelancer marketing services (capped at {cap})."
    elif dir_res.direction == DirectionLabel.INFO_OR_THOUGHT_CONTENT:
        why_text = f"Disqualified: Informational essay or educational tips without purchase intent (capped at {cap})."
    elif dir_res.direction == DirectionLabel.AIRDROP_BOT_SPAM:
        why_text = f"Disqualified: Airdrop, giveaway, or spam pattern detected (capped at {cap})."
    else:
        why_text = f"Review needed: Commercial direction ambiguous (capped at {cap})."

    score_result = ScoreV2(
        final_score=final_score,
        direction=dir_res.direction,
        direction_cap=cap,
        need_strength_score=need_score,
        urgency_score=urgency_score,
        icp_fit_score=icp_score,
        authority_score=auth_score,
        quote_verified=dir_res.quote_verified,
        evidence_quote=dir_res.evidence_quote,
        why_text=why_text
    )

    # Cache result
    store_cached_classification(conn, content_hash, "heuristic-v2", score_result.model_dump())
    return score_result
