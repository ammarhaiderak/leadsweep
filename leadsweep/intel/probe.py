# NEW FEATURE: Query Intelligence Probe-and-Learn Loop
"""
Executes small probe batches for query variants, computes precision@10,
and prunes underperforming variants while allocating volume to winning variants.
"""
import logging
from typing import List, Dict, Any, Tuple
from leadsweep.intel.models import LeadBrief, QueryVariant, DirectionLabel
from leadsweep.intel.direction import classify_lead_direction

logger = logging.getLogger("leadsweep.intel.probe")


def simulate_or_score_probe_items(items: List[Dict[str, Any]], brief: LeadBrief) -> Tuple[int, int, float]:
    """
    Evaluates items scraped in a probe run against the lead direction classifier.
    Returns: (total_items, buyer_signals_found, precision)
    """
    if not items:
        return 0, 0, 0.0

    buyer_count = 0
    for item in items:
        text = item.get("text", "")
        author_bio = item.get("author", {}).get("description", "")
        res = classify_lead_direction(text, author_bio=author_bio, brief=brief)
        # Check if buyer signal or hiring signal
        if res.direction in (DirectionLabel.BUYER_SIGNAL, DirectionLabel.HIRING_SIGNAL):
            buyer_count += 1

    precision = buyer_count / len(items)
    return len(items), buyer_count, round(precision, 3)


def select_winning_variants(
    variants: List[QueryVariant],
    min_precision_threshold: float = 0.4,
    max_winners: int = 3
) -> List[QueryVariant]:
    """
    Bandit selection: prunes variants below precision floor and orders by performance.
    """
    # Sort variants by measured precision descending
    scored = [v for v in variants if v.measured_precision is not None]
    if not scored:
        # If unmeasured, return top N diverse variants
        return variants[:max_winners]

    scored.sort(key=lambda x: x.measured_precision or 0.0, reverse=True)
    
    # Filter by threshold
    winners = [v for v in scored if (v.measured_precision or 0.0) >= min_precision_threshold]
    
    # If no variants beat threshold, return the best single variant to prevent total starvation
    if not winners:
        winners = scored[:1]

    return winners[:max_winners]
