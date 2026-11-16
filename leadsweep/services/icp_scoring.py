"""ICP Qualification Engine: Heuristic Bio Rules + Batched Groq LLM Scoring.

Evaluates X profiles against target ICP (e.g. Founders, CTOs, Engineering Leads, AI buyers)
conserving LLM tokens by batching profiles in small groups (up to 5 per prompt).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from leadsweep.config import Settings, get_settings
from leadsweep.models import XUser
from leadsweep.pipeline.store import Store

log = logging.getLogger("leadsweep.services.icp")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- Heuristic Rules
ROLE_HIGH: dict[str, int] = {
    "founder": 30, "co-founder": 30, "ceo": 30, "cto": 30, "cpo": 25,
    "vp of engineering": 25, "head of engineering": 25, "head of product": 20,
    "head of ai": 25, "director of engineering": 20, "chief architect": 20,
    "owner": 15, "managing director": 20,
}

ROLE_MEDIUM: dict[str, int] = {
    "product manager": 15, "lead engineer": 15, "tech lead": 15,
    "engineering manager": 15, "staff engineer": 12, "principal engineer": 12,
    "ai engineer": 15, "full-stack developer": 10, "software architect": 12,
}

TECH_INTEREST: dict[str, int] = {
    "building": 15, "stealth": 15, "saas": 15, "ai": 12, "llm": 12, "agents": 12,
    "automation": 12, "workflow": 10, "data pipelines": 10, "startups": 10,
    "hiring": 20, "backed by": 15, "y combinator": 15, "yc": 10,
}

NEGATIVE_SIGNALS: dict[str, int] = {
    "student": -25, "intern": -25, "seeking opportunities": -20, "#opentowork": -25,
    "crypto trader": -25, "airdrop": -30, "memecoin": -30, "bot": -40,
    "parody": -50, "fan account": -40,
}


def _norm(text: str) -> str:
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text).replace("’", "'").replace("‘", "'")
    return " ".join(t.lower().split())


def calculate_rules_score(user: XUser) -> tuple[int, str, list[str]]:
    """Calculates heuristic 0-100 score based on title, keywords, followers, and verification."""
    bio = _norm(user.bio or "")
    name = _norm(user.name or "")
    combined = f"{name} {bio}"

    score = 20  # base score
    matched_signals: list[str] = []
    persona = "Individual / Specialist"

    # Check high-value decision maker roles
    for role, w in ROLE_HIGH.items():
        if re.search(r"(?<!\w)" + re.escape(role) + r"(?!\w)", combined):
            score += w
            matched_signals.append(f"role:{role}")
            persona = "Founder / Executive"
            break

    # If no executive, check tech/management roles
    if persona == "Individual / Specialist":
        for role, w in ROLE_MEDIUM.items():
            if re.search(r"(?<!\w)" + re.escape(role) + r"(?!\w)", combined):
                score += w
                matched_signals.append(f"role:{role}")
                persona = "Engineering / Product Leader"
                break

    # Tech & buying keywords
    for kw, w in TECH_INTEREST.items():
        if re.search(r"(?<!\w)" + re.escape(kw) + r"(?!\w)", combined):
            score += w
            matched_signals.append(f"kw:{kw}")

    # Negative signals
    for neg, w in NEGATIVE_SIGNALS.items():
        if re.search(r"(?<!\w)" + re.escape(neg) + r"(?!\w)", combined):
            score += w
            matched_signals.append(f"neg:{neg}")

    # Follower sanity checks
    if user.followers_count:
        if 200 <= user.followers_count <= 25000:
            score += 10  # healthy active builder/operator range
            matched_signals.append("followers_sweet_spot")
        elif user.followers_count > 100000:
            score -= 5  # celebrity / influencer, hard to reach

    if user.is_blue_verified:
        score += 5
        matched_signals.append("verified")

    # Clamping
    final_score = max(0, min(100, score))
    return final_score, persona, matched_signals


# --------------------------------------------------------------------------- Structured Outputs
class ProfileEvaluation(BaseModel):
    user_id: str
    icp_score: int = Field(ge=0, le=100)
    persona: str
    fit_reason: str
    outreach_angle: str


class BatchEvaluationResponse(BaseModel):
    evaluations: list[ProfileEvaluation]


SYSTEM_PROMPT = """You are an expert B2B qualification engine evaluating prospective Twitter/X profiles for an AI & Automation agency.
Our services: AI agents, workflow automation, web scraping/data pipelines, LLM applications, MCP servers.
Target ICP: Founders, CTOs, VP Engineering, Product Leaders, Tech Leads looking to build AI products or automate business operations.

For each user profile provided, evaluate:
1. icp_score (0-100): likelihood they could be a decision-maker or client needing our services.
2. persona: concise category (e.g. 'Startup Founder', 'Tech Lead', 'Agency Owner', 'Unqualified').
3. fit_reason: 1 sentence explaining the fit or lack of fit.
4. outreach_angle: 1 personalized sentence suggesting how to open a conversation.
"""


class ICPScoringService:
    def __init__(self, store: Store | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.store = store or Store(self.settings.db_path)

    def score_heuristically(self, user: XUser) -> dict[str, Any]:
        rules_score, persona, signals = calculate_rules_score(user)
        fit_reason = f"Heuristic match based on signals: {', '.join(signals[:4])}" if signals else "General profile"
        outreach_angle = f"Ask about their roadmap in {persona.lower()}"
        now = _now()

        # Ensure user exists in x_users to satisfy FK constraint
        self.store.db.execute(
            """
            INSERT OR IGNORE INTO x_users (rest_id, handle, name, bio, location, followers_count, following_count, is_blue_verified, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user.rest_id,
                user.handle,
                user.name,
                user.bio,
                user.location,
                user.followers_count,
                user.following_count,
                1 if user.is_blue_verified else 0,
                user.first_seen_at.isoformat(),
                user.last_seen_at.isoformat(),
            ),
        )

        self.store.db.execute(
            """
            INSERT INTO user_scores (user_id, icp_score, persona, fit_reason, outreach_angle, scored_by, scored_at, rules_score)
            VALUES (?, ?, ?, ?, ?, 'rules', ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                icp_score=excluded.icp_score,
                persona=excluded.persona,
                fit_reason=excluded.fit_reason,
                outreach_angle=excluded.outreach_angle,
                scored_by='rules',
                scored_at=excluded.scored_at,
                rules_score=excluded.rules_score
            """,
            (user.rest_id, rules_score, persona, fit_reason, outreach_angle, now, rules_score),
        )
        self.store.db.commit()

        return {
            "user_id": user.rest_id,
            "icp_score": rules_score,
            "persona": persona,
            "fit_reason": fit_reason,
            "outreach_angle": outreach_angle,
            "scored_by": "rules",
        }

    async def score_with_llm(self, users: list[XUser], batch_size: int = 5) -> list[dict[str, Any]]:
        """Batched Groq LLM scoring to evaluate multiple profiles per LLM request."""
        api_key = self.settings.groq_api_key
        if not api_key:
            # Fall back to heuristic rule scoring if Groq is not configured
            log.info("No Groq API key set, falling back to heuristic scoring for %d users", len(users))
            return [self.score_heuristically(u) for u in users]

        try:
            from langchain_groq import ChatGroq
            llm = ChatGroq(
                model=self.settings.groq_model,
                api_key=api_key,
                temperature=0,
                max_tokens=600,
            ).with_structured_output(BatchEvaluationResponse)
        except Exception as e:
            log.warning("Could not initialize ChatGroq: %s, falling back to rules", e)
            return [self.score_heuristically(u) for u in users]

        results: list[dict[str, Any]] = []
        now = _now()

        # Batch in chunks of 5
        for i in range(0, len(users), batch_size):
            chunk = users[i : i + batch_size]
            prompt_lines = ["Evaluate the following profiles:"]
            for u in chunk:
                r_score, _, _ = calculate_rules_score(u)
                prompt_lines.append(
                    f"User ID: {u.rest_id} | Handle: @{u.handle} | Name: {u.name or ''} | "
                    f"Bio: {u.bio or ''} | Followers: {u.followers_count or 0} | Rules Score: {r_score}"
                )

            messages = [
                ("system", SYSTEM_PROMPT),
                ("human", "\n".join(prompt_lines)),
            ]

            try:
                resp = await llm.ainvoke(messages)
                evals_map = {e.user_id: e for e in resp.evaluations} if hasattr(resp, "evaluations") else {}
                for u in chunk:
                    r_score, _, _ = calculate_rules_score(u)
                    ev = evals_map.get(u.rest_id)
                    if ev:
                        self.store.db.execute(
                            """
                            INSERT INTO user_scores (user_id, icp_score, persona, fit_reason, outreach_angle, scored_by, scored_at, rules_score)
                            VALUES (?, ?, ?, ?, ?, 'groq', ?, ?)
                            ON CONFLICT(user_id) DO UPDATE SET
                                icp_score=excluded.icp_score,
                                persona=excluded.persona,
                                fit_reason=excluded.fit_reason,
                                outreach_angle=excluded.outreach_angle,
                                scored_by='groq',
                                scored_at=excluded.scored_at,
                                rules_score=excluded.rules_score
                            """,
                            (u.rest_id, ev.icp_score, ev.persona, ev.fit_reason, ev.outreach_angle, now, r_score),
                        )
                        results.append({
                            "user_id": u.rest_id,
                            "icp_score": ev.icp_score,
                            "persona": ev.persona,
                            "fit_reason": ev.fit_reason,
                            "outreach_angle": ev.outreach_angle,
                            "scored_by": "groq",
                        })
                    else:
                        results.append(self.score_heuristically(u))
            except Exception as e:
                log.warning("Groq scoring failed for batch (%s), falling back to rules", e)
                for u in chunk:
                    results.append(self.score_heuristically(u))

        self.store.db.commit()
        return results

    def score_all_unscored(self, limit: int = 100) -> list[dict[str, Any]]:
        """Score all x_users in the database that do not yet have a user_scores record."""
        rows = self.store.db.execute(
            """
            SELECT u.* FROM x_users u
            LEFT JOIN user_scores us ON us.user_id = u.rest_id
            WHERE us.user_id IS NULL
            ORDER BY u.followers_count DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        out = []
        for r in rows:
            u = XUser(
                rest_id=r["rest_id"],
                handle=r["handle"],
                name=r["name"],
                bio=r["bio"],
                location=r["location"],
                followers_count=r["followers_count"],
                following_count=r["following_count"],
                is_blue_verified=bool(r["is_blue_verified"]),
            )
            out.append(self.score_heuristically(u))
        return out
