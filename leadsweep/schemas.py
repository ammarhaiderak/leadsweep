"""Structured MCP output contracts (Pydantic). Tools ALWAYS return these, never raw exceptions."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .models import Tweet, XUser

ErrorCode = Literal[
    "INVALID_INPUT",
    "SESSION_EXPIRED",
    "RATE_LIMITED",
    "NO_SESSION_AVAILABLE",
    "ENDPOINT_CHANGED",
    "USER_NOT_FOUND",
    "INTERNAL",
]


class ErrorInfo(BaseModel):
    code: ErrorCode
    message: str
    retryable: bool
    retry_after_s: int | None = None
    hint: str | None = None


class SearchResponse(BaseModel):
    ok: bool
    query: str
    count: int
    tweets: list[Tweet] = Field(default_factory=list)
    error: ErrorInfo | None = None
    elapsed_s: float = 0.0


class ProfileResponse(BaseModel):
    ok: bool
    username: str
    count: int
    tweets: list[Tweet] = Field(default_factory=list)
    error: ErrorInfo | None = None
    elapsed_s: float = 0.0


class FollowersResponse(BaseModel):
    ok: bool
    username: str
    count: int
    users: list[XUser] = Field(default_factory=list)
    error: ErrorInfo | None = None
    elapsed_s: float = 0.0


class SessionInfo(BaseModel):
    id: str
    dead: bool
    cooldown_s: int
    reason: str = ""


class SessionStatusResponse(BaseModel):
    ok: bool = True
    sessions: list[SessionInfo]
