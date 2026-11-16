"""Subreddit discovery: recent posts from specific public subreddits."""
from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from .client import RedditClient
from .models import RedditPost
from .normalizer import normalize_listing
from .pagination import build_listing_params, extract_after

log = logging.getLogger("leadsweep.integrations.reddit.subreddit")

ALLOWED_SORTS = {"new", "hot", "top", "rising"}

_SUBREDDIT_RE = re.compile(r"^[A-Za-z0-9_]{2,21}$")


def normalize_subreddit_target(raw: str) -> str | None:
    """Accept ``r/name``, ``/r/name``, a reddit URL, or a bare name."""
    text = (raw or "").strip()
    if not text:
        return None
    match = re.search(r"reddit\.com/r/([A-Za-z0-9_]{2,21})", text, re.IGNORECASE)
    if match:
        return match.group(1)
    text = text.lstrip("/")
    if text.lower().startswith("r/"):
        text = text[2:]
    text = text.strip("/")
    return text if _SUBREDDIT_RE.match(text) else None


def parse_subreddit_list(raw: str | list[str] | None) -> list[str]:
    """Parse a comma/space separated subreddit list, dropping invalid entries."""
    if raw is None:
        return []
    entries: list[str] = []
    if isinstance(raw, str):
        entries = [p for p in re.split(r"[,\s]+", raw) if p]
    else:
        for item in raw:
            entries.extend([p for p in re.split(r"[,\s]+", str(item)) if p])
    out: list[str] = []
    for entry in entries:
        name = normalize_subreddit_target(entry)
        if name and name.lower() not in {e.lower() for e in out}:
            out.append(name)
    return out


async def subreddit_posts(
    client: RedditClient,
    *,
    subreddit: str,
    sort: str = "new",
    limit: int = 25,
    max_pages: int = 2,
    time_filter: str | None = None,
) -> AsyncIterator[RedditPost]:
    """Yield recent public posts from one subreddit."""
    name = normalize_subreddit_target(subreddit)
    if not name:
        log.info("Skipping invalid subreddit target: %r", subreddit)
        return
    effective_sort = sort if sort in ALLOWED_SORTS else "new"
    after: str | None = None
    for _page in range(max(1, max_pages)):
        params = build_listing_params(
            sort=effective_sort,
            time_filter=time_filter if effective_sort == "top" else None,
            limit=limit,
            after=after,
        )
        payload = await client.fetch_listing(f"/r/{name}/{effective_sort}.json", params)
        for post in normalize_listing(payload):
            yield post
        after = extract_after(payload)
        if not after:
            break
