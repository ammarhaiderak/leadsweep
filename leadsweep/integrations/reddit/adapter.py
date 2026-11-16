"""Platform adapter binding Reddit ingestion into the existing SearchActor dispatch."""
from __future__ import annotations

import datetime
import logging
from typing import Any, AsyncIterator

from leadsweep.adapters import LeadRecord, PlatformAdapter

from .authentication import OFFLINE_FIXTURES, load_access_config
from .discovery import build_plan
from .service import RedditIngestionService

log = logging.getLogger("leadsweep.integrations.reddit.adapter")


class RedditNativeAdapter(PlatformAdapter):
    """Native Reddit platform adapter (no credentials, no fabricated metrics)."""

    platform_name = "reddit"

    def __init__(self) -> None:
        self.last_scrape_status: str | None = None
        self.last_scrape_detail: str | None = None
        self.execution_summary: dict[str, Any] | None = None

    async def search(
        self,
        query: str,
        max_items: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> AsyncIterator[LeadRecord]:
        options = dict(filters or {})
        config = load_access_config()
        plan = build_plan(query, options, max_pages=config.max_pages)
        # Honour the job's item budget; the wizard may pass subreddits without a query.
        plan.limit = max(1, min(int(options.get("max_results") or max_items or 20), 100))
        if plan.include_comments and config.comment_budget:
            plan.comment_budget = min(plan.comment_budget or config.comment_budget, config.comment_budget)

        log.info(
            "Reddit discovery start: mode=%s access=%s terms=%d subreddits=%d limit=%d",
            plan.mode, config.mode, len(plan.terms), len(plan.subreddits), plan.limit,
        )

        service = RedditIngestionService(config)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        yielded = 0
        async for post in service.stream(plan):
            yielded += 1
            engagement: dict[str, int] = {}
            if post.score is not None:
                engagement["likes"] = post.score
            if post.num_comments is not None:
                engagement["replies"] = post.num_comments
            # ``headline`` stays None on purpose: to_tweet_compat() prepends it, which would
            # duplicate the title already present in ``content``.
            yield LeadRecord(
                id=post.lead_id,
                platform="reddit",
                source_id=post.post_id,
                source_url=post.permalink,
                name=post.author or post.subreddit,
                username=post.author or f"r_{post.subreddit}",
                title=post.title,
                bio=None,
                content=post.full_text(),
                profile_url=f"https://www.reddit.com/user/{post.author}" if post.author else None,
                engagement=engagement,
                published_at=post.created_at,
                # Keep subreddit/title/permalink available to the Data Explorer and exports.
                extra_metadata=post.metadata(),
                collected_at=now_iso,
                updated_at=now_iso,
                intent="reddit public discussion",
            )

        self.last_scrape_status = service.summary.status
        self.last_scrape_detail = service.summary.status_detail
        self.execution_summary = service.summary.to_dict()
        log.info(
            "Reddit discovery finished: yielded=%d status=%s requests=%d denied=%d cached=%d",
            yielded,
            service.summary.status,
            service.summary.requests,
            service.summary.access_denied_responses,
            service.summary.cached_responses,
        )


def is_fixture_mode() -> bool:
    return load_access_config().mode == OFFLINE_FIXTURES


__all__ = ["RedditNativeAdapter", "is_fixture_mode"]
