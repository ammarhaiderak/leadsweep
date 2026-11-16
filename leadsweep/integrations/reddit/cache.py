"""Short-lived response cache and post de-duplication registry.

Both are process-local and free. The cache prevents repeated identical Reddit requests inside a
TTL window; the registry guarantees the same post is never ingested twice in a run, across
keywords, subreddits or pagination passes.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any


def make_cache_key(*parts: Any) -> str:
    """Deterministic cache key from request-relevant parts."""
    raw = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class RedditResponseCache:
    """TTL cache for listing payloads."""

    def __init__(self, ttl_seconds: int = 900) -> None:
        self.ttl_seconds = max(0, int(ttl_seconds))
        self._store: dict[str, tuple[float, Any]] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        if self.ttl_seconds <= 0:
            return None
        entry = self._store.get(key)
        if not entry:
            self.misses += 1
            return None
        cached_at, payload = entry
        if time.monotonic() - cached_at > self.ttl_seconds:
            self._store.pop(key, None)
            self.misses += 1
            return None
        self.hits += 1
        return payload

    def set(self, key: str, payload: Any) -> None:
        if self.ttl_seconds <= 0:
            return
        self._store[key] = (time.monotonic(), payload)

    def clear(self) -> None:
        self._store.clear()


class SeenRegistry:
    """Tracks already-ingested identifiers for one run."""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self.duplicates = 0

    def first_seen(self, item_id: str) -> bool:
        """True when this id is new; False (and counted) when it is a duplicate."""
        if not item_id:
            return False
        if item_id in self._seen:
            self.duplicates += 1
            return False
        self._seen.add(item_id)
        return True

    def __len__(self) -> int:
        return len(self._seen)
