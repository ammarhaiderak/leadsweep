# NEW FEATURE: Query Variant Generator
"""
Generates 6-12 diverse, strategic X search query variants based on a LeadBrief.
Strategies:
1. need_signal: Topic keywords combined with explicit purchasing/hiring action phrases.
2. icp_bio: Target buyer roles combined with pain/problem phrases.
3. pain_point: Natural expressions of struggle, seeking recommendations, or vendor replacement.
"""
import re
from typing import List
from leadsweep.intel.models import LeadBrief, QueryVariant, QueryVariantStrategy


def format_exclusion_operators(exclusions: List[str]) -> str:
    """Format negative terms into Twitter search syntax: -term or -\"multi word\"."""
    ops = []
    # Pick top high-leverage negatives to avoid query length explosion
    priority_negatives = [
        "open to work",
        "looking for work",
        "hire me",
        "my portfolio",
        "available for hire",
        "airdrop",
        "giveaway"
    ]
    all_negs = set(exclusions)
    chosen = []
    for p in priority_negatives:
        if p in all_negs:
            chosen.append(p)
    # Add any extra learned negatives up to 8 max
    for e in exclusions:
        if e not in chosen and len(chosen) < 8:
            chosen.append(e)

    for term in chosen:
        cleaned = term.strip().replace('"', '')
        if " " in cleaned:
            ops.append(f'-"{cleaned}"')
        else:
            ops.append(f'-{cleaned}')
    return " ".join(ops)


def generate_query_variants(brief: LeadBrief, max_variants: int = 8) -> List[QueryVariant]:
    """
    Produce diverse search variants adhering strictly to Twitter advanced search operators:
    -filter:retweets -filter:replies lang:en
    """
    base_term = brief.raw_query.strip().replace('"', '')
    neg_ops = format_exclusion_operators(brief.exclusions)
    base_filters = "-filter:retweets -filter:replies lang:en"

    variants: List[QueryVariant] = []

    # STRATEGY 1: Need-Signal Queries (Topic + Buying Intent)
    need_patterns = [
        ('"looking for" ("developer" OR "dev" OR "agency" OR "builder")', "Direct hiring / seeking agency or developer"),
        ('"need a" ("solidity" OR "smart contract" OR "designer" OR "marketer")', "Direct role specification"),
        ('"anyone recommend" ("agency" OR "freelancer" OR "auditor")', "Community recommendation request"),
        ('"who can build" OR "who can help build"', "Direct project inquiry"),
        ('"budget available" OR "budget:" OR "paid gig"', "Explicit funded need"),
    ]

    for phrase, rationale in need_patterns:
        # Construct query: "base_term" phrase negatives filters
        q = f'"{base_term}" {phrase} {neg_ops} {base_filters}'.strip()
        variants.append(QueryVariant(
            query_string=q,
            strategy=QueryVariantStrategy.NEED_SIGNAL,
            rationale=f"Targeting buyers in {base_term}: {rationale}"
        ))

    # STRATEGY 2: ICP-Bio & Role Search (Target persona + action verbs)
    roles = brief.icp.roles[:3] if brief.icp.roles else ["founder", "CEO"]
    role_group = " OR ".join([f'"{r}"' for r in roles])
    
    icp_patterns = [
        (f'({role_group}) "we are hiring" {base_term}', "Executive / founder announcing hiring"),
        (f'({role_group}) "looking for a co-founder" OR "looking for an engineer" {base_term}', "Leadership building core team"),
        (f'({role_group}) "DM me if you" ({base_term} OR "build")', "Founder requesting inbound solutions"),
    ]

    for q_template, rationale in icp_patterns:
        q = f'{q_template} {neg_ops} {base_filters}'.strip()
        variants.append(QueryVariant(
            query_string=q,
            strategy=QueryVariantStrategy.ICP_BIO,
            rationale=f"Founder role matching: {rationale}"
        ))

    # STRATEGY 3: Pain-Point & Frustration Queries
    pain_patterns = [
        (f'"{base_term}" ("struggling with" OR "tired of" OR "broken")', "Founder expressing pain point in niche"),
        (f'"{base_term}" ("need advice on" OR "how do you handle")', "Founder seeking external solution/guidance"),
        (f'"{base_term}" ("replacing our" OR "alternative to")', "Active vendor replacement search"),
    ]

    for q_template, rationale in pain_patterns:
        q = f'{q_template} {neg_ops} {base_filters}'.strip()
        variants.append(QueryVariant(
            query_string=q,
            strategy=QueryVariantStrategy.PAIN_POINT,
            rationale=f"Pain point matching: {rationale}"
        ))

    # Deduplicate and cap to max_variants
    seen = set()
    deduped = []
    for v in variants:
        if v.query_string not in seen:
            seen.add(v.query_string)
            deduped.append(v)
            if len(deduped) >= max_variants:
                break

    return deduped
