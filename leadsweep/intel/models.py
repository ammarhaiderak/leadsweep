# NEW FEATURE: Query Intelligence Models & Schemas
"""
Query Intelligence Layer - Brief Models, Enums, and Direction Taxonomy.
Follows Pydantic v2 conventions and strict validation.
"""
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class DirectionLabel(str, Enum):
    BUYER_SIGNAL = "BUYER_SIGNAL"
    HIRING_SIGNAL = "HIRING_SIGNAL"
    PARTNER_OR_FUNDING_SEEKER_FOR_OFFER = "PARTNER_OR_FUNDING_SEEKER_FOR_OFFER"
    JOB_SEEKER = "JOB_SEEKER"
    SERVICE_PROVIDER_PROMO = "SERVICE_PROVIDER_PROMO"
    INFO_OR_THOUGHT_CONTENT = "INFO_OR_THOUGHT_CONTENT"
    AIRDROP_BOT_SPAM = "AIRDROP_BOT_SPAM"
    UNCLEAR = "UNCLEAR"


# Direction Hard Caps
DIRECTION_SCORE_CAPS: Dict[DirectionLabel, int] = {
    DirectionLabel.BUYER_SIGNAL: 100,
    DirectionLabel.HIRING_SIGNAL: 90,
    DirectionLabel.PARTNER_OR_FUNDING_SEEKER_FOR_OFFER: 80,
    DirectionLabel.INFO_OR_THOUGHT_CONTENT: 25,
    DirectionLabel.JOB_SEEKER: 20,
    DirectionLabel.SERVICE_PROVIDER_PROMO: 20,
    DirectionLabel.AIRDROP_BOT_SPAM: 5,
    DirectionLabel.UNCLEAR: 50,  # Routes to NEEDS_REVIEW
}


class ICPProfile(BaseModel):
    roles: List[str] = Field(default_factory=list, description="Target buyer roles (e.g. founder, CTO, lead developer)")
    industries: List[str] = Field(default_factory=list, description="Target industry verticals (e.g. Web3, DeFi, SaaS)")
    company_stage: Optional[str] = Field(None, description="Stage (e.g. Seed, Series A, bootstrapped)")
    geography: Optional[str] = Field(None, description="Target regions or Global")
    language: str = Field(default="en", description="Target language code")


class LeadBrief(BaseModel):
    brief_id: str = Field(..., description="Unique ID of the Lead Brief")
    raw_query: str = Field(..., description="Original user raw query")
    offer: str = Field(..., description="What the user sells or provides (e.g. smart contract development and security audits)")
    icp: ICPProfile = Field(default_factory=ICPProfile)
    need_signals: List[str] = Field(
        default_factory=list,
        description="Verifiable buying/hiring phrases indicating explicit need (e.g. 'looking for', 'need a dev', 'budget')"
    )
    exclusions: List[str] = Field(
        default_factory=list,
        description="Terms/patterns that disqualify (e.g. 'open to work', 'airdrop', 'my portfolio')"
    )
    recency_days: int = Field(default=30, description="Recency window in days")
    volume_target: int = Field(default=50, description="Desired total lead count")
    quality_bar: float = Field(default=0.7, description="Target precision score threshold")
    assumptions: List[str] = Field(
        default_factory=list,
        description="Assumptions made when formulating the brief from vague input"
    )


class QueryVariantStrategy(str, Enum):
    NEED_SIGNAL = "need_signal"
    ICP_BIO = "icp_bio"
    PAIN_POINT = "pain_point"


class QueryVariant(BaseModel):
    query_string: str = Field(..., description="Exact Twitter search query string with operators")
    strategy: QueryVariantStrategy = Field(..., description="Strategic intent category")
    rationale: str = Field(..., description="Explanation of why this variant finds buyers")
    measured_precision: Optional[float] = Field(None, description="Precision measured during probe loop")
    items_scraped: int = Field(default=0, description="Items scraped during probing")
    buyers_found: int = Field(default=0, description="Buyers/hiring leads found during probing")


class DirectionClassificationResult(BaseModel):
    direction: DirectionLabel = Field(..., description="Categorized direction label")
    max_score_cap: int = Field(..., description="Maximum allowable score cap for this direction")
    reason: str = Field(..., description="Brief explanation for this classification")
    evidence_quote: str = Field(default="", description="Verbatim quote from post text proving the classification")
    quote_verified: bool = Field(default=False, description="Whether the quote was verified to appear in post text")
    is_fallback: bool = Field(default=False, description="True if heuristic rules were used instead of LLM")
