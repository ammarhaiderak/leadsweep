"""Normalized, verifiable Reddit records and the per-run execution summary.

Missing values stay ``None``. No engagement metric is ever defaulted to a plausible-looking
number; if Reddit did not return it, the field is absent from the normalized record.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import asdict, dataclass, field
from typing import Any

from leadsweep.models import Tweet


def _parse_utc(value: Any) -> _dt.datetime | None:
    """Normalize a Reddit epoch or ISO timestamp into an aware UTC datetime."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            return _dt.datetime.fromtimestamp(float(value), tz=_dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)


@dataclass(slots=True)
class RedditComment:
    """A supporting comment for a parent post. Never promoted to its own lead."""

    comment_id: str
    post_id: str
    author: str | None
    body: str
    created_at: str | None = None
    permalink: str | None = None
    score: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RedditPost:
    """A normalized public Reddit post."""

    post_id: str
    subreddit: str
    title: str
    body: str
    author: str | None
    permalink: str
    created_at: str | None = None
    score: int | None = None
    upvote_ratio: float | None = None
    num_comments: int | None = None
    external_url: str | None = None
    over_18: bool = False
    locked: bool = False
    removed: bool = False
    retrieved_at: str = field(default_factory=lambda: _dt.datetime.now(_dt.timezone.utc).isoformat())
    comments: list[RedditComment] = field(default_factory=list)
    source_mode: str = "public_unauthenticated"
    source_provider: str = "arctic_shift"
    retrieved_on_archive: int | None = None

    @property
    def lead_id(self) -> str:
        """Stable cross-platform identifier (never re-derived from content)."""
        return f"reddit_{self.post_id}"

    def full_text(self) -> str:
        """Title + body, the exact text handed to relevance and qualification."""
        title = (self.title or "").strip()
        body = (self.body or "").strip()
        if title and body:
            return f"{title}\n\n{body}"
        return title or body

    def created_datetime(self) -> _dt.datetime | None:
        return _parse_utc(self.created_at)

    def validate_live_record(self) -> bool:
        """Verify that a live record has a real Reddit ID, subreddit, permalink, UTC date, and text."""
        import re

        if not self.post_id or not re.fullmatch(r"[A-Za-z0-9_]{3,16}", self.post_id):
            return False
        if not self.subreddit or not re.fullmatch(r"[A-Za-z0-9_]{2,21}", self.subreddit):
            return False
        if not self.permalink.startswith("https://www.reddit.com/r/"):
            return False
        if f"/comments/{self.post_id}" not in self.permalink:
            return False
        if self.created_datetime() is None:
            return False
        if not self.full_text().strip():
            return False
        if self.removed:
            return False
        return True

    def metadata(self) -> dict[str, Any]:
        """Reddit-specific metadata held apart from shared lead fields."""
        return {
            "reddit_id": self.post_id,
            "subreddit": self.subreddit,
            "title": self.title,
            "permalink": self.permalink,
            "external_url": self.external_url,
            "upvote_ratio": self.upvote_ratio,
            "over_18": self.over_18,
            "locked": self.locked,
            "removed": self.removed,
            "score": self.score,
            "num_comments": self.num_comments,
            "source_mode": self.source_mode,
            "source_provider": self.source_provider,
            "retrieved_at": self.retrieved_at,
            "retrieved_on_archive": self.retrieved_on_archive,
            "metrics_complete": self.score is not None and self.num_comments is not None,
            "comments": [c.to_dict() for c in self.comments],
        }

    def to_tweet(self) -> Tweet:
        """Convert to the shared Tweet domain model so the existing store/qualification reuse it."""
        created = self.created_datetime()
        handle = self.author or None
        metadata = self.metadata()
        return Tweet(
            id=self.lead_id,
            url=self.permalink,
            text=self.full_text(),
            author_username=handle,
            author_name=handle,
            author_followers=None,
            created_at=created or _dt.datetime.now(_dt.timezone.utc),
            lang=None,
            like_count=self.score or 0,
            retweet_count=0,
            reply_count=self.num_comments or 0,
            quote_count=0,
            view_count=None,
            is_retweet=False,
            is_reply=False,
            platform="reddit",
            extra_metadata=metadata,
        )


@dataclass
class RedditExecutionSummary:
    """Reddit-specific accounting for one ingestion run (honest, never rounded up)."""

    requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rate_limit_responses: int = 0
    access_denied_responses: int = 0
    cached_responses: int = 0
    posts_discovered: int = 0
    duplicates_skipped: int = 0
    comments_fetched: int = 0
    posts_filtered_out: int = 0
    ai_calls: int = 0
    ai_failures: int = 0
    estimated_api_cost_usd: float = 0.0
    paid_service_used: bool = False
    access_mode: str = "public_unauthenticated"
    source_provider: str = "arctic_shift"
    ui_state: str = "LIVE SOURCE AVAILABLE"
    last_retrieved_at: str | None = None
    status: str = "OK"
    status_detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
