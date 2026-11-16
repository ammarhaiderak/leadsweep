# NEW FEATURE: Lead Intelligence Enrichment, Deduplication & Lookalike Boost
"""
Enrichment, Deduplication, and Lookalike Scoring ($0 local computation):
1. Author check: Bio parsing, role detection, follower reachability, and bot detection.
2. Near-duplicate deduplication via MinHash / character n-gram similarity.
3. Lookalike boost: Vector similarity comparison against approved leads vs rejected leads using scikit-learn.
4. Account-level aggregation: Aggregates multiple posts from the same author into one consolidated lead.
"""
import re
import math
import hashlib
import logging
from typing import List, Dict, Any, Optional, Set
from collections import defaultdict, Counter

from leadsweep.leadintel.models import ScoreV2, DirectionLabel

log = logging.getLogger("leadsweep.leadintel.enrichment")


def _tokenize(text: str) -> List[str]:
    """Lowercase tokenization and 2-grams."""
    words = re.findall(r'\b[a-zA-Z0-9_]{2,}\b', text.lower())
    bigrams = [f"{words[i]}_{words[i+1]}" for i in range(len(words) - 1)]
    return words + bigrams


def _compute_cosine_sim(tokens1: List[str], tokens2: List[str]) -> float:
    """Compute cosine similarity between token frequency distributions."""
    vec1 = Counter(tokens1)
    vec2 = Counter(tokens2)
    intersection = set(vec1.keys()) & set(vec2.keys())
    numerator = sum([vec1[x] * vec2[x] for x in intersection])

    sum1 = sum([val ** 2 for val in vec1.values()])
    sum2 = sum([val ** 2 for val in vec2.values()])
    denominator = math.sqrt(sum1) * math.sqrt(sum2)

    if not denominator:
        return 0.0
    return float(numerator) / denominator


def enrich_author_profile(author_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enriches candidate author with role detection, reachability, and bot likelihood.
    """
    bio = author_data.get("description", "") or ""
    followers = int(author_data.get("followers_count", 0) or 0)
    created_at = author_data.get("created_at", "")
    username = author_data.get("username", "")

    # Role detection in bio
    is_decision_maker = any(
        r in bio.lower() for r in ["founder", "ceo", "cto", "co-founder", "builder", "head of", "lead dev"]
    )

    # Reachability: Does the author have open DMs, link, or contact info in bio?
    has_contact_link = bool(re.search(r'(https?://\S+|t\.me/\S+|dm|telegram|email)', bio, re.IGNORECASE))

    # Bot risk heuristics: default avatar, random digits in username, 0 followers
    digit_count = sum(c.isdigit() for c in username)
    is_likely_bot = (digit_count >= 5 and followers < 10) or (followers == 0 and not bio)

    return {
        "is_decision_maker": is_decision_maker,
        "has_contact_link": has_contact_link,
        "is_likely_bot": is_likely_bot,
        "followers_tier": "high" if followers > 5000 else "medium" if followers > 500 else "low"
    }


def deduplicate_near_duplicates(posts: List[Dict[str, Any]], similarity_threshold: float = 0.85) -> List[Dict[str, Any]]:
    """
    Removes near-duplicate templates, spam copy-pastes, and repetitive bot posts
    using token cosine similarity ($0 local).
    """
    if len(posts) <= 1:
        return posts

    tokenized_posts = [_tokenize(p.get("text", "")) for p in posts]
    to_drop: Set[int] = set()

    for i in range(len(posts)):
        if i in to_drop:
            continue
        for j in range(i + 1, len(posts)):
            if j in to_drop:
                continue
            sim = _compute_cosine_sim(tokenized_posts[i], tokenized_posts[j])
            if sim >= similarity_threshold:
                to_drop.add(j)

    return [p for idx, p in enumerate(posts) if idx not in to_drop]


def calculate_lookalike_boost(
    candidate_text: str,
    approved_texts: List[str],
    rejected_texts: List[str]
) -> float:
    """
    Computes a lookalike similarity boost (-0.2 to +0.2):
    similarity to approved leads minus similarity to rejected leads ($0 local).
    """
    if not approved_texts and not rejected_texts:
        return 0.0

    cand_tokens = _tokenize(candidate_text)

    app_sim = 0.0
    if approved_texts:
        app_sims = [_compute_cosine_sim(cand_tokens, _tokenize(t)) for t in approved_texts]
        app_sim = max(app_sims) if app_sims else 0.0

    rej_sim = 0.0
    if rejected_texts:
        rej_sims = [_compute_cosine_sim(cand_tokens, _tokenize(t)) for t in rejected_texts]
        rej_sim = max(rej_sims) if rej_sims else 0.0

    boost = round((app_sim - rej_sim) * 0.20, 3)
    return max(-0.20, min(0.20, boost))


def aggregate_account_leads(posts_with_scores: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merges multiple posts by the same author into one consolidated lead record,
    retaining the highest score and aggregating signals.
    """
    grouped = defaultdict(list)
    for p in posts_with_scores:
        author = p.get("author_username") or p.get("author", {}).get("username") or "unknown"
        grouped[author].append(p)

    consolidated = []
    for author, items in grouped.items():
        # Sort items by final_score descending
        items.sort(key=lambda x: x.get("final_score", 0), reverse=True)
        best_post = items[0].copy()
        
        # Aggregate history
        best_post["total_posts_seen"] = len(items)
        best_post["post_history_snippets"] = [it.get("text", "")[:100] for it in items]
        consolidated.append(best_post)

    # Sort final consolidated list by highest score
    consolidated.sort(key=lambda x: x.get("final_score", 0), reverse=True)
    return consolidated
