"""Reddit data client: permitted public endpoints, or local fixture reads.

The client is intentionally small and honest:
* ``public_unauthenticated`` performs plain GETs against Reddit's public JSON endpoints with a
  descriptive User-Agent, one request at a time, paced by the controller. If Reddit refuses
  (403/401), the run stops with ``ACCESS_RESTRICTED``. No proxy rotation, session spoofing,
  cookie replay or retry storming is implemented, and a denial is never retried.
* ``offline_fixtures`` reads locally supplied Reddit JSON (your own permitted exports). Zero
  network, zero credentials, fully deterministic, so discovery and qualification can be tested.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx

from .authentication import (
    DEFAULT_SEARCH_SUBREDDITS,
    OFFLINE_FIXTURES,
    PROVIDER_ARCTIC_SHIFT,
    PUBLIC_UNAUTHENTICATED,
    RedditAccessConfig,
)
from .cache import RedditResponseCache, make_cache_key
from .exceptions import (
    RedditCircuitOpenError,
    RedditConfigError,
    RedditError,
    RedditRateLimitedError,
    RedditResponseError,
    RedditTimeoutError,
    classify_http_status,
)
from .rate_limiter import RedditRequestController

log = logging.getLogger("leadsweep.integrations.reddit.client")

_EXPANSION_SUFFIXES = (
    "looking for recommendation",
    "need help with",
    "anyone know a tool",
)
_STOPWORDS = {"the", "and", "for", "with", "need", "looking", "help", "anyone", "know", "tool", "from", "that", "this"}


class RedditClient:
    """Single entry point for Reddit listing/comment fetches."""

    def __init__(
        self,
        config: RedditAccessConfig,
        *,
        controller: RedditRequestController | None = None,
        cache: RedditResponseCache | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self.controller = controller or RedditRequestController(
            max_requests_per_minute=config.max_requests_per_minute,
            max_concurrent_requests=config.max_concurrent_requests,
            max_retries=config.max_retries,
            circuit_breaker_ttl_s=config.circuit_breaker_ttl_s,
        )
        self.cache = cache or RedditResponseCache(config.cache_ttl_seconds)
        self._http = http_client
        self._owns_http = http_client is None

    # ------------------------------------------------------------------ lifecycle
    async def __aenter__(self) -> "RedditClient":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._http is not None and self._owns_http:
            await self._http.aclose()
            self._http = None

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.request_timeout),
                follow_redirects=False,
                headers={
                    "User-Agent": self.config.user_agent,
                    "Accept": "application/json",
                },
            )
        return self._http

    def _use_arctic_shift(self) -> bool:
        """Use the Arctic Shift public archive API when running live unauthenticated requests."""
        return (
            self.config.mode == PUBLIC_UNAUTHENTICATED
            and self.config.source_provider == PROVIDER_ARCTIC_SHIFT
            and (self._owns_http or "arctic-shift" in self.config.base_url)
        )

    # ------------------------------------------------------------------ public API
    async def fetch_listing(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch a listing payload (search/new/hot) as a dict."""
        if not self.config.enabled:
            raise RedditConfigError("Reddit integration is disabled by configuration.")
        if self.config.mode == OFFLINE_FIXTURES:
            return self._fixture_listing(path, params)
        if self.config.mode != PUBLIC_UNAUTHENTICATED:
            raise RedditConfigError(f"Unsupported Reddit access mode: {self.config.mode}")
        if self._use_arctic_shift():
            return await self._fetch_arctic_shift_listing(path, params)
        payload = await self._get_json(path, params)
        if not isinstance(payload, dict):
            raise RedditResponseError("Reddit returned a non-object listing payload.")
        return payload

    async def fetch_comments(self, post_id: str, *, limit: int = 5) -> list[dict[str, Any]]:
        """Fetch a comment tree for one post (bounded)."""
        if self.config.mode == OFFLINE_FIXTURES:
            return self._fixture_comments(post_id)
        if not self.config.enabled:
            raise RedditConfigError("Reddit integration is disabled by configuration.")
        if self._use_arctic_shift():
            clean_id = str(post_id).removeprefix("t3_")
            payload = await self._get_json(
                "/api/comments/tree",
                {"link_id": f"t3_{clean_id}", "limit": max(1, min(limit, 25))},
            )
            if isinstance(payload, dict) and isinstance(payload.get("data"), list):
                return [c for c in payload["data"] if isinstance(c, dict)]
            return []
        payload = await self._get_json(
            f"/comments/{post_id}.json",
            {"limit": max(1, min(limit, 25)), "depth": 1, "sort": "top", "raw_json": 1},
        )
        if not isinstance(payload, list) or len(payload) < 2:
            return []
        comments_listing = payload[1]
        if not isinstance(comments_listing, dict):
            return []
        data = comments_listing.get("data")
        if not isinstance(data, dict):
            return []
        children = data.get("children")
        return children if isinstance(children, list) else []

    # ------------------------------------------------------------------ Arctic Shift adapter
    async def _fetch_arctic_shift_listing(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """Translate a standard Reddit listing/search path into an Arctic Shift archive query."""
        limit = max(1, min(int(params.get("limit") or 25), 100))
        query = str(params.get("q") or "").strip()
        after = str(params.get("after") or "").strip()

        subreddit: str | None = None
        if path.startswith("/r/"):
            parts = [p for p in path.split("/") if p]
            if len(parts) >= 2:
                subreddit = parts[1]

        subreddits = [subreddit] if subreddit else list(self.config.default_search_subreddits[:5] or DEFAULT_SEARCH_SUBREDDITS[:5])
        fetch_limit = min(max(limit * 2, 75), 100)

        raw_posts: list[dict[str, Any]] = []
        oldest_utc: int | None = None

        for sub in subreddits:
            api_params: dict[str, Any] = {
                "subreddit": sub,
                "sort": "desc",
                "limit": fetch_limit,
            }
            if after.startswith("before_"):
                before_ts = after.removeprefix("before_").strip()
                if before_ts.isdigit():
                    api_params["before"] = int(before_ts)
            elif after.isdigit():
                api_params["before"] = int(after)

            payload = await self._get_json("/api/posts/search", api_params)
            if not isinstance(payload, dict):
                raise RedditResponseError("Arctic Shift returned a non-object listing payload.")
            data_list = payload.get("data")
            if not isinstance(data_list, list):
                raise RedditResponseError("Arctic Shift listing payload is missing its data list.")

            for item in data_list:
                if isinstance(item, dict):
                    raw_posts.append(item)
                    c_utc = item.get("created_utc")
                    if isinstance(c_utc, (int, float)):
                        ts = int(c_utc)
                        if oldest_utc is None or ts < oldest_utc:
                            oldest_utc = ts

        children = self._filter_arctic_shift_posts(raw_posts, query)
        next_after: str | None = None
        if oldest_utc is not None and len(raw_posts) >= fetch_limit:
            next_after = f"before_{max(1, oldest_utc - 1)}"

        return {
            "kind": "Listing",
            "data": {
                "children": children[:limit],
                "after": next_after,
            },
        }

    @staticmethod
    def _filter_arctic_shift_posts(raw_posts: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
        """Filter and rank raw Arctic Shift post objects into ``t3`` listing children."""
        cleaned_query = (query or "").strip().lower()
        for suffix in _EXPANSION_SUFFIXES:
            if cleaned_query.endswith(suffix):
                cleaned_query = cleaned_query[: -len(suffix)].strip()

        raw_tokens = [t for t in re.split(r"[^a-z0-9_+#.-]+", cleaned_query) if len(t) >= 2]
        core_tokens = [t for t in raw_tokens if t not in _STOPWORDS] or raw_tokens

        scored: list[tuple[int, int, dict[str, Any]]] = []
        for idx, post in enumerate(raw_posts):
            if not isinstance(post, dict):
                continue
            child = {"kind": "t3", "data": post} if "data" not in post else post
            data = child.get("data") if isinstance(child, dict) else None
            if not isinstance(data, dict):
                continue
            if not core_tokens:
                scored.append((1, -idx, child))
                continue
            haystack = f"{data.get('title', '')} {data.get('selftext', '')}".lower()
            matches = sum(1 for tok in core_tokens if tok in haystack)
            scored.append((matches, -idx, child))

        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in scored]

    # ------------------------------------------------------------------ internals
    async def _get_json(self, path: str, params: dict[str, Any]) -> Any:
        cache_key = make_cache_key("GET", path, params)
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        base = (
            self.config.archive_base_url
            if (path.startswith("/api/") and self._owns_http and "arctic-shift" not in self.config.base_url)
            else self.config.base_url
        )
        url = f"{base}{path}"
        attempt = 0
        last_error: RedditError | None = None

        while attempt <= self.config.max_retries:
            attempt += 1
            self.controller.assert_available()
            await self.controller.acquire()
            try:
                await self.controller.wait_turn()
                self.controller.requests += 1
                client = await self._client()
                response = await client.get(url, params=params)
            except httpx.TimeoutException as exc:
                self.controller.record_failure()
                last_error = RedditTimeoutError(f"Reddit request timed out: {type(exc).__name__}")
                if attempt <= self.config.max_retries:
                    self.controller.retries += 1
                    await self._sleep(self.controller.backoff_delay(attempt))
                    continue
                raise last_error from exc
            except httpx.HTTPError as exc:
                self.controller.record_failure()
                last_error = RedditTimeoutError(f"Reddit network failure: {type(exc).__name__}")
                if attempt <= self.config.max_retries:
                    self.controller.retries += 1
                    await self._sleep(self.controller.backoff_delay(attempt))
                    continue
                raise last_error from exc
            finally:
                self.controller.release()

            status = response.status_code
            if status == 200:
                try:
                    payload = response.json()
                except (ValueError, json.JSONDecodeError) as exc:
                    self.controller.record_failure()
                    raise RedditResponseError("Reddit returned invalid JSON.") from exc
                self.controller.record_success()
                self.cache.set(cache_key, payload)
                return payload

            retry_after: float | None = None
            header = response.headers.get("Retry-After") or response.headers.get("X-RateLimit-Reset")
            if header:
                try:
                    retry_after = float(header)
                except ValueError:
                    retry_after = None

            if status == 422 and path.startswith("/api/"):
                error: RedditError = RedditRateLimitedError(
                    "Arctic Shift archive query timed out under load (HTTP 422).",
                    retry_after_s=retry_after,
                )
            else:
                error = classify_http_status(status, retry_after=retry_after)

            if error.status_code in ("ACCESS_RESTRICTED", "AUTH_REQUIRED"):
                self.controller.record_denial(error.message)
                raise error

            if error.status_code == "RATE_LIMITED":
                self.controller.record_rate_limit()
                if attempt <= self.config.max_retries:
                    self.controller.retries += 1
                    await self._sleep(self.controller.backoff_delay(attempt, retry_after))
                    continue
                raise error

            if error.retryable:
                self.controller.record_failure()
                if attempt <= self.config.max_retries:
                    self.controller.retries += 1
                    await self._sleep(self.controller.backoff_delay(attempt))
                    continue
                raise error

            # 404 and any other non-retryable response: report as-is.
            raise error

        raise last_error or RedditResponseError("Reddit request failed without a response.")

    @staticmethod
    async def _sleep(seconds: float) -> None:
        if seconds <= 0:
            return
        import asyncio

        await asyncio.sleep(seconds)

    # ------------------------------------------------------------------ fixtures
    def _fixture_files(self) -> list[Path]:
        directory = self.config.fixture_dir
        if not directory.exists() or not directory.is_dir():
            return []
        return sorted(p for p in directory.glob("*.json") if p.is_file())

    def _load_fixture_children(self) -> list[dict[str, Any]]:
        children: list[dict[str, Any]] = []
        for path in self._fixture_files():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                log.warning("Skipping unreadable Reddit fixture %s: %s", path.name, exc)
                continue
            children.extend(_fixture_children_from_payload(payload))
        return children

    def _fixture_listing(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._fixture_files():
            raise RedditConfigError(
                f"No Reddit fixtures found in {self.config.fixture_dir}. "
                "Add your own permitted Reddit JSON exports (*.json) to run offline."
            )
        query = str(params.get("q") or "").lower().strip()
        subreddit_hint = ""
        if path.startswith("/r/"):
            subreddit_hint = path.split("/")[2] if len(path.split("/")) > 2 else ""

        matched: list[dict[str, Any]] = []
        for child in self._load_fixture_children():
            data = child.get("data") if isinstance(child, dict) else None
            if not isinstance(data, dict):
                continue
            if subreddit_hint and str(data.get("subreddit", "")).lower() != subreddit_hint.lower():
                continue
            if query:
                haystack = f"{data.get('title', '')} {data.get('selftext', '')}".lower()
                terms = [t for t in query.replace('"', " ").split() if len(t) > 2]
                if terms and not any(term in haystack for term in terms):
                    continue
            matched.append(child)

        limit = int(params.get("limit") or 25)
        return {"kind": "Listing", "data": {"children": matched[:limit], "after": None}}

    def _fixture_comments(self, post_id: str) -> list[dict[str, Any]]:
        for path in self._fixture_files():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            for child in _fixture_children_from_payload(payload):
                data = child.get("data") if isinstance(child, dict) else None
                if not isinstance(data, dict) or str(data.get("id")) != str(post_id):
                    continue
                raw_comments = data.get("comments")
                if isinstance(raw_comments, list):
                    return raw_comments
        return []


def _fixture_children_from_payload(payload: Any) -> list[dict[str, Any]]:
    """Accept both a bare listing payload and a bare list of post objects."""
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("children"), list):
            return [c for c in data["children"] if isinstance(c, dict)]
        return []
    if isinstance(payload, list):
        out: list[dict[str, Any]] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            if "data" in entry and isinstance(entry.get("data"), dict):
                out.append(entry)
            else:
                out.append({"kind": "t3", "data": entry})
        return out
    return []


__all__ = ["RedditClient", "RedditCircuitOpenError"]
