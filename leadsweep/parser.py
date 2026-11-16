"""Pure functions: raw SearchTimeline GraphQL JSON -> Tweet models.

Deliberately defensive: X moves fields around (e.g. screen_name migrated from
user.legacy to user.core). Every access has a fallback and never raises on shape drift.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from .models import Tweet, XUser


def _dig(obj: Any, *path: str | int, default: Any = None) -> Any:
    cur = obj
    for key in path:
        try:
            cur = cur[key]
        except (KeyError, IndexError, TypeError):
            return default
    return cur if cur is not None else default


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")
    except ValueError:
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None


def _find_key(node: Any, keys: tuple[str, ...], depth: int = 0) -> Any:
    if depth > 5:
        return None
    if isinstance(node, dict):
        for k in keys:
            if k in node and not isinstance(node[k], (dict, list)):
                return node[k]
        for v in node.values():
            found = _find_key(v, keys, depth + 1)
            if found is not None:
                return found
    elif isinstance(node, list):
        for v in node:
            found = _find_key(v, keys, depth + 1)
            if found is not None:
                return found
    return None


def _followers(user: Any) -> int | None:
    """X moved follower counts around (legacy.followers_count -> relationship_counts.followers ...); try them all."""
    for path in (("legacy", "followers_count"), ("relationship_counts", "followers"), ("core", "followers_count")):
        v = _to_int(_dig(user, *path))
        if v is not None:
            return v
    return _to_int(_find_key(user, ("followers_count", "normal_followers_count")))


def _unwrap(result: Any) -> dict | None:
    if not isinstance(result, dict):
        return None
    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet") or {}
    if result.get("__typename") == "TweetTombstone" or not result.get("legacy"):
        return None
    return result


def parse_tweet_result(result: Any) -> Tweet | None:
    outer = _unwrap(result)
    if outer is None:
        return None

    rt = _unwrap(_dig(outer, "legacy", "retweeted_status_result", "result"))
    base = rt or outer
    legacy = base["legacy"]

    tweet_id = base.get("rest_id") or legacy.get("id_str")
    if not tweet_id:
        return None

    user = _dig(base, "core", "user_results", "result", default={})
    username = _dig(user, "core", "screen_name") or _dig(user, "legacy", "screen_name")
    name = _dig(user, "core", "name") or _dig(user, "legacy", "name")
    followers = _followers(user)  # UPDATED LOGIC (P3.1)

    # UPDATED LOGIC: Full-text extraction (note_tweet, quoted tweets, card/link previews, alt text)
    full_text = _dig(base, "note_tweet", "note_tweet_results", "result", "text") or legacy.get("full_text", "")
    
    # Quoted tweet text if available
    quoted = _unwrap(_dig(base, "quoted_status_result", "result"))
    if quoted:
        quoted_legacy = quoted.get("legacy", {})
        quoted_text = _dig(quoted, "note_tweet", "note_tweet_results", "result", "text") or quoted_legacy.get("full_text", "")
        if quoted_text:
            quoted_user = _dig(quoted, "core", "user_results", "result", "legacy", "screen_name") or "quoted"
            full_text = f"{full_text}\n\n[Quoted @{quoted_user}]: {quoted_text}".strip()

    # Card / link preview title or description if tweet body is essentially empty or just a link
    card = base.get("card", {})
    card_bindings = _dig(card, "legacy", "binding_values", default=[])
    card_title = ""
    card_desc = ""
    if isinstance(card_bindings, list):
        for b in card_bindings:
            if isinstance(b, dict):
                k = b.get("key")
                v = _dig(b, "value", "string_value", default="")
                if k == "title":
                    card_title = v
                elif k == "description":
                    card_desc = v
    if card_title or card_desc:
        card_summary = f"{card_title}: {card_desc}".strip(": ")
        if card_summary and card_summary not in full_text:
            full_text = f"{full_text}\n\n[Link Preview]: {card_summary}".strip()

    # Media alt text
    media_list = _dig(legacy, "extended_entities", "media", default=[]) or _dig(legacy, "entities", "media", default=[])
    if isinstance(media_list, list):
        alt_texts = [m.get("ext_alt_text") for m in media_list if isinstance(m, dict) and m.get("ext_alt_text")]
        if alt_texts:
            full_text = f"{full_text}\n\n[Media Alt]: {', '.join(alt_texts)}".strip()

    # Link-only check: if text consists only of t.co links with no actual content, mark NO_TEXT
    import re
    cleaned_of_urls = re.sub(r"https?://t\.co/[a-zA-Z0-9]+", "", full_text).strip()
    if not cleaned_of_urls or len(cleaned_of_urls) < 3:
        full_text = "NO_TEXT"

    return Tweet(
        id=str(tweet_id),
        url=f"https://x.com/{username}/status/{tweet_id}" if username else f"https://x.com/i/status/{tweet_id}",
        text=full_text,
        author_username=username,
        author_name=name,
        author_followers=followers,
        created_at=(
            _parse_dt(legacy.get("created_at"))
            or (
                datetime.fromtimestamp(((int(tweet_id) >> 22) + 1288834974657) / 1000.0, tz=timezone.utc)
                if str(tweet_id).isdigit()
                else None
            )
        ),
        lang=legacy.get("lang"),
        like_count=_to_int(legacy.get("favorite_count")) or 0,
        retweet_count=_to_int(legacy.get("retweet_count")) or 0,
        reply_count=_to_int(legacy.get("reply_count")) or 0,
        quote_count=_to_int(legacy.get("quote_count")) or 0,
        view_count=_to_int(_dig(base, "views", "count")),
        is_retweet=rt is not None,
        is_reply=bool(legacy.get("in_reply_to_status_id_str")),
    )


def parse_search_timeline(payload: dict) -> tuple[list[Tweet], str | None]:
    """Return (tweets, bottom_cursor) from one SearchTimeline response body."""
    instructions = _dig(
        payload, "data", "search_by_raw_query", "search_timeline", "timeline", "instructions", default=[]
    )
    tweets: list[Tweet] = []
    cursor: str | None = None

    for ins in instructions:
        if not isinstance(ins, dict):
            continue
        entries = ins.get("entries") or ([ins["entry"]] if isinstance(ins.get("entry"), dict) else [])
        for entry in entries:
            entry_id = entry.get("entryId", "")
            content = entry.get("content", {})
            if entry_id.startswith("cursor-bottom"):
                cursor = content.get("value") or cursor
            elif entry_id.startswith("tweet-"):
                tweet = parse_tweet_result(_dig(content, "itemContent", "tweet_results", "result"))
                if tweet:
                    tweets.append(tweet)
    return tweets, cursor


# ======================================================================================
# NEW FEATURE (Phase 2): profile timeline (UserTweets) + user lookup (UserByScreenName)
# ======================================================================================
def user_exists(payload: dict) -> bool:
    """True if a UserByScreenName response contains a real user."""
    return bool(_dig(payload, "data", "user", "result", "rest_id"))


def _walk_for_instructions(node: Any, depth: int = 0) -> list:
    """UPDATED LOGIC (P2.1): find the timeline 'instructions' list wherever X put it."""
    if depth > 8:
        return []
    if isinstance(node, dict):
        ins = node.get("instructions")
        if isinstance(ins, list):
            return ins
        children: Any = node.values()
    elif isinstance(node, list):
        children = node
    else:
        return []
    for child in children:
        found = _walk_for_instructions(child, depth + 1)
        if found:
            return found
    return []


def _walk_tweet_results(node: Any, out: list, depth: int = 0) -> None:
    """Collect every tweet_results.result in document order (does not descend into a tweet)."""
    if depth > 14:
        return
    if isinstance(node, dict):
        tr = node.get("tweet_results")
        if isinstance(tr, dict) and isinstance(tr.get("result"), dict):
            out.append(tr["result"])
            return
        for v in node.values():
            _walk_tweet_results(v, out, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _walk_tweet_results(v, out, depth + 1)


def parse_user_tweets(payload: dict) -> tuple[list[Tweet], str | None]:
    """Return (tweets, bottom_cursor) from one profile-feed response (UserTweets / UserOriginalsTimeline).

    Shape-tolerant: does not depend on timeline key names or tweet entryId prefixes.
    """
    root = _dig(payload, "data", "user", "result", default=None) or payload
    tweets: list[Tweet] = []
    cursor: str | None = None
    for ins in _walk_for_instructions(root):
        if not isinstance(ins, dict):
            continue
        is_pin_ins = ins.get("type") in ("TimelinePinEntry", "TimelineTimelinePinEntry") or "pin" in str(ins.get("type", "")).lower()
        entries = ins.get("entries") or ([ins["entry"]] if isinstance(ins.get("entry"), dict) else [])  # entry = pinned tweet
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("entryId", "")
            content = entry.get("content", {})
            if entry_id.startswith("cursor-bottom"):
                cursor = _dig(content, "value") or cursor
            elif entry_id.startswith(("cursor-", "promoted")):
                continue
            else:
                is_pinned = is_pin_ins or "pinned" in entry_id.lower() or entry.get("type") in ("TimelinePinEntry", "TimelineTimelinePinEntry")
                found: list = []
                _walk_tweet_results(content, found)
                for res in found:
                    t = parse_tweet_result(res)
                    if t:
                        if is_pinned:
                            t.is_pinned = True
                        tweets.append(t)
    return tweets, cursor


# ======================================================================================
# Follower Intelligence (Phase 6 / Stage 1): parse X users & follower timeline
# ======================================================================================
def parse_user_profile(result: Any) -> XUser | None:
    """Extract an XUser model from any user_results.result / user node."""
    if not isinstance(result, dict):
        return None
    # If wrapped in UserWithVisibilityResults or similar
    if result.get("__typename") in ("UserUnavailable", "UserTombstone"):
        return None
    if "user" in result and isinstance(result["user"], dict):
        result = result["user"]

    rest_id = result.get("rest_id") or result.get("id")
    legacy = result.get("legacy") or {}
    core = result.get("core") or {}

    handle = (
        _dig(core, "screen_name")
        or _dig(legacy, "screen_name")
        or result.get("screen_name")
        or _find_key(result, ("screen_name",))
    )
    if not rest_id or not handle:
        return None

    name = (
        _dig(core, "name")
        or _dig(legacy, "name")
        or result.get("name")
        or _find_key(result, ("name",))
    )
    bio = (
        _dig(legacy, "description")
        or _dig(result, "description")
        or _find_key(result, ("description", "bio"))
    )
    location = (
        _dig(legacy, "location")
        or _dig(result, "location")
        or _find_key(result, ("location",))
    )

    # URL / website: may be in legacy.entities.url.urls[0].expanded_url
    website = (
        _dig(legacy, "entities", "url", "urls", 0, "expanded_url")
        or _dig(legacy, "url")
        or _dig(result, "url")
    )

    followers_cnt = _followers(result)
    following_cnt = (
        _to_int(_dig(legacy, "friends_count"))
        or _to_int(_dig(result, "relationship_counts", "following"))
        or _to_int(_find_key(result, ("friends_count", "following_count")))
    )
    tweets_cnt = (
        _to_int(_dig(legacy, "statuses_count"))
        or _to_int(_find_key(result, ("statuses_count", "media_count")))
    )
    listed_cnt = (
        _to_int(_dig(legacy, "listed_count"))
        or _to_int(_find_key(result, ("listed_count",)))
    )

    created_at_str = legacy.get("created_at") or result.get("created_at")
    created_dt = _parse_dt(created_at_str)

    is_blue = bool(
        result.get("is_blue_verified")
        or legacy.get("verified")
        or _dig(result, "verification_info", "is_identity_verified")
    )
    verified_type = (
        _dig(result, "verification_info", "reason", "description", "text")
        or legacy.get("verified_type")
        or ("blue" if is_blue else None)
    )
    protected = bool(legacy.get("protected") or result.get("protected"))
    avatar_url = (
        _dig(legacy, "profile_image_url_https")
        or _dig(result, "avatar", "image_url")
        or _find_key(result, ("profile_image_url_https", "avatar_url"))
    )

    prof_cat = (
        _dig(result, "professional", "category", 0, "name")
        or _dig(result, "professional", "professional_type")
    )

    # Content hash over bio + name + location to detect profile changes over time
    hash_str = f"{name or ''}|{bio or ''}|{location or ''}|{website or ''}"
    content_hash = hashlib.sha256(hash_str.encode("utf-8")).hexdigest()

    return XUser(
        rest_id=str(rest_id),
        handle=str(handle),
        name=str(name) if name else None,
        bio=str(bio) if bio else None,
        location=str(location) if location else None,
        website=str(website) if website else None,
        followers_count=followers_cnt,
        following_count=following_cnt,
        tweets_count=tweets_cnt,
        listed_count=listed_cnt,
        created_at=created_dt,
        is_blue_verified=is_blue,
        verified_type=verified_type,
        protected=protected,
        avatar_url=avatar_url,
        professional_category=prof_cat,
        content_hash=content_hash,
    )


def _walk_user_results(node: Any, out: list, depth: int = 0) -> None:
    """Collect every user_results.result or User object in document order."""
    if depth > 14:
        return
    if isinstance(node, dict):
        ur = node.get("user_results")
        if isinstance(ur, dict) and isinstance(ur.get("result"), dict):
            out.append(ur["result"])
            return
        if node.get("__typename") == "User" and (node.get("rest_id") or node.get("id")):
            out.append(node)
            return
        for v in node.values():
            _walk_user_results(v, out, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _walk_user_results(v, out, depth + 1)


def parse_followers_timeline(payload: dict) -> tuple[list[XUser], str | None]:
    """Return (users, bottom_cursor) from a Followers / UserFollowers / FollowersTimeline response.

    Shape-tolerant: handles both user-centric and timeline-centric instructions.
    """
    root = _dig(payload, "data", "user", "result", default=None) or payload
    users: list[XUser] = []
    cursor: str | None = None

    for ins in _walk_for_instructions(root):
        if not isinstance(ins, dict):
            continue
        entries = ins.get("entries") or ([ins["entry"]] if isinstance(ins.get("entry"), dict) else [])
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("entryId", "")
            content = entry.get("content", {})
            if entry_id.startswith("cursor-bottom"):
                cursor = _dig(content, "value") or cursor
            elif entry_id.startswith(("cursor-", "promoted")):
                continue
            else:
                found: list = []
                _walk_user_results(content, found)
                for res in found:
                    u = parse_user_profile(res)
                    if u:
                        users.append(u)

    return users, cursor
