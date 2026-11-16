from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..models import Tweet

QueryType = Literal["lead", "rfp", "trend"]
Category = Literal["lead", "rfp", "trend", "noise"]


class QuerySpec(BaseModel):
    name: str
    q: str = Field(min_length=1, max_length=512)
    type: QueryType = "lead"
    max_results: int | None = Field(default=None, ge=1, le=100)
    enabled: bool = True


class AgencyProfile(BaseModel):
    name: str = "Our agency"
    services: list[str] = Field(default_factory=list)
    ideal_clients: list[str] = Field(default_factory=list)


class PipelineConfig(BaseModel):
    max_results_per_query: int = Field(default=20, ge=1, le=100)
    min_score: int = Field(default=70, ge=0, le=100)
    heuristic_min_score: int = Field(default=80, ge=0, le=100)  # UPDATED LOGIC (P3.1): stricter bar when no LLM judged the post
    agency: AgencyProfile = Field(default_factory=AgencyProfile)
    queries: list[QuerySpec]


def load_pipeline_config(path: Path) -> PipelineConfig:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    cfg = PipelineConfig.model_validate(
        {**raw.get("settings", {}), "agency": raw.get("agency", {}), "queries": raw.get("queries", [])}
    )
    names = [q.name for q in cfg.queries]
    if len(names) != len(set(names)):
        raise ValueError("duplicate query names in queries.toml")
    return cfg


class LeadScore(BaseModel):
    """Structured verdict for one post (also the JSON schema sent to the LLM)."""

    score: int = Field(ge=0, le=100, description="0-100 lead quality")
    category: Category = Field(description="lead | rfp | trend | noise")
    intent_signals: list[str] = Field(default_factory=list, description="short phrases from the post that justify the score")
    reason: str = Field(default="", description="one sentence explanation")
    suggested_action: str = Field(default="", description="one sentence next step for the BD team, empty for noise")

    @field_validator("score", mode="before")
    @classmethod
    def _clamp(cls, v):
        try:
            return max(0, min(100, int(round(float(v)))))
        except (TypeError, ValueError):
            return v

    @field_validator("intent_signals", mode="before")
    @classmethod
    def _signals(cls, v):
        if isinstance(v, str):
            v = [v]
        return list(v)[:6] if isinstance(v, (list, tuple)) else v


class Fetched(BaseModel):
    tweet: Tweet
    query_name: str
    query_type: QueryType


class Candidate(BaseModel):
    tweet: Tweet
    queries: list[str]
    query_type: QueryType


class ScoredTweet(BaseModel):
    tweet: Tweet
    queries: list[str]
    query_type: QueryType
    score: LeadScore
    heuristic_score: int
    scored_by: str
