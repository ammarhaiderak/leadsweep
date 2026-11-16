# NEW FEATURE: Lead Intelligence Query Compiler
"""
Compiles 6-12 diverse, strategic search queries across selected strategies (S1..S6).
Employs proper Twitter advanced search syntax:
- Space for AND (never literal 'AND')
- Parenthesized OR groups
- -filter:retweets -filter:replies lang:en
- Exclusion operators
"""
from typing import List
from leadsweep.leadintel.models import LeadBrief, QueryVariant, StrategyType


def format_exclusion_operators(exclusions: List[str]) -> str:
    """Format negative terms into Twitter syntax."""
    priority = [
        "open to work", "looking for work", "hire me", "my portfolio",
        "available for hire", "airdrop", "giveaway"
    ]
    chosen = []
    excl_set = set(exclusions)
    for p in priority:
        if p in excl_set:
            chosen.append(p)
    for e in exclusions:
        if e not in chosen and len(chosen) < 7:
            chosen.append(e)

    ops = []
    for term in chosen:
        cleaned = term.strip().replace('"', '')
        if " " in cleaned:
            ops.append(f'-"{cleaned}"')
        else:
            ops.append(f'-{cleaned}')
    return " ".join(ops)


def compile_queries(brief: LeadBrief, strategies: List[StrategyType], target_count: int = 8) -> List[QueryVariant]:
    """
    Produces a strategic portfolio of 6-12 query variants.
    """
    base_terms = brief.icp_domains if brief.icp_domains else [brief.offer.split()[0]]
    domain_group = " OR ".join([f'"{d}"' if " " in d else d for d in base_terms[:3]])
    if not domain_group:
        domain_group = "web3 OR crypto OR AI OR tech"

    neg_ops = format_exclusion_operators(brief.exclusions)
    base_filters = f"-filter:retweets -filter:replies lang:{brief.language}".strip()

    variants: List[QueryVariant] = []

    # STRATEGY S1: Need-Signal Posts
    if StrategyType.S1_NEED_SIGNAL in strategies:
        need_patterns = [
            ('("looking for" OR "need a" OR "who can build") (developer OR agency OR engineer)', "Direct role/agency search", 0.75),
            ('("anyone recommend" OR "who does") ("smart contract" OR website OR audit OR marketing)', "Recommendation inquiry", 0.80),
            ('("budget available" OR "paid gig" OR "RFP")', "Funded demand signal", 0.85),
        ]
        for pattern, rationale, exp_prec in need_patterns:
            q = f'({domain_group}) {pattern} {neg_ops} {base_filters}'.strip()
            variants.append(QueryVariant(
                strategy=StrategyType.S1_NEED_SIGNAL,
                query_string=q,
                rationale=rationale,
                expected_precision=exp_prec
            ))

    # STRATEGY S2: Pain-Point Posts
    if StrategyType.S2_PAIN_POINT in strategies:
        pain_patterns = [
            ('("struggling with" OR "tired of" OR "can\'t find a reliable")', "Founder expressing acute frustration", 0.70),
            ('("our dev left" OR "contract got exploited" OR "broken integration")', "Emergency pain trigger", 0.75),
        ]
        for pattern, rationale, exp_prec in pain_patterns:
            q = f'({domain_group}) {pattern} {neg_ops} {base_filters}'.strip()
            variants.append(QueryVariant(
                strategy=StrategyType.S2_PAIN_POINT,
                query_string=q,
                rationale=rationale,
                expected_precision=exp_prec
            ))

    # STRATEGY S3: ICP-Bio & Role Search
    if StrategyType.S3_ICP_BIO in strategies:
        roles = brief.icp_roles[:3] if brief.icp_roles else ["founder", "CEO"]
        role_group = " OR ".join([f'"{r}"' if " " in r else r for r in roles])
        icp_patterns = [
            (f'({role_group}) "we are hiring"', "Founder announcing paid hiring", 0.80),
            (f'({role_group}) "looking for a co-founder" OR "looking for an engineer"', "Executive team expansion", 0.70),
        ]
        for pattern, rationale, exp_prec in icp_patterns:
            q = f'({domain_group}) {pattern} {neg_ops} {base_filters}'.strip()
            variants.append(QueryVariant(
                strategy=StrategyType.S3_ICP_BIO,
                query_string=q,
                rationale=rationale,
                expected_precision=exp_prec
            ))

    # STRATEGY S5: Trigger Events
    if StrategyType.S5_TRIGGER_EVENTS in strategies:
        trigger_patterns = [
            ('("just raised" OR "closed pre-seed" OR "closed seed")', "Recently funded company with budget", 0.75),
            ('("launching mainnet" OR "launching token" OR "minting next month")', "Imminent deployment needing services", 0.70),
        ]
        for pattern, rationale, exp_prec in trigger_patterns:
            q = f'({domain_group}) {pattern} {neg_ops} {base_filters}'.strip()
            variants.append(QueryVariant(
                strategy=StrategyType.S5_TRIGGER_EVENTS,
                query_string=q,
                rationale=rationale,
                expected_precision=exp_prec
            ))

    # STRATEGY S6: Competitor / Tool Dissatisfaction
    if StrategyType.S6_COMPETITOR_DISSATISFACTION in strategies:
        comp_patterns = [
            ('("alternative to" OR "switching from" OR "replacing")', "Active vendor replacement search", 0.75),
        ]
        for pattern, rationale, exp_prec in comp_patterns:
            q = f'({domain_group}) {pattern} {neg_ops} {base_filters}'.strip()
            variants.append(QueryVariant(
                strategy=StrategyType.S6_COMPETITOR_DISSATISFACTION,
                query_string=q,
                rationale=rationale,
                expected_precision=exp_prec
            ))

    # Deduplicate variants
    seen = set()
    deduped = []
    for v in variants:
        if v.query_string not in seen:
            seen.add(v.query_string)
            deduped.append(v)
            if len(deduped) >= target_count:
                break

    return deduped


compile_query_portfolio = compile_queries

