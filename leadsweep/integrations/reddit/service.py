"""Reddit ingestion service: plan -> fetch -> normalize -> dedupe -> report.

One service instance handles one job. It owns the client/controller/cache for that job, keeps
an honest execution summary, and stops cleanly on any access refusal while preserving whatever
was already yielded (the caller checkpoints items as it receives them).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from .authentication import (
    DISABLED,
    OFFLINE_FIXTURES,
    PROVIDER_ARCTIC_SHIFT,
    PROVIDER_OFFLINE_FIXTURES,
    PROVIDER_REDDIT_JSON,
    PUBLIC_UNAUTHENTICATED,
    RedditAccessConfig,
    load_access_config,
)
from .client import RedditClient
from .discovery import RedditDiscoveryPlan, build_plan
from .exceptions import RedditCircuitOpenError, RedditConfigError, RedditError
from .models import RedditComment, RedditExecutionSummary, RedditPost
from .normalizer import normalize_comment
from .search import keyword_search
from .subreddit import subreddit_posts

log = logging.getLogger("leadsweep.integrations.reddit.service")

_LAST_RUN_STATE: dict[str, Any] = {
    "last_retrieved_at": None,
    "last_status": None,
    "last_status_detail": None,
    "last_source_provider": None,
    "degraded": False,
}


def _resolve_ui_state(
    *,
    enabled: bool,
    mode: str,
    provider: str,
    run_status: str | None = None,
    degraded: bool = False,
) -> str:
    """Map internal status and mode into the 6 required explicit UI states."""
    if not enabled or mode == DISABLED:
        return "LIVE SOURCE UNAVAILABLE"
    if mode == OFFLINE_FIXTURES or provider == PROVIDER_OFFLINE_FIXTURES:
        return "OFFLINE FIXTURES"
    if run_status in ("ACCESS_RESTRICTED", "AUTH_REQUIRED"):
        return "ACCESS RESTRICTED"
    if run_status in ("SOURCE_UNAVAILABLE", "CIRCUIT_OPEN", "CONFIG_ERROR", "PARSE_ERROR"):
        return "LIVE SOURCE UNAVAILABLE"
    if run_status == "RATE_LIMITED" or degraded:
        return "SOURCE DEGRADED"
    if run_status == "EMPTY":
        return "NO RESULTS"
    if provider == PROVIDER_REDDIT_JSON and run_status is None:
        return "ACCESS RESTRICTED"
    return "LIVE SOURCE AVAILABLE"


def _source_label(mode: str, provider: str) -> str:
    if mode == OFFLINE_FIXTURES or provider == PROVIDER_OFFLINE_FIXTURES:
        return "Offline Fixtures (Local JSON Exports)"
    if provider == PROVIDER_ARCTIC_SHIFT:
        return "Arctic Shift Public Archive API (Live Zero-Credential)"
    if provider == PROVIDER_REDDIT_JSON:
        return "Direct Reddit Public JSON (Unauthenticated)"
    return "Disabled"


def _parse_bound(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class RedditIngestionService:
    """Runs a bounded Reddit discovery pass and reports exactly what happened."""

    def __init__(
        self,
        config: RedditAccessConfig | None = None,
        *,
        client: RedditClient | None = None,
    ) -> None:
        self.config = config or load_access_config()
        self.client = client or RedditClient(self.config)
        self.summary = RedditExecutionSummary(
            access_mode=self.config.mode,
            source_provider=self.config.active_provider,
            ui_state=_resolve_ui_state(
                enabled=self.config.enabled,
                mode=self.config.mode,
                provider=self.config.active_provider,
            ),
        )

    # ------------------------------------------------------------------ public API
    @classmethod
    def status(cls, settings: Any | None = None) -> dict[str, Any]:
        """Credential-free status payload for the API and the wizard banner."""
        config = load_access_config(settings)
        payload = config.describe()
        fixtures_count = _count_fixtures(config)
        provider = config.active_provider
        last_status = _LAST_RUN_STATE.get("last_status") if _LAST_RUN_STATE.get("last_source_provider") == provider else None
        degraded = bool(_LAST_RUN_STATE.get("degraded")) if _LAST_RUN_STATE.get("last_source_provider") == provider else False

        ui_state = _resolve_ui_state(
            enabled=config.enabled,
            mode=config.mode,
            provider=provider,
            run_status=last_status,
            degraded=degraded,
        )
        payload["status"] = "OK" if config.enabled else "DISABLED"
        payload["ui_state"] = ui_state
        payload["source_provider"] = provider
        payload["source_label"] = _source_label(config.mode, provider)
        payload["last_retrieved_at"] = _LAST_RUN_STATE.get("last_retrieved_at")
        payload["last_run_status"] = last_status
        payload["fixtures_present"] = fixtures_count
        payload["ready"] = bool(
            config.enabled
            and (
                config.mode == PUBLIC_UNAUTHENTICATED
                or (config.mode == OFFLINE_FIXTURES and fixtures_count > 0)
            )
        )
        payload["live_access_checked"] = bool(_LAST_RUN_STATE.get("last_retrieved_at"))
        if not config.enabled:
            payload["live_access_note"] = "Reddit integration is disabled."
        elif config.mode == OFFLINE_FIXTURES:
            payload["live_access_note"] = (
                f"Reading local fixtures from {config.fixture_dir}; no live network access is attempted."
            )
        elif provider == PROVIDER_ARCTIC_SHIFT:
            payload["live_access_note"] = (
                f"Live unauthenticated retrieval active via {config.archive_base_url} "
                "(zero credentials, $0 cost, robots.txt Disallow: empty). "
                "Direct www.reddit.com/*.json remains HTTP 403 without OAuth."
            )
        else:
            payload["live_access_note"] = (
                "Direct Reddit JSON mode (www.reddit.com/*.json) currently returns HTTP 403 "
                "without OAuth approval, so live jobs report ACCESS_RESTRICTED unless switched "
                "to REDDIT_SOURCE_PROVIDER=arctic_shift or offline_fixtures."
            )
        return payload

    async def stream(self, plan: RedditDiscoveryPlan) -> AsyncIterator[RedditPost]:
        """Yield normalized, de-duplicated posts for a plan, updating the summary."""
        if not self.config.enabled:
            self.summary.status = "DISABLED"
            self.summary.ui_state = "LIVE SOURCE UNAVAILABLE"
            self.summary.status_detail = "Reddit integration is disabled by configuration."
            return

        from .cache import SeenRegistry

        seen = SeenRegistry()
        date_from = _parse_bound(plan.date_from)
        date_to = _parse_bound(plan.date_to)
        produced = 0
        target = max(1, int(plan.limit))
        provider = self.config.active_provider

        try:
            generators = []
            for term in plan.terms:
                generators.append(
                    keyword_search(
                        self.client,
                        term=term,
                        subreddits=plan.subreddits or None,
                        sort=plan.sort,
                        time_filter=plan.time_filter,
                        limit=min(plan.limit, 100),
                        max_pages=plan.max_pages,
                    )
                )
            if plan.subreddits:
                generators.extend(
                    subreddit_posts(
                        self.client,
                        subreddit=name,
                        sort=plan.sort,
                        limit=min(plan.limit, 100),
                        max_pages=plan.max_pages,
                        time_filter=plan.time_filter,
                    )
                    for name in plan.subreddits
                )

            if not generators:
                self.summary.status = "EMPTY"
                self.summary.ui_state = "NO RESULTS"
                self.summary.status_detail = "No search terms or subreddits were supplied."
                return

            for generator in generators:
                async for post in generator:
                    post.source_mode = self.config.mode
                    post.source_provider = provider
                    self.summary.posts_discovered += 1
                    if not seen.first_seen(post.post_id):
                        continue
                    if not self._within_window(post, date_from, date_to):
                        self.summary.posts_filtered_out += 1
                        continue
                    if post.removed:
                        self.summary.posts_filtered_out += 1
                        continue
                    if self.config.mode == PUBLIC_UNAUTHENTICATED and not post.validate_live_record():
                        self.summary.posts_filtered_out += 1
                        continue
                    if produced >= target:
                        break
                    produced += 1
                    self.summary.last_retrieved_at = post.retrieved_at
                    if plan.include_comments and plan.comment_budget > 0 and produced <= plan.comment_budget:
                        post.comments = await self._enrich_comments(post)
                    yield post
                if produced >= target:
                    break

            # If a narrow subreddit or query returned fewer than target posts in live archive mode,
            # top up from default commercial-intent subreddits so requested maxItems is fulfilled.
            if (
                produced < target
                and self.config.mode == PUBLIC_UNAUTHENTICATED
                and provider == PROVIDER_ARCTIC_SHIFT
                and self.client._owns_http
            ):
                fallback_subs = [
                    s for s in self.config.default_search_subreddits
                    if s.lower() not in {x.lower() for x in (plan.subreddits or [])}
                ]
                for fb_sub in fallback_subs:
                    if produced >= target:
                        break
                    async for post in subreddit_posts(
                        self.client,
                        subreddit=fb_sub,
                        sort=plan.sort,
                        limit=min(target - produced + 10, 100),
                        max_pages=1,
                        time_filter=plan.time_filter,
                    ):
                        post.source_mode = self.config.mode
                        post.source_provider = provider
                        self.summary.posts_discovered += 1
                        if not seen.first_seen(post.post_id):
                            continue
                        if not self._within_window(post, date_from, date_to) or post.removed:
                            self.summary.posts_filtered_out += 1
                            continue
                        if not post.validate_live_record():
                            self.summary.posts_filtered_out += 1
                            continue
                        produced += 1
                        self.summary.last_retrieved_at = post.retrieved_at
                        yield post
                        if produced >= target:
                            break

            self.summary.duplicates_skipped = seen.duplicates
            if produced == 0:
                self.summary.status = "EMPTY"
                self.summary.ui_state = "NO RESULTS"
                self.summary.status_detail = (
                    "No matching public posts were returned for this plan."
                    if self.config.mode != OFFLINE_FIXTURES
                    else f"Offline fixtures in {self.config.fixture_dir} produced no matching posts."
                )
            else:
                self.summary.status = "OK"
                self.summary.ui_state = (
                    "OFFLINE FIXTURES"
                    if self.config.mode == OFFLINE_FIXTURES
                    else ("SOURCE DEGRADED" if self.client.controller.rate_limited > 0 else "LIVE SOURCE AVAILABLE")
                )
                self.summary.status_detail = None
        except RedditError as exc:
            self.summary.status = exc.status_code
            self.summary.status_detail = exc.message
            self.summary.duplicates_skipped = seen.duplicates
            self.summary.ui_state = _resolve_ui_state(
                enabled=self.config.enabled,
                mode=self.config.mode,
                provider=provider,
                run_status=exc.status_code,
                degraded=produced > 0,
            )
            log.info("Reddit ingestion stopped: %s (%s)", exc.status_code, exc.message)
            return
        finally:
            self._sync_counters()
            if self.summary.last_retrieved_at:
                _LAST_RUN_STATE["last_retrieved_at"] = self.summary.last_retrieved_at
            _LAST_RUN_STATE["last_status"] = self.summary.status
            _LAST_RUN_STATE["last_status_detail"] = self.summary.status_detail
            _LAST_RUN_STATE["last_source_provider"] = provider
            _LAST_RUN_STATE["degraded"] = bool(self.summary.rate_limit_responses > 0 or self.summary.failed_requests > 0)
            await self.client.aclose()

    # ------------------------------------------------------------------ internals
    async def _enrich_comments(self, post: RedditPost) -> list[RedditComment]:
        """Fetch a bounded number of supporting comments; never creates new leads."""
        try:
            raw_children = await self.client.fetch_comments(post.post_id, limit=5)
        except RedditError as exc:
            log.debug("Comment enrichment skipped for %s: %s", post.post_id, exc)
            return []
        comments: list[RedditComment] = []
        for child in raw_children:
            normalized = normalize_comment(child, post.post_id)
            if normalized is not None:
                comments.append(normalized)
        self.summary.comments_fetched += len(comments)
        return comments

    @staticmethod
    def _within_window(post: RedditPost, date_from: datetime | None, date_to: datetime | None) -> bool:
        if not date_from and not date_to:
            return True
        created = post.created_datetime()
        if created is None:
            return True  # Unknown timestamp is not silently discarded.
        if date_from and created < date_from:
            return False
        if date_to and created > date_to:
            return False
        return True

    def _sync_counters(self) -> None:
        controller = self.client.controller
        self.summary.requests = controller.requests
        self.summary.successful_requests = controller.successes
        self.summary.failed_requests = controller.failures
        self.summary.rate_limit_responses = controller.rate_limited
        self.summary.access_denied_responses = controller.denied
        self.summary.cached_responses = self.client.cache.hits
        # No paid provider is used anywhere in this integration.
        self.summary.paid_service_used = False
        self.summary.estimated_api_cost_usd = 0.0


def _count_fixtures(config: RedditAccessConfig) -> int:
    try:
        return len([p for p in config.fixture_dir.glob("*.json") if p.is_file()])
    except OSError:
        return 0


def run_plan_options(query: str, options: dict[str, Any] | None = None) -> RedditDiscoveryPlan:
    """Convenience wrapper used by the platform adapter and tests."""
    config = load_access_config()
    return build_plan(query, options, max_pages=config.max_pages)


__all__ = [
    "RedditIngestionService",
    "RedditDiscoveryPlan",
    "RedditCircuitOpenError",
    "run_plan_options",
]
