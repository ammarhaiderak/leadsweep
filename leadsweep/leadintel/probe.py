# NEW FEATURE: Lead Intelligence Probe Loop & Bandit Allocator
"""
Probe, Judge, and Self-Correcting Search Loop:
1. Probe: Runs variants with tiny caps (15-25 items).
2. Judge: Scores candidates with judge_candidate (direction, topic gate, Score v2).
3. Precision: Computes lead precision per variant.
4. Multi-Armed Bandit Allocation: Prunes losers below precision floor, routes remaining volume to winners.
5. Learn from Noise: Extracts recurring noise terms from rejected posts and generates learned negatives.
"""
import re
import logging
import sqlite3
from typing import List, Dict, Any, Tuple, Optional
from collections import Counter

from leadsweep.leadintel.models import LeadBrief, QueryVariant, DirectionLabel
from leadsweep.leadintel.judge import judge_candidate

log = logging.getLogger("leadsweep.leadintel.probe")


def evaluate_probe_batch(
    variant: QueryVariant,
    items: List[Dict[str, Any]],
    brief: LeadBrief,
    conn: Optional[sqlite3.Connection] = None
) -> Tuple[int, int, float, List[str]]:
    """
    Judges scraped probe items for a variant.
    Returns: (total_items, true_buyers, precision_rate, rejected_texts)
    """
    if not items:
        return 0, 0, 0.0, []

    buyers = 0
    rejected_texts = []

    for item in items:
        text = item.get("text", "")
        author_bio = item.get("author", {}).get("description", "")
        author_followers = item.get("author", {}).get("followers_count", 0) or 0
        
        score_res = judge_candidate(
            post_text=text,
            author_bio=author_bio,
            author_followers=author_followers,
            topic_rel_score=100,
            brief=brief,
            conn=conn
        )

        if score_res.direction in (DirectionLabel.BUYER_SIGNAL, DirectionLabel.HIRING_SIGNAL) and score_res.final_score >= 70:
            buyers += 1
        else:
            rejected_texts.append(text)

    total = len(items)
    precision = round(buyers / total, 3) if total else 0.0
    
    variant.items_scraped += total
    variant.buyers_found += buyers
    variant.measured_precision = precision

    # Persist in li_variant_stats if conn available
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO li_variant_stats (
                    query_string, strategy, probe_count, buyer_count, precision_rate, updated_at
                ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(query_string) DO UPDATE SET
                    probe_count = probe_count + excluded.probe_count,
                    buyer_count = buyer_count + excluded.buyer_count,
                    precision_rate = excluded.precision_rate,
                    updated_at = CURRENT_TIMESTAMP;
            """, (variant.query_string, variant.strategy.value, total, buyers, precision))
            conn.commit()
        except Exception as e:
            log.warning(f"Could not persist variant stats: {e}")

    return total, buyers, precision, rejected_texts


def allocate_bandit_winners(
    variants: List[QueryVariant],
    min_precision_floor: float = 0.4,
    max_winners: int = 3
) -> List[QueryVariant]:
    """
    Bandit allocation:
    Prunes variants below min_precision_floor and returns top performing variants.
    """
    measured = [v for v in variants if v.measured_precision is not None]
    if not measured:
        return variants[:max_winners]

    # Sort by measured precision descending
    measured.sort(key=lambda v: v.measured_precision or 0.0, reverse=True)
    
    # Filter above floor
    winners = [v for v in measured if (v.measured_precision or 0.0) >= min_precision_floor]
    
    # If no variants beat the floor, retain the best single variant to prevent starvation
    if not winners:
        winners = measured[:1]

    return winners[:max_winners]


def extract_learned_negatives_from_noise(
    rejected_texts: List[str],
    brief: LeadBrief,
    min_occurrences: int = 2
) -> List[str]:
    """
    Extracts recurring noise terms appearing in multiple rejected posts.
    Guards against negating core topic keywords.
    """
    if not rejected_texts:
        return []

    words = []
    core_set = {t.lower() for t in (brief.icp_domains + brief.icp_roles)}
    
    noise_candidates = [
        "giveaway", "airdrop", "presale", "whitelist", "portfolio",
        "internship", "hiring intern", "entry level", "follow me", "retweet"
    ]

    for text in rejected_texts:
        t_lower = text.lower()
        for cand in noise_candidates:
            if cand in t_lower and cand not in core_set:
                words.append(cand)

    counts = Counter(words)
    learned = [term for term, count in counts.items() if count >= min_occurrences]
    return learned
