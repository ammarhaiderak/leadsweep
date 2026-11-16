"""
leadsweep/core/contract_models.py -- Contract Schemas for Buying-Intent Listening Engine

Enforces strict closed sets, rejection logic, and exact data models:
- RawItem
- LeadDecision
- Checkpoint
- QueryPack
- SalesIntentType (closed set)
"""
from __future__ import annotations

import enum
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class SalesIntentType(str, enum.Enum):
    # Closed set for sales paging / alert
    ACTIVE_BUY = "ACTIVE_BUY"
    ALTERNATIVE = "ALTERNATIVE"
    COMPETITOR_PAIN = "COMPETITOR_PAIN"
    IMPLEMENTATION = "IMPLEMENTATION"
    BUDGET = "BUDGET"
    HIRING_FOR_PROBLEM = "HIRING_FOR_PROBLEM"

    # Non-paging types
    SUPPORT_EXISTING_CUSTOMER = "SUPPORT_EXISTING_CUSTOMER"
    MENTION_ONLY = "MENTION_ONLY"
    OFF_TOPIC = "OFF_TOPIC"


PAGING_INTENT_TYPES = {
    SalesIntentType.ACTIVE_BUY,
    SalesIntentType.ALTERNATIVE,
    SalesIntentType.COMPETITOR_PAIN,
    SalesIntentType.IMPLEMENTATION,
    SalesIntentType.BUDGET,
    SalesIntentType.HIRING_FOR_PROBLEM,
}


class RawItem(BaseModel):
    source: str = Field(..., description="Source connector id e.g. hn, bluesky, lobsters, devto, github, stackexchange")
    native_id: str = Field(..., description="Unique platform item id")
    thread_id: str = Field(..., description="Thread or discussion grouping id")
    url: str = Field(..., description="Direct public URL")
    item_type: Literal["post", "comment"] = Field(..., description="Item type")
    author_handle: str = Field(..., description="Public handle on post")
    community: str = Field(..., description="Community, subreddit, tag, or repo name")
    source_created_at: Optional[datetime] = Field(None, description="Native UTC timestamp, never imputed as now")
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    body: str = Field(..., description="Post or comment text")
    title: Optional[str] = Field(None, description="Title if post, or None")
    parent_excerpt: Optional[str] = Field(None, description="Excerpt of parent item for comments")
    raw_extra: Dict[str, Any] = Field(default_factory=dict, description="Unknown extra JSON fields from upstream")
    payload_sha256: str = Field("", description="SHA-256 hash of raw upstream payload")
    license_id: str = Field("public_api_v1", description="License identifier or contract id")
    retain_until: Optional[datetime] = Field(None, description="Data retention boundary")

    @model_validator(mode="before")
    @classmethod
    def _compute_payload_sha(cls, values: Any) -> Any:
        if isinstance(values, dict):
            if not values.get("payload_sha256"):
                body_val = values.get("body") or ""
                native_val = values.get("native_id") or ""
                values["payload_sha256"] = hashlib.sha256(f"{native_val}:{body_val}".encode("utf-8")).hexdigest()
        return values

    @property
    def is_complete(self) -> bool:
        """Comment with no parent excerpt or missing source_created_at -> incomplete, not alertable."""
        if self.source_created_at is None:
            return False
        if not self.body or not self.body.strip():
            return False
        if self.item_type == "comment" and (self.parent_excerpt is None or not self.parent_excerpt.strip()):
            return False
        return True


class AlertClass(str, enum.Enum):
    ALERT = "alert"
    REVIEW = "review"
    DROP = "drop"


class LeadDisposition(str, enum.Enum):
    NEW = "new"
    ACTED = "acted"
    DISMISSED = "dismissed"
    SNOOZED = "snoozed"


class LeadDecision(BaseModel):
    decision_id: str = Field(..., description="Unique deterministic decision id (source:native_id:model_ver)")
    source: str
    native_id: str
    query_pack_hash: str
    intent_type: SalesIntentType
    intent_score: int = Field(ge=0, le=100, description="Intent score 0..100 from text only")
    icp_score: int = Field(ge=0, le=100, description="ICP score 0..100 from role, community, geo hints")
    priority: float = Field(..., description="intent * icp / 100 * exp(-age_hours / 12)")
    evidence_span: str = Field(..., description="<=30 word quote appearing verbatim in the post")
    reason: str = Field(..., description="Concise rationale for score and intent")
    model_version: str = Field(..., description="Pinned model / prompt version")
    alert_class: AlertClass = Field(..., description="alert | review | drop")
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    disposition: LeadDisposition = Field(default=LeadDisposition.NEW)
    reply_draft: Optional[str] = Field(None, description="Human-send only draft, alert class only, not_sent")

    @field_validator("evidence_span")
    @classmethod
    def _validate_quote_word_count(cls, v: str) -> str:
        words = v.strip().split()
        if len(words) > 30:
            raise ValueError(f"evidence_span quote must be <= 30 words, got {len(words)}")
        return v


class Checkpoint(BaseModel):
    source: str
    cursor: Optional[str] = None
    watermark_time: Optional[datetime] = None
    last_native_id: Optional[str] = None
    lease_owner: Optional[str] = None
    lease_until: Optional[datetime] = None


class QueryPack(BaseModel):
    version: str
    hash: str
    icp_id: str
    families: List[str] = Field(default_factory=list, description="Buyer-voice query families")
    communities: List[str] = Field(default_factory=list, description="Community allowlist from ICP")
    negatives: List[str] = Field(default_factory=list, description="Deterministic negative pack")
    compiled_per_source: Dict[str, str] = Field(default_factory=dict, description="Target query strings per source")
