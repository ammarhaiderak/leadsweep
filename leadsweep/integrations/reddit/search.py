"""Keyword discovery across Reddit search listings."""
from __future__ import annotations

import logging
from typing import AsyncIterator

from .client import RedditClient
from .models import RedditPost
from .normalizer import normalize_listing
from .pagination import build_listing_params, extract_after

log = logging.getLogger("leadsweep.integrations.reddit.search")


async def keyword_search(
    client: RedditClient,
    *,
    term: str,
    subreddits: list[str] | None = None,
    sort: str = "new",
    time_filter: str | None = None,
    limit: int = 25,
    max_pages: int = 2,
) -> AsyncIterator[RedditPost]:
    """Yield posts matching one term, optionally restricted to specific subreddits."""
    clean_term = (term or "").strip()
    if not clean_term:
        return

    targets: list[str | None] = list(subreddits or []) or [None]
    for subreddit in targets:
        path = f"/r/{subreddit}/search.json" if subreddit else "/search.json"
        after: str | None = None
        for _page in range(max(1, max_pages)):
            params = build_listing_params(
                query=clean_term,
                sort=sort,
                time_filter=time_filter,
                limit=limit,
                after=after,
                restrict_to_subreddit=bool(subreddit),
            )
            payload = await client.fetch_listing(path, params)
            posts = normalize_listing(payload)
            for post in posts:
                yield post
            after = extract_after(payload)
            if not after:
                break
