# NEW FEATURE: Lead Intelligence Strategy Portfolio Selector
"""
Selects appropriate retrieval strategies (S1..S8) based on the LeadBrief.
Strategies:
- S1 Need-signal posts: Topic keywords + explicit buying/hiring phrases + role nouns
- S2 Pain-point posts: Phrases real founders complain about ("dev left", "exploited", "can't find reliable")
- S3 ICP-bio targeting: Role keywords in bio combined with current domain signals
- S4 Reply mining: People asking for recommendations under popular posts
- S5 Trigger events: "just raised", "launching mainnet/mint", "hiring our first", "RFP", "grant"
- S6 Competitor/tool dissatisfaction: People complaining about competitor tools
- S7 Lookalike expansion: Using approved leads' vocabularies
- S8 Community seeds: High-signal target communities/lists
"""
from typing import List
from leadsweep.leadintel.models import LeadBrief, StrategyType


def select_strategies_for_brief(brief: LeadBrief) -> List[StrategyType]:
    """
    Deterministically selects high-leverage retrieval strategies tailored to the brief.
    Default high-confidence portfolio includes S1, S2, S3, S5, S6.
    """
    strategies = [
        StrategyType.S1_NEED_SIGNAL,
        StrategyType.S2_PAIN_POINT,
        StrategyType.S3_ICP_BIO
    ]

    # Trigger events (S5) are high-yield for funded startups / product launches
    if any(r in brief.icp_roles for r in ["founder", "CEO", "co-founder"]) or "startup" in brief.offer.lower():
        strategies.append(StrategyType.S5_TRIGGER_EVENTS)

    # Competitor dissatisfaction (S6) is high-yield for B2B services/SaaS
    if brief.offer_type in ("services", "product"):
        strategies.append(StrategyType.S6_COMPETITOR_DISSATISFACTION)

    return strategies


select_strategy_portfolio = select_strategies_for_brief

