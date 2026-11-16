"""Relevance Engine and Query Understanding for LeadSweep ($0 deterministic).

Architecture (PHASE 3 & 4):
- QueryIntent: Extracts platform, target_entity, industry, location, keywords.
- RelevanceEngine: Evaluates candidate LeadRecords against query intent.
  Computes multi-factor relevance_score (0.0 - 1.0) and applies hard threshold.
- Rejects noise, random tutorials, unrelated accounts, and non-leads.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from pydantic import BaseModel, Field

from leadsweep.adapters import LeadRecord

log = logging.getLogger("leadsweep.relevance")

# Common job/founder titles & intent triggers
TITLES = [
    "founder", "co-founder", "ceo", "cto", "cpo", "vp", "director", "head of",
    "lead", "manager", "engineer", "developer", "architect", "consultant",
    "freelancer", "creator", "owner", "partner", "president", "executive"
]

INDUSTRIES = [
    "saas", "ai", "artificial intelligence", "automation", "b2b", "crypto",
    "web3", "fintech", "edtech", "healthtech", "ecommerce", "software",
    "marketing", "agency", "tech", "design", "cloud", "devops"
]

LOCATIONS = [
    "lahore", "karachi", "islamabad", "pakistan", "london", "uk", "new york",
    "san francisco", "california", "us", "usa", "berlin", "germany", "dubai",
    "uae", "toronto", "canada", "remote", "global", "singapore", "india"
]


class QueryIntent(BaseModel):
    """Structured understanding of natural-language user search requests."""
    raw_query: str
    target_entity: str | None = None
    industry: str | None = None
    location: str | None = None
    keywords: list[str] = Field(default_factory=list)
    platform: str | None = None
    intent: str = "potential lead/prospect"

    @classmethod
    def parse(cls, query: str, platform: str | None = None) -> QueryIntent:
        """Deterministic, $0-cost rule-based natural language query understanding."""
        q_lower = query.lower().strip()
        words = re.findall(r"\b\w+\b", q_lower)

        # 1. Target entity / Role
        found_entity: str | None = None
        for t in TITLES:
            if t in q_lower:
                found_entity = t
                break

        # 2. Industry / Domain
        found_industry: str | None = None
        for ind in INDUSTRIES:
            if ind in q_lower:
                found_industry = ind
                break

        # 3. Location
        found_location: str | None = None
        for loc in LOCATIONS:
            if loc in q_lower:
                found_location = loc
                break

        # 4. Extracted keywords (excluding stop words)
        stopwords = {
            "find", "search", "looking", "for", "in", "at", "who", "are", "with",
            "the", "a", "an", "and", "or", "to", "of", "on", "by", "is", "get",
            "want", "need", "hire", "leads"
        }
        kw = [w for w in words if w not in stopwords and len(w) > 2]

        return cls(
            raw_query=query,
            target_entity=found_entity,
            industry=found_industry,
            location=found_location,
            keywords=kw,
            platform=platform,
            intent="b2b_lead_prospect",
        )


class RelevanceEngine:
    """Evaluates candidates, scores relevance (0-100), and rejects noise below threshold."""

    def __init__(self, threshold: float = 0.40) -> None:
        self.threshold = threshold

    def evaluate(self, candidate: LeadRecord, intent: QueryIntent) -> tuple[bool, float, list[str]]:
        """Score a candidate against the extracted query intent.
        
        Returns:
            (is_accepted, score_0_to_1, matched_signals)
        """
        text_corpus = f"{candidate.name} {candidate.username} {candidate.headline or ''} {candidate.title or ''} {candidate.bio or ''} {candidate.content} {candidate.company or ''} {candidate.location or ''}".lower()

        signals: list[str] = []
        score = 0.0

        # 1. Keyword match (Weight 0.35)
        if intent.keywords:
            matched_kw = [kw for kw in intent.keywords if kw in text_corpus]
            kw_ratio = len(matched_kw) / max(len(intent.keywords), 1)
            score += kw_ratio * 0.35
            if matched_kw:
                signals.append(f"matched_keywords:{','.join(matched_kw[:3])}")
        else:
            score += 0.20

        # 2. Entity / Role match (Weight 0.25)
        if intent.target_entity:
            if intent.target_entity in text_corpus:
                score += 0.25
                signals.append(f"matched_role:{intent.target_entity}")
        else:
            score += 0.15

        # 3. Industry / Tech match (Weight 0.20)
        if intent.industry:
            if intent.industry in text_corpus:
                score += 0.20
                signals.append(f"matched_industry:{intent.industry}")
        else:
            score += 0.10

        # 4. Location match (Weight 0.15)
        if intent.location:
            if intent.location in text_corpus:
                score += 0.15
                signals.append(f"matched_location:{intent.location}")
        else:
            score += 0.10

        # 5. Profile Quality & Actionability (Weight 0.05)
        if candidate.profile_url or candidate.website:
            score += 0.05
            signals.append("profile_verified")

        # Hard noise penalty (e.g. food, generic recipes, video games if query was tech)
        noise_keywords = ["recipe", "football", "celebrity gossip", "horoscope", "diet", "meme"]
        if any(nk in text_corpus for nk in noise_keywords) and not any(nk in intent.raw_query.lower() for nk in noise_keywords):
            score -= 0.30

        final_score = max(0.0, min(1.0, round(score, 2)))
        candidate.relevance_score = final_score
        candidate.lead_score = int(final_score * 100)

        is_accepted = final_score >= self.threshold
        return is_accepted, final_score, signals
