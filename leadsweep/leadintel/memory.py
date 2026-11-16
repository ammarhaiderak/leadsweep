"""
Lead Intelligence Engine - User Feedback Memory & Lookalike Generation.
Maintains li_feedback, computes calibrated weights in li_models, and produces lookalike query variants.
Zero external dependencies ($0 cost).
"""

from __future__ import annotations

import json
import uuid
import math
from typing import Any, Dict, List, Optional
from leadsweep.leadintel.db import get_connection
from leadsweep.leadintel.models import QueryVariant, StrategyType


def record_lead_feedback(
    post_id: str,
    author_username: str,
    action: str,  # "approved", "rejected", "contacted"
    rejection_reason: Optional[str] = None,
    post_text: str = "",
    author_bio: str = "",
    score_at_action: Optional[float] = None,
    brief_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Records user approval or rejection into li_feedback using features_json."""
    features = {
        "author_username": author_username,
        "post_text": post_text,
        "author_bio": author_bio,
        "rejection_reason": rejection_reason,
        "score_at_action": score_at_action,
        "brief_id": brief_id,
        "extra": metadata or {},
    }
    fb_id = str(uuid.uuid4())
    direction = "BUYER_SIGNAL" if action == "approved" else "REJECTED"

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO li_feedback (id, tweet_id, label, direction, features_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (fb_id, post_id, action, direction, json.dumps(features)),
        )


def get_feedback_history(limit: int = 100) -> List[Dict[str, Any]]:
    """Returns recent feedback items with unpacked features."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, tweet_id, label, direction, features_json, created_at
            FROM li_feedback
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()

    history = []
    for r in rows:
        features = {}
        try:
            features = json.loads(r[4]) if r[4] else {}
        except Exception:
            pass

        history.append({
            "id": r[0],
            "post_id": r[1],
            "action": r[2],
            "direction": r[3],
            "author_username": features.get("author_username", ""),
            "post_text": features.get("post_text", ""),
            "author_bio": features.get("author_bio", ""),
            "rejection_reason": features.get("rejection_reason"),
            "score_at_action": features.get("score_at_action"),
            "created_at": r[5],
        })

    return history


def update_calibrated_weights() -> Dict[str, float]:
    """
    Computes lightweight calibration adjustments from approval/rejection rates.
    Persists updated model weights in li_models. Zero external ML libraries needed.
    """
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT label FROM li_feedback"
        )
        rows = cursor.fetchall()

    approved_count = sum(1 for r in rows if r[0] == "approved")
    rejected_count = sum(1 for r in rows if r[0] == "rejected")
    total = approved_count + rejected_count

    # Default weights
    weights = {
        "topic_weight": 0.40,
        "direction_weight": 0.45,
        "enrichment_weight": 0.15,
        "rejection_penalty_multiplier": 1.0,
    }

    if total >= 5:
        approval_rate = approved_count / total
        # If user rejects heavily (> 60%), increase direction penalty weight
        if approval_rate < 0.4:
            weights["direction_weight"] = 0.55
            weights["topic_weight"] = 0.35
            weights["enrichment_weight"] = 0.10
            weights["rejection_penalty_multiplier"] = 1.3
        elif approval_rate > 0.7:
            weights["direction_weight"] = 0.40
            weights["topic_weight"] = 0.40
            weights["enrichment_weight"] = 0.20
            weights["rejection_penalty_multiplier"] = 0.8

    version = f"v1.{total}"
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO li_models (version, weights_json, samples_count)
            VALUES (?, ?, ?)
            """,
            (
                version,
                json.dumps(weights),
                total
            ),
        )

    return weights


def generate_lookalike_queries(brief_core_terms: List[str], max_variants: int = 3) -> List[QueryVariant]:
    """
    Generates new search variants anchored on terms and bios of approved leads.
    """
    history = get_feedback_history(limit=25)
    approved = [h for h in history if h.get("action") == "approved"]

    if not approved:
        return []

    # Extract high-frequency non-stopword tokens from approved bios & posts
    stopwords = {
        "the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "of", "with",
        "is", "are", "am", "i", "we", "my", "our", "you", "your", "it", "this", "that",
        "looking", "need", "hiring", "build", "building", "co", "https", "http"
    }

    tokens: Dict[str, int] = {}
    for h in approved:
        combined = f"{h.get('post_text', '')} {h.get('author_bio', '')}".lower()
        import re
        words = re.findall(r"\b[a-z]{4,15}\b", combined)
        for w in words:
            if w not in stopwords:
                tokens[w] = tokens.get(w, 0) + 1

    sorted_tokens = sorted(tokens.items(), key=lambda x: x[1], reverse=True)
    top_tokens = [w for w, _ in sorted_tokens[:6]]

    variants: List[QueryVariant] = []
    base_anchor = brief_core_terms[0] if brief_core_terms else "web3"

    for i in range(min(max_variants, max(1, len(top_tokens) // 2))):
        if not top_tokens:
            break
        kw1 = top_tokens[i * 2] if (i * 2) < len(top_tokens) else "auditor"
        kw2 = top_tokens[i * 2 + 1] if (i * 2 + 1) < len(top_tokens) else ""
        text = f'"{base_anchor}" "{kw1}"' if not kw2 else f'"{base_anchor}" ("{kw1}" OR "{kw2}") "looking for"'
        text += " -filter:retweets -filter:replies lang:en"
        variants.append(
            QueryVariant(
                strategy=StrategyType.S7_LOOKALIKE,
                query_string=text,
                rationale=f"Lookalike discovery based on approved lead vocabulary ({kw1})",
                expected_precision=0.75,
            )
        )

    return variants
