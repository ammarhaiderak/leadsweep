"""SearchActor: Apify-class keyword and advanced search query actor."""
# NEW FEATURE (Phase B): SearchActor with strict Actor interface
from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Literal

from pydantic import BaseModel, Field

from leadsweep.actors.base import Actor, ActorEstimate, RunContext
from leadsweep.models import Tweet

log = logging.getLogger("leadsweep.actors.search")


class SearchActorInput(BaseModel):
    query: str = Field(..., description="Target search query or raw phrase")
    tab: Literal["live", "top"] = Field(default="live", description="Search timeline tab")
    max_results: int = Field(default=20, ge=1, le=500, description="Target tweet harvest count")
    cursor: str | None = Field(default=None, description="Optional resumption cursor")
    platform: str = Field(default="twitter", description="Target platform (twitter, linkedin, reddit, youtube, etc.)")
    # NEW FEATURE: Per-platform discovery options (Reddit subreddits / comment enrichment).
    options: dict[str, Any] = Field(default_factory=dict, description="Platform-specific options" )


class SearchActor(Actor[SearchActorInput, Tweet]):
    name = "search"
    version = "1.0.0"
    input_schema = SearchActorInput
    risk_level = "low"

    def estimate(self, input_data: SearchActorInput) -> ActorEstimate:
        # Pacing: ~15 tweets per scroll page + jitter
        pages = max(1, (input_data.max_results // 15) + 1)
        est_sec = pages * 3.5 + 4.0
        return ActorEstimate(
            estimated_items=input_data.max_results,
            estimated_seconds=est_sec,
            risk_level="low",
            cost_dollars=0.0,
        )

    async def run(self, input_data: SearchActorInput, ctx: RunContext) -> AsyncIterator[Tweet]:
        """Stream scraped items while updating checkpoints after page fetches.
        
        Supports:
        1. Multi-platform extraction (LinkedIn, Reddit, YouTube, Instagram, Facebook, TikTok, Twitter).
        2. 30-day freshness limit.
        3. Guaranteed volume with smart query expansion.
        """
        import datetime
        import urllib.request
        import urllib.parse
        import re
        from selectolax.lexbor import LexborHTMLParser

        target_platform = (input_data.platform or "twitter").lower()
        target_count = input_data.max_results
        raw_q = input_data.query.strip().strip('"').strip("'")
        
        # -------------------------------------------------------------
        # Phase 2 & 3: Platform Adapter Dispatch for non-Twitter (LinkedIn, Upwork, Fiverr)
        # -------------------------------------------------------------
        from leadsweep.adapters import PlatformAdapterRegistry
        from leadsweep.services.relevance import QueryIntent, RelevanceEngine

        if target_platform != "twitter":
            adapter = PlatformAdapterRegistry.get(target_platform)
            intent = QueryIntent.parse(raw_q, platform=target_platform)
            relevance_engine = RelevanceEngine(threshold=0.35)

            log.info(
                "Executing platform adapter '%s' for query '%s' (intent role=%s, ind=%s, loc=%s, target=%d)",
                adapter.platform_name, raw_q, intent.target_entity, intent.industry, intent.location, target_count
            )

            yielded = 0
            tg_filters = {"job_id": ctx.run_id} if target_platform == "telegram" else None
            # NEW FEATURE: Reddit receives the job's discovery options (subreddits, dates, comments).
            if target_platform == "reddit":
                tg_filters = dict(input_data.options or {})
                tg_filters["max_results"] = target_count
            tg_items_limit = target_count if target_platform == "telegram" else target_count * 2
            # NEW FEATURE: The keyword-overlap gate would drop genuine Reddit posts (a subreddit
            # browse need not contain every query token). Reddit is gated by subreddit/term
            # retrieval and then by the existing qualification pipeline instead.
            apply_relevance_gate = target_platform != "reddit"
            async for candidate in adapter.search(raw_q, max_items=tg_items_limit, filters=tg_filters):
                if yielded >= target_count or ctx.is_cancelled():
                    break

                # Evaluate candidate through relevance filter
                is_accepted, score, signals = relevance_engine.evaluate(candidate, intent)
                if apply_relevance_gate and not is_accepted:
                    log.debug("Rejected candidate %s (score=%.2f < threshold)", candidate.name, score)
                    continue

                yielded += 1
                tweet_item = candidate.to_tweet_compat()
                ctx.save_checkpoint({"yielded": yielded, "last_url": candidate.source_url, "platform": target_platform})
                yield tweet_item

            # NEW FEATURE (Phase 1): Communicate Telegram status & detail to runner
            if target_platform == "telegram" and hasattr(adapter, "last_scrape_status"):
                from leadsweep.services.telegram_public_scraper import _TRANSPORT_MGR
                ctx.save_checkpoint({
                    "yielded": yielded,
                    "platform": target_platform,
                    "telegram_status": adapter.last_scrape_status,
                    "telegram_status_detail": getattr(adapter, "last_scrape_detail", None),
                    "candidate_reports": getattr(adapter, "candidate_reports", []),
                    "accounting": _TRANSPORT_MGR.get_accounting_summary(job_id=ctx.run_id),
                })

            # NEW FEATURE: Reddit execution summary + stop reason for the job lifecycle.
            if target_platform == "reddit" and hasattr(adapter, "last_scrape_status"):
                ctx.save_checkpoint({
                    "yielded": yielded,
                    "platform": target_platform,
                    "reddit_status": adapter.last_scrape_status,
                    "reddit_status_detail": getattr(adapter, "last_scrape_detail", None),
                    "reddit_summary": getattr(adapter, "execution_summary", None),
                })

            log.info("Finished %s search with %d relevant leads (target=%d)", target_platform, yielded, target_count)
            return

        # -------------------------------------------------------------
        # Twitter (X) Platform with Pre-Scraping AI Agent Optimization Layer
        # -------------------------------------------------------------
        from leadsweep.services.query_agent import QueryOptimizationAgent

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        thirty_days_ago = now_utc - datetime.timedelta(days=30)

        # Agent Layer: Generate high-intent, platform-native boolean queries
        clean_raw = raw_q.strip().strip('"').strip("'")
        query_plan = await QueryOptimizationAgent.optimize(clean_raw, platform="twitter")
        
        # Prioritize body-targeted Agent boolean queries, followed by exact quotes and clean raw query
        queries_to_try: list[str] = []
        for q in (query_plan.search_queries or []):
            if q not in queries_to_try:
                queries_to_try.append(q)
        if f'"{clean_raw}"' not in queries_to_try:
            queries_to_try.append(f'"{clean_raw}"')
        if clean_raw not in queries_to_try:
            queries_to_try.append(clean_raw)

        seen_ids: set[str] = set()
        author_yield_counts: dict[str, int] = {}  # Cap per-author extraction to prevent single-profile dumps
        yielded = 0

        use_browser_scraper = False
        if ctx.scraper is not None:
            use_browser_scraper = True
        else:
            try:
                from pathlib import Path
                from leadsweep.config import get_settings
                sessions_file = get_settings().sessions_file
                if sessions_file.exists():
                    # Verify that sessions_file contains at least one session
                    import json
                    raw_sess = json.loads(sessions_file.read_text(encoding="utf-8"))
                    if raw_sess.get("sessions"):
                        use_browser_scraper = True
            except Exception:
                use_browser_scraper = False

        if use_browser_scraper:
            try:
                async with ctx.use_scraper() as scraper:
                    for q_idx, active_q in enumerate(queries_to_try):
                        if yielded >= target_count or ctx.is_cancelled():
                            break

                        needed = target_count - yielded
                        log.info(
                            "SearchActor AI Agent query pass %d/%d: '%s' (needed=%d)",
                            q_idx + 1, len(queries_to_try), active_q, needed
                        )
                        
                        tweets = []
                        last_search_exc = None
                        for search_attempt in range(1, 3):
                            try:
                                tweets = await scraper.search_tweets(
                                    query=active_q,
                                    tab=input_data.tab,
                                    max_results=max(needed, 50),
                                )
                                last_search_exc = None
                                break
                            except Exception as exc:
                                last_search_exc = exc
                                from leadsweep.exceptions import RateLimitedError, SessionExpiredError, NoSessionAvailableError
                                if isinstance(exc, (RateLimitedError, SessionExpiredError, NoSessionAvailableError)):
                                    st_label = "RATE_LIMITED" if isinstance(exc, RateLimitedError) else "SESSION_COOLDOWN"
                                    ctx.save_checkpoint({
                                        "x_status": st_label,
                                        "x_status_detail": str(exc),
                                    })
                                    log.warning("Search pass hit %s for '%s': %s", st_label, active_q, exc)
                                    break
                                log.warning("Search pass attempt %d failed for '%s': %s; retrying in 3s...", search_attempt, active_q, exc)
                                await asyncio.sleep(3.0)
                        if last_search_exc:
                            continue

                        for t in tweets:
                            if ctx.is_cancelled() or yielded >= target_count:
                                break

                            if t.id in seen_ids:
                                continue
                            seen_ids.add(t.id)

                            author = (t.author_username or "").strip().lower()
                            if author:
                                current_author_count = author_yield_counts.get(author, 0)
                                if current_author_count >= 2:
                                    continue

                            if t.created_at:
                                tweet_dt = t.created_at
                                if tweet_dt.tzinfo is None:
                                    tweet_dt = tweet_dt.replace(tzinfo=datetime.timezone.utc)
                                if tweet_dt < thirty_days_ago:
                                    continue

                            import html
                            raw_text = t.text or ""
                            clean_text = html.unescape(raw_text).strip()
                            t.text = clean_text

                            if not clean_text or len(clean_text) < 15:
                                continue

                            if author:
                                author_yield_counts[author] = author_yield_counts.get(author, 0) + 1

                            t.platform = "twitter"
                            yielded += 1
                            ctx.save_checkpoint({"yielded": yielded, "last_tweet_id": t.id})
                            yield t
            except Exception as e:
                if "Live browser launch is blocked" in str(e):
                    raise
                log.warning("Browser-based X scraping unavailable (%s), switching to autonomous zero-login TwitterAdapter", e)

        # Autonomous Zero-Account Fallback: Search via public TwitterAdapter without requiring user account sessions
        if yielded < target_count and not ctx.is_cancelled():
            adapter = PlatformAdapterRegistry.get("twitter")
            intent = QueryIntent.parse(clean_raw, platform="twitter")
            relevance_engine = RelevanceEngine(threshold=0.30)

            log.info("Executing autonomous zero-account Twitter adapter for '%s' (needed=%d)", clean_raw, target_count - yielded)
            async for candidate in adapter.search(clean_raw, max_items=(target_count - yielded) * 2):
                if yielded >= target_count or ctx.is_cancelled():
                    break
                if candidate.id in seen_ids:
                    continue
                seen_ids.add(candidate.id)

                is_accepted, score, signals = relevance_engine.evaluate(candidate, intent)
                if not is_accepted:
                    continue

                yielded += 1
                tweet_item = candidate.to_tweet_compat()
                ctx.save_checkpoint({"yielded": yielded, "last_url": candidate.source_url, "platform": "twitter"})
                yield tweet_item

        log.info("SearchActor run_id=%s finished with %d fresh tweets (target=%d)", ctx.run_id, yielded, target_count)
        return

