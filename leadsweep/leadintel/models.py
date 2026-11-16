# NEW FEATURE: Lead Intelligence Data Models & Schemas
"""
Pydantic schemas for the Lead Intelligence Engine (LangGraph + LangChain).
Strict validation, TypedDict graph states, Direction taxonomy, and Score v2 dimensions.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class DirectionLabel(str, Enum):
    BUYER_SIGNAL = "BUYER_SIGNAL"
    HIRING_SIGNAL = "HIRING_SIGNAL"
    PARTNER_OR_FUNDING_FOR_OFFER = "PARTNER_OR_FUNDING_FOR_OFFER"
    JOB_SEEKER = "JOB_SEEKER"
    SERVICE_PROVIDER_PROMO = "SERVICE_PROVIDER_PROMO"
    INFO_OR_THOUGHT_CONTENT = "INFO_OR_THOUGHT_CONTENT"
    AIRDROP_BOT_SPAM = "AIRDROP_BOT_SPAM"
    UNCLEAR = "UNCLEAR"


# Direction Hard Caps
DIRECTION_SCORE_CAPS: Dict[DirectionLabel, int] = {
    DirectionLabel.BUYER_SIGNAL: 100,
    DirectionLabel.HIRING_SIGNAL: 90,
    DirectionLabel.PARTNER_OR_FUNDING_FOR_OFFER: 80,
    DirectionLabel.INFO_OR_THOUGHT_CONTENT: 25,
    DirectionLabel.JOB_SEEKER: 20,
    DirectionLabel.SERVICE_PROVIDER_PROMO: 20,
    DirectionLabel.AIRDROP_BOT_SPAM: 5,
    DirectionLabel.UNCLEAR: 50,  # Routes to NEEDS_REVIEW
}


class StrategyType(str, Enum):
    S1_NEED_SIGNAL = "S1_NEED_SIGNAL"
    S2_PAIN_POINT = "S2_PAIN_POINT"
    S3_ICP_BIO = "S3_ICP_BIO"
    S4_REPLY_MINING = "S4_REPLY_MINING"
    S5_TRIGGER_EVENTS = "S5_TRIGGER_EVENTS"
    S6_COMPETITOR_DISSATISFACTION = "S6_COMPETITOR_DISSATISFACTION"
    S7_LOOKALIKE = "S7_LOOKALIKE"
    S8_COMMUNITY_SEEDS = "S8_COMMUNITY_SEEDS"


class LeadBrief(BaseModel):
    offer: str = Field(..., description="What the user sells or provides")
    offer_type: Literal["services", "product", "recruiting", "investing", "partnership", "other"] = Field(
        default="services", description="Category of offer"
    )
    icp_roles: List[str] = Field(default_factory=list, description="Target buyer roles (founder, CEO, CTO, etc.)")
    icp_domains: List[str] = Field(default_factory=list, description="Target industry verticals (web3, defi, ai, etc.)")
    geo: List[str] = Field(default_factory=list, description="Target geography or regions")
    language: str = Field(default="en", description="Target language code")
    need_signals: List[str] = Field(
        default_factory=list, description="Actionable buying or hiring phrases ('looking for', 'need a dev', etc.)"
    )
    pain_points: List[str] = Field(
        default_factory=list, description="Common complaints or struggles expressed by real buyers"
    )
    include_hiring_posts: bool = Field(default=True, description="Whether paid hiring/job posts count as leads")
    exclusions: List[str] = Field(
        default_factory=list, description="Disqualifying terms ('open to work', 'airdrop', 'my portfolio')"
    )
    recency_days: int = Field(default=14, description="Search recency window in days")
    target_count: int = Field(default=50, description="Target lead count")
    quality_bar: float = Field(default=0.6, description="Target precision@10 threshold")
    assumptions: List[str] = Field(default_factory=list, description="Assumptions made from vague query")
    ambiguity: float = Field(default=0.0, description="Ambiguity score between 0.0 and 1.0")


class QueryVariant(BaseModel):
    strategy: StrategyType = Field(..., description="Retrieval strategy type")
    query_string: str = Field(..., description="Exact Twitter search query string with operators")
    rationale: str = Field(..., description="Why this variant targets real buyers")
    expected_precision: float = Field(default=0.7, description="Estimated precision")
    measured_precision: Optional[float] = Field(None, description="Precision measured during probe loop")
    items_scraped: int = Field(default=0, description="Items scraped during probing")
    buyers_found: int = Field(default=0, description="Buyers/hiring leads found during probing")


class DirectionClassificationResult(BaseModel):
    direction: DirectionLabel = Field(..., description="Categorized direction label")
    need_strength: float = Field(default=0.0, description="Need signal strength (0.0 to 1.0)")
    urgency: float = Field(default=0.0, description="Urgency level (0.0 to 1.0)")
    icp_fit: float = Field(default=0.0, description="Target ICP role/domain match (0.0 to 1.0)")
    confidence: float = Field(default=0.8, description="Classification confidence (0.0 to 1.0)")
    max_score_cap: int = Field(default=100, description="Maximum allowable score cap for this direction")
    reason: str = Field(..., description="Concise explanation of classification")
    evidence_quote: str = Field(default="", description="Verbatim quote from post text proving classification")
    quote_verified: bool = Field(default=False, description="Whether quote literally appears in post text")
    is_fallback: bool = Field(default=False, description="Whether heuristic fallback was used")


class ScoreV2(BaseModel):
    final_score: int = Field(..., description="Calibrated score from 0 to 100")
    direction: DirectionLabel = Field(...)
    direction_cap: int = Field(...)
    need_strength_score: int = Field(...)
    urgency_score: int = Field(...)
    icp_fit_score: int = Field(...)
    authority_score: int = Field(...)
    quote_verified: bool = Field(...)
    evidence_quote: str = Field(default="")
    why_text: str = Field(..., description="Human-readable explanation of why this score was assigned")


class LeadIntelTrace(BaseModel):
    run_id: str
    node_name: str
    model_used: str
    tokens_used: int = 0
    latency_ms: float = 0.0
    cache_hit: bool = False
    fallback_used: bool = False
