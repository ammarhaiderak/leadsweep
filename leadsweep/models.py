from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class Tweet(BaseModel):
    id: str
    url: str
    text: str
    author_username: str | None = None
    author_name: str | None = None
    author_followers: int | None = None
    created_at: datetime | None = None
    lang: str | None = None
    like_count: int = 0
    retweet_count: int = 0
    reply_count: int = 0
    quote_count: int = 0
    view_count: int | None = None
    is_retweet: bool = False
    is_reply: bool = False
    is_pinned: bool = False
    platform: str = "twitter"
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # NEW FEATURE: Platform-specific metadata (e.g. Reddit subreddit/title/permalink) kept out
    # of shared lead fields. Optional so every existing X/Telegram item is unchanged.
    extra_metadata: dict[str, Any] | None = None


class XUser(BaseModel):
    rest_id: str
    handle: str
    name: str | None = None
    bio: str | None = None
    location: str | None = None
    website: str | None = None
    followers_count: int | None = None
    following_count: int | None = None
    tweets_count: int | None = None
    listed_count: int | None = None
    created_at: datetime | None = None
    is_blue_verified: bool = False
    verified_type: str | None = None
    protected: bool = False
    avatar_url: str | None = None
    professional_category: str | None = None
    first_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    content_hash: str | None = None

