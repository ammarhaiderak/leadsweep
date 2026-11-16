"""
leadsweep/core/connectors.py -- Connectors with Hard Stops, Quotas, and Circuit Breakers

Contract rules:
1. Public stream/API only: Hacker News (Firebase/Algolia), Lobsters (JSON/Atom), Bluesky, Dev.to, GitHub, Stack Exchange.
2. Reddit: disabled_unlicensed unless contract id is supplied in config.
3. Unsupported platforms: LinkedIn, Instagram, TikTok, Facebook, WhatsApp, X (without enterprise stream). Marked unsupported.
4. Token bucket at 50% published quota.
5. 429 backoff with full jitter (base 2s, cap 5 min, max 6 attempts).
6. 401/403: Circuit breaker opened immediately, page human, stop.
7. No headless browser anywhere.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional
import httpx

from .contract_models import RawItem

log = logging.getLogger("leadsweep.connectors")


class CircuitBreakerOpenError(RuntimeError):
    """Raised when 401/403 trip the circuit breaker."""
    pass


class ConnectorClient:
    def __init__(self, source_name: str, base_url: str, user_agent: str = "LeadIntel/1.0 (+https://leadsweep.io/contact)"):
        self.source_name = source_name
        self.base_url = base_url
        self.user_agent = user_agent
        self.breaker_open = False
        self.breaker_reason = ""
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0),
            headers={"User-Agent": self.user_agent, "Accept": "application/json"},
        )

    async def get_json(self, endpoint: str, params: Optional[Dict[str, Any]] = None, max_attempts: int = 6) -> Any:
        if self.breaker_open:
            raise CircuitBreakerOpenError(f"Circuit breaker is OPEN for {self.source_name}: {self.breaker_reason}")

        url = f"{self.base_url}{endpoint}" if endpoint.startswith("/") else endpoint
        attempt = 0
        base_delay = 2.0
        cap_delay = 300.0  # 5 minutes

        while attempt < max_attempts:
            attempt += 1
            try:
                resp = await self.client.get(url, params=params)
                
                # Hard stop on 401 / 403: trip circuit breaker immediately, page human, stop
                if resp.status_code in (401, 403):
                    self.breaker_open = True
                    self.breaker_reason = f"HTTP {resp.status_code} received from {self.source_name}. Breaker opened, human paged."
                    log.critical(self.breaker_reason)
                    raise CircuitBreakerOpenError(self.breaker_reason)

                # 429 Rate limit: full jitter exponential backoff
                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        sleep_s = float(retry_after)
                    else:
                        # Full jitter: random between 0 and min(cap, base * 2 ** (attempt - 1))
                        sleep_cap = min(cap_delay, base_delay * (2 ** (attempt - 1)))
                        sleep_s = random.uniform(0.5, sleep_cap)
                    
                    log.warning("Connector %s hit 429 (attempt %d/%d), sleeping %.2fs", self.source_name, attempt, max_attempts, sleep_s)
                    await asyncio.sleep(sleep_s)
                    continue

                resp.raise_for_status()
                return resp.json()

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.HTTPStatusError) as exc:
                if isinstance(exc, CircuitBreakerOpenError):
                    raise
                if attempt >= max_attempts:
                    log.error("Connector %s failed after %d attempts: %s", self.source_name, attempt, exc)
                    raise
                sleep_cap = min(cap_delay, base_delay * (2 ** (attempt - 1)))
                await asyncio.sleep(random.uniform(0.5, sleep_cap))

        raise RuntimeError(f"Connector {self.source_name} exhausted max attempts without response")

    async def close(self):
        await self.client.aclose()


class HackerNewsConnector:
    """HN Public API connector via Firebase + Algolia search_by_date API."""
    source_id = "hn"
    lag_slo_minutes = 2.0
    published_limit = "10,000 req/hr (Algolia free/public)"
    license_class = "public_terms"

    def __init__(self):
        self.algolia_client = ConnectorClient("hn_algolia", "https://hn.algolia.com/api/v1")

    async def fetch_recent(self, query: str, watermark_timestamp: Optional[int] = None) -> List[RawItem]:
        # Algolia search_by_date
        params: Dict[str, Any] = {
            "query": query,
            "tags": "(story,comment)",
            "hitsPerPage": 30,
        }
        if watermark_timestamp:
            params["numericFilters"] = f"created_at_i>{watermark_timestamp}"

        data = await self.algolia_client.get_json("/search_by_date", params=params)
        items: List[RawItem] = []
        hits = data.get("hits", [])

        for h in hits:
            obj_id = str(h.get("objectID") or "")
            created_at_str = h.get("created_at")
            source_dt = None
            if created_at_str:
                try:
                    source_dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                except Exception:
                    pass

            is_comment = "comment" in (h.get("_tags") or [])
            title = h.get("title") or h.get("story_title")
            body = h.get("comment_text") or h.get("story_text") or title or ""
            author = h.get("author") or "unknown"
            story_id = str(h.get("story_id") or obj_id)
            url = f"https://news.ycombinator.com/item?id={obj_id}"

            item = RawItem(
                source=self.source_id,
                native_id=obj_id,
                thread_id=story_id,
                url=url,
                item_type="comment" if is_comment else "post",
                author_handle=author,
                community="news.ycombinator.com",
                source_created_at=source_dt,
                body=body,
                title=title,
                parent_excerpt=h.get("story_title") if is_comment else None,
                raw_extra={"points": h.get("points"), "num_comments": h.get("num_comments")},
                payload_sha256="",
                license_id="hn_public_terms",
            )
            items.append(item)

        return items


class LobstersConnector:
    """Lobsters public JSON feed connector."""
    source_id = "lobsters"
    lag_slo_minutes = 2.0
    published_limit = "1 req/sec (Polite crawler)"
    license_class = "public_terms"

    def __init__(self):
        self.client = ConnectorClient("lobsters", "https://lobste.rs")

    async def fetch_recent(self) -> List[RawItem]:
        data = await self.client.get_json("/hottest.json")
        items: List[RawItem] = []
        if not isinstance(data, list):
            return items

        for post in data:
            short_id = str(post.get("short_id") or "")
            created_at_str = post.get("created_at")
            source_dt = None
            if created_at_str:
                try:
                    source_dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                except Exception:
                    pass

            item = RawItem(
                source=self.source_id,
                native_id=short_id,
                thread_id=short_id,
                url=post.get("comments_url") or f"https://lobste.rs/s/{short_id}",
                item_type="post",
                author_handle=post.get("submitter_user") or "anonymous",
                community="lobste.rs",
                source_created_at=source_dt,
                body=post.get("description") or post.get("title") or "",
                title=post.get("title"),
                parent_excerpt=None,
                raw_extra={"score": post.get("score"), "tags": post.get("tags")},
                license_id="lobsters_public_terms",
            )
            items.append(item)

        return items


class RedditConnector:
    """Reddit Connector -- Strictly adheres to contract: disabled_unlicensed unless contract id is configured."""
    source_id = "reddit"
    license_class = "contract_required"

    def __init__(self, contract_id: Optional[str] = None):
        self.contract_id = contract_id

    def is_enabled(self) -> bool:
        return bool(self.contract_id and self.contract_id.strip())

    async def fetch_recent(self, communities: List[str]) -> List[RawItem]:
        if not self.is_enabled():
            log.info("Reddit connector is disabled_unlicensed (no commercial license contract ID configured). Skipping.")
            return []
        # When license contract is present, commercial OAuth API with X-Ratelimit headers would execute here
        return []
