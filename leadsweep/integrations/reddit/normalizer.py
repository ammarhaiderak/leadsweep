"""Turn raw Reddit JSON into normalized records without inventing anything.

Removed/deleted posts are preserved as records but flagged, never silently rewritten into a
plausible-looking post. A missing metric stays missing.
"""
from __future__ import annotations

import logging
from typing import Any

from .exceptions import RedditResponseError
from .models import RedditComment, RedditPost

log = logging.getLogger("leadsweep.integrations.reddit.normalizer")

_REMOVED_MARKERS = {"[removed]", "[deleted]", "[ removed by reddit ]"}
# Reddit marks deleted accounts with these literal placeholders; they are not handles.
_REMOVED_AUTHORS = {"[deleted]", "[removed]", "[ removed by reddit ]"}


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _epoch_to_iso(value: Any) -> str | None:
    from .models import _parse_utc

    parsed = _parse_utc(value)
    return parsed.isoformat() if parsed else None


def normalize_author(raw: Any) -> str | None:
    """Reddit returns ``[deleted]`` for removed accounts; that is not an author."""
    handle = _clean(raw).lstrip("/")
    if handle.startswith("u/"):
        handle = handle[2:]
    if not handle or handle.lower() in _REMOVED_AUTHORS:
        return None
    return handle


def normalize_subreddit(raw: Any) -> str:
    name = _clean(raw).lstrip("/")
    if name.lower().startswith("r/"):
        name = name[2:]
    return name.strip("/")


def normalize_permalink(raw: Any, subreddit: str, post_id: str) -> str:
    path = _clean(raw)
    if not path:
        return f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/"
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return f"https://www.reddit.com{path}"


def is_removed(data: dict[str, Any]) -> bool:
    """Detect removed/deleted posts from the flags Reddit actually returns."""
    if _clean(data.get("removed_by_category")):
        return True
    body = _clean(data.get("selftext")).lower()
    title = _clean(data.get("title")).lower()
    return body in _REMOVED_MARKERS or title in _REMOVED_MARKERS


def normalize_post(child: Any) -> RedditPost:
    """Normalize one ``t3`` listing child into a RedditPost."""
    if not isinstance(child, dict):
        raise RedditResponseError("Reddit listing child is not an object.")
    data = child.get("data")
    if not isinstance(data, dict):
        raise RedditResponseError("Reddit listing child is missing its data object.")

    post_id = _clean(data.get("id")) or _clean(data.get("name")).removeprefix("t3_")
    subreddit = normalize_subreddit(data.get("subreddit"))
    title = _clean(data.get("title"))
    if not post_id or not subreddit:
        raise RedditResponseError("Reddit post without an id or subreddit cannot be normalized.")

    return RedditPost(
        post_id=post_id,
        subreddit=subreddit,
        title=title,
        body=_clean(data.get("selftext")),
        author=normalize_author(data.get("author")),
        permalink=normalize_permalink(data.get("permalink"), subreddit, post_id),
        created_at=_epoch_to_iso(data.get("created_utc")) or _clean(data.get("created_utc")) or None,
        score=_as_int(data.get("score")),
        upvote_ratio=_as_float(data.get("upvote_ratio")),
        num_comments=_as_int(data.get("num_comments")),
        external_url=_clean(data.get("url_overridden_by_dest")) or _clean(data.get("url")) or None,
        over_18=bool(data.get("over_18")),
        locked=bool(data.get("locked")),
        removed=is_removed(data),
        retrieved_on_archive=_as_int(data.get("retrieved_on")),
    )


def normalize_comment(child: Any, parent_post_id: str) -> RedditComment | None:
    """Normalize one ``t1`` comment child. Non-comment placeholders yield None."""
    if not isinstance(child, dict) or child.get("kind") != "t1":
        return None
    data = child.get("data")
    if not isinstance(data, dict):
        return None
    comment_id = _clean(data.get("id"))
    body = _clean(data.get("body"))
    if not comment_id or not body or body in _REMOVED_MARKERS:
        return None
    permalink = _clean(data.get("permalink"))
    return RedditComment(
        comment_id=comment_id,
        post_id=parent_post_id,
        author=normalize_author(data.get("author")),
        body=body,
        created_at=_epoch_to_iso(data.get("created_utc")),
        permalink=f"https://www.reddit.com{permalink}" if permalink.startswith("/") else (permalink or None),
        score=_as_int(data.get("score")),
    )


def iter_children(payload: Any) -> list[Any]:
    """Return the children list from a listing payload, or an empty list."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    children = data.get("children")
    return children if isinstance(children, list) else []


def normalize_listing(payload: Any) -> list[RedditPost]:
    """Normalize every post in a listing, skipping malformed children instead of failing the run."""
    posts: list[RedditPost] = []
    for child in iter_children(payload):
        try:
            posts.append(normalize_post(child))
        except RedditResponseError as exc:
            log.debug("Skipping malformed Reddit child: %s", exc)
    return posts
