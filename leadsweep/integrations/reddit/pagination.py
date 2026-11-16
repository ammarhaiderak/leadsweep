"""Cursor pagination helpers for Reddit listings.

Bounded page counts and conservative page sizes keep request volume predictable. Nothing here
pages forever: callers get an explicit stop condition.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MAX_PAGE_SIZE = 100


@dataclass(slots=True)
class ListingCursor:
    """Reddit's opaque ``after`` fullname cursor."""

    after: str | None = None

    def next_cursor(self) -> "ListingCursor":
        return ListingCursor(after=self.after)

    def is_empty(self) -> bool:
        return not self.after


def clamp_page_size(requested: int | None, default: int = 25, maximum: int = MAX_PAGE_SIZE) -> int:
    try:
        value = int(requested if requested is not None else default)
    except (TypeError, ValueError):
        value = default
    return max(1, min(maximum, value))


def build_listing_params(
    *,
    query: str | None = None,
    sort: str | None = None,
    time_filter: str | None = None,
    limit: int = 25,
    after: str | None = None,
    restrict_to_subreddit: bool = False,
    raw_json: bool = True,
) -> dict[str, Any]:
    """Build query parameters shared by search and listing endpoints."""
    params: dict[str, Any] = {"limit": clamp_page_size(limit)}
    if raw_json:
        params["raw_json"] = 1
    if query:
        params["q"] = query
        params["type"] = "link"
    if sort:
        params["sort"] = sort
    if time_filter:
        params["t"] = time_filter
    if after:
        params["after"] = after
    if restrict_to_subreddit and query:
        params["restrict_sr"] = 1
    return params


def extract_after(payload: dict[str, Any] | None) -> str | None:
    """Read the next-page cursor from a listing payload."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    after = data.get("after")
    return str(after) if after else None
