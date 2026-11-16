"""Target grammar parser for Twitter/X URLs, handles, and search queries."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_STATUS_URL_RE = re.compile(r"(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/(?:i/web/status|[^/]+/status)/(\d+)", re.IGNORECASE)

RESERVED_PATHS = {
    "home",
    "explore",
    "search",
    "i",
    "settings",
    "intent",
    "notifications",
    "messages",
    "tos",
    "privacy",
    "help",
    "about",
    "login",
    "logout",
    "signup",
    "account",
    "download",
}


@dataclass
class XTarget:
    kind: str  # "profile", "search", "status", "invalid"
    handle: str | None = None
    with_replies: bool = False
    status_id: str | None = None
    query: str = ""
    error: str | None = None


def parse_x_target(raw_input: str, wizard_type: str = "search") -> XTarget:
    """Parse a user input string into an XTarget according to H2-1 Target Grammar.
    
    Rules:
    - https://x.com/<handle>, twitter.com/<handle>, @handle, optional /with_replies
    - handle regex 1-15 chars [A-Za-z0-9_]
    - reject reserved paths (home, explore, search, i, settings, intent...)
    - /status/<id> URLs -> status actor or clear message
    - Plain words stay SEARCH unless wizard_type == 'profile' or 'timeline'
    - Search behavior unchanged
    """
    clean = (raw_input or "").strip()
    if not clean:
        return XTarget(kind="search", query="")

    # 1. Check for /status/<id> URLs first
    status_match = _STATUS_URL_RE.search(clean)
    if status_match:
        status_id = status_match.group(1)
        return XTarget(
            kind="status",
            status_id=status_id,
            query=clean,
            error=f"Tweet status URLs (status ID: {status_id}) must be scraped using the Tweet Replies scraper",
        )

    # 2. Check for URLs: https://x.com/<handle>, twitter.com/<handle>, etc.
    candidate = clean
    is_url = False
    if "://" in candidate or candidate.startswith(("x.com/", "twitter.com/", "www.x.com/", "www.twitter.com/")):
        is_url = True
        if not candidate.startswith(("http://", "https://")):
            candidate = f"https://{candidate}"
        try:
            parsed = urlparse(candidate)
            hostname = (parsed.hostname or "").lower()
            if hostname in ("x.com", "twitter.com", "www.x.com", "www.twitter.com"):
                path_parts = [p for p in parsed.path.strip("/").split("/") if p]
                if not path_parts:
                    return XTarget(kind="invalid", error="X URL missing profile handle", query=clean)
                
                handle_cand = path_parts[0]
                with_replies = len(path_parts) > 1 and path_parts[1].lower() == "with_replies"

                if handle_cand.lower() in RESERVED_PATHS:
                    return XTarget(
                        kind="invalid",
                        error=f"Path '/{handle_cand}' is a reserved X system route, not a user profile",
                        query=clean,
                    )
                
                if not _HANDLE_RE.fullmatch(handle_cand):
                    return XTarget(
                        kind="invalid",
                        error=f"Invalid Twitter/X handle '{handle_cand}' (must be 1-15 alphanumeric characters or underscore)",
                        query=clean,
                    )

                return XTarget(kind="profile", handle=handle_cand, with_replies=with_replies, query=clean)
            else:
                # URL from another domain stays search unless invalid
                return XTarget(kind="search", query=clean)
        except Exception:
            return XTarget(kind="search", query=clean)

    # 3. Check for @handle format: e.g. "@nextjs", "@nextjs/with_replies"
    if clean.startswith("@"):
        part = clean[1:].strip()
        with_replies = False
        if "/" in part:
            parts = part.split("/", 1)
            part = parts[0]
            with_replies = parts[1].lower().rstrip("/") == "with_replies"
        
        if part.lower() in RESERVED_PATHS:
            return XTarget(kind="invalid", error=f"Reserved route '@{part}' is not a valid user profile", query=clean)
        if not _HANDLE_RE.fullmatch(part):
            return XTarget(kind="invalid", error=f"Invalid Twitter/X handle '@{part}'", query=clean)
        return XTarget(kind="profile", handle=part, with_replies=with_replies, query=clean)

    # 4. Check for path with /with_replies without protocol: e.g. "nextjs/with_replies"
    if "/" in clean and not any(c in clean for c in (" ", "\t", "\n")):
        parts = clean.split("/", 1)
        if parts[1].lower().rstrip("/") == "with_replies" and _HANDLE_RE.fullmatch(parts[0]):
            handle_cand = parts[0]
            if handle_cand.lower() in RESERVED_PATHS:
                return XTarget(kind="invalid", error=f"Reserved route '{handle_cand}' is not a valid user profile", query=clean)
            return XTarget(kind="profile", handle=handle_cand, with_replies=True, query=clean)

    # 5. Plain words:
    # If wizard_type is explicitly 'profile' or 'timeline':
    if wizard_type in ("profile", "timeline"):
        if _HANDLE_RE.fullmatch(clean):
            if clean.lower() in RESERVED_PATHS:
                return XTarget(kind="invalid", error=f"Reserved route '{clean}' is not a valid user profile", query=clean)
            return XTarget(kind="profile", handle=clean, with_replies=False, query=clean)
        return XTarget(kind="invalid", error=f"Invalid Twitter/X handle '{clean}' (must be 1-15 letters/digits/underscore)", query=clean)

    # Otherwise plain words STAY SEARCH
    return XTarget(kind="search", query=clean)
