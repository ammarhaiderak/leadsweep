"""Discovery planning: turn a user request into bounded Reddit queries.

This is deterministic and free ($0). It expands a commercial-intent brief into a small number of
search terms and subreddit targets; it does NOT decide whether a post is a lead. Semantic
judgement is left to the existing LangGraph qualification pipeline, which verifies evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .subreddit import parse_subreddit_list

# Used only to expand a bare query into a few retrieval phrasings. These are search terms,
# never lead-classification signals.
_INTENT_SEARCH_SUFFIXES = (
    "looking for recommendation",
    "need help with",
    "anyone know a tool",
)

MAX_TERMS = 6


@dataclass(slots=True)
class RedditDiscoveryPlan:
    """Bounded execution plan for one Reddit job."""

    terms: list[str] = field(default_factory=list)
    subreddits: list[str] = field(default_factory=list)
    sort: str = "new"
    time_filter: str | None = None
    limit: int = 25
    max_pages: int = 2
    include_comments: bool = False
    comment_budget: int = 0
    date_from: str | None = None
    date_to: str | None = None
    raw_query: str = ""

    @property
    def mode(self) -> str:
        if self.terms and self.subreddits:
            return "keyword_and_subreddit"
        if self.subreddits:
            return "subreddit"
        return "keyword"

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "terms": list(self.terms),
            "subreddits": list(self.subreddits),
            "sort": self.sort,
            "time_filter": self.time_filter,
            "limit": self.limit,
            "max_pages": self.max_pages,
            "include_comments": self.include_comments,
            "comment_budget": self.comment_budget,
            "date_from": self.date_from,
            "date_to": self.date_to,
        }


def split_terms(raw_query: str) -> list[str]:
    """Split a user query on the project's existing multi-query separators."""
    if not raw_query or not raw_query.strip():
        return []
    parts = re.split(r"(?:\s+(?:or|OR)\s+|\s*,\s*|\s*\|\s*)", raw_query.strip())
    terms: list[str] = []
    for part in parts:
        cleaned = re.sub(r"\s+", " ", part).strip().strip('"').strip("'")
        # A bare subreddit target is a target, not a search term.
        if not cleaned or re.fullmatch(r"(?:https?://)?(?:www\.)?reddit\.com/r/\S+", cleaned, re.IGNORECASE):
            continue
        if re.fullmatch(r"(?:r/)?[A-Za-z0-9_]{2,21}", cleaned) and cleaned.lower().startswith("r/"):
            continue
        if cleaned not in terms:
            terms.append(cleaned)
    return terms[:MAX_TERMS]


def expand_intent_terms(terms: list[str], *, enabled: bool = True) -> list[str]:
    """Add a couple of retrieval phrasings so recommendation-seeking posts surface.

    Bounded and deterministic: quality gating still happens downstream.
    """
    if not enabled or not terms:
        return terms
    expanded: list[str] = list(terms)
    for term in terms[:1]:
        for suffix in _INTENT_SEARCH_SUFFIXES:
            candidate = f"{term} {suffix}"
            if candidate not in expanded:
                expanded.append(candidate)
    return expanded[:MAX_TERMS]


def build_plan(raw_query: str, options: dict[str, Any] | None = None, *, max_pages: int = 2) -> RedditDiscoveryPlan:
    """Build a discovery plan from a raw query plus wizard/job options."""
    opts = options or {}
    raw = (raw_query or "").strip()

    subreddits = parse_subreddit_list(opts.get("subreddits") or opts.get("subreddit"))
    terms = split_terms(raw)

    # If the query itself is a subreddit reference, treat it as a target only.
    if not terms and not subreddits and raw:
        from .subreddit import normalize_subreddit_target

        guess = normalize_subreddit_target(raw)
        if guess:
            subreddits = [guess]
        else:
            terms = [raw]

    intent_expansion = bool(opts.get("expand_intent_queries", True))
    terms = expand_intent_terms(terms, enabled=intent_expansion and bool(subreddits))

    include_comments = bool(opts.get("includeComments") or opts.get("include_comments"))
    plan = RedditDiscoveryPlan(
        terms=terms,
        subreddits=subreddits,
        sort=str(opts.get("sort") or "new"),
        time_filter=opts.get("time_filter") or opts.get("timeFilter"),
        limit=max(1, min(int(opts.get("pageSize") or opts.get("page_size") or 25), 100)),
        max_pages=max(1, min(int(opts.get("maxPages") or max_pages), 10)),
        include_comments=include_comments,
        comment_budget=max(0, min(int(opts.get("commentBudget") or 3), 25)) if include_comments else 0,
        date_from=opts.get("dateFrom") or opts.get("date_from"),
        date_to=opts.get("dateTo") or opts.get("date_to"),
        raw_query=raw,
    )
    return plan
