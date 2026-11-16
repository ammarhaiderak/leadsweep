"""RepliesActor: Extract conversation replies for a target tweet."""
# NEW FEATURE (Phase C): RepliesActor
from __future__ import annotations

import logging
from typing import AsyncIterator
from pydantic import BaseModel, Field

from leadsweep.actors.base import Actor, ActorEstimate, RunContext
from leadsweep.models import Tweet

log = logging.getLogger("leadsweep.actors.replies")


class RepliesActorInput(BaseModel):
    tweet_id: str = Field(..., description="Target parent Tweet ID")
    author_handle: str | None = Field(default=None, description="Tweet author handle for search filtering")
    max_results: int = Field(default=20, ge=1, le=100, description="Max replies to harvest")


class RepliesActor(Actor[RepliesActorInput, Tweet]):
    name = "replies"
    version = "1.0.0"
    input_schema = RepliesActorInput
    risk_level = "low"

    def estimate(self, input_data: RepliesActorInput) -> ActorEstimate:
        return ActorEstimate(
            estimated_items=input_data.max_results,
            estimated_seconds=8.0,
            risk_level="low",
            cost_dollars=0.0,
        )

    async def run(self, input_data: RepliesActorInput, ctx: RunContext) -> AsyncIterator[Tweet]:
        log.info("Executing RepliesActor run_id=%s tweet_id=%s max=%d", ctx.run_id, input_data.tweet_id, input_data.max_results)

        # Conversational query search pattern: conversation_id:{tweet_id}
        search_query = f"conversation_id:{input_data.tweet_id}"
        if input_data.author_handle:
            search_query += f" to:{input_data.author_handle.lstrip('@')}"

        yielded = 0  # UPDATED LOGIC: Initialize yielded counter
        use_browser_scraper = False
        if ctx.scraper is not None:
            use_browser_scraper = True
        else:
            try:
                from leadsweep.config import get_settings
                sessions_file = get_settings().sessions_file
                if sessions_file.exists():
                    use_browser_scraper = True
            except Exception:
                use_browser_scraper = False

        if use_browser_scraper:
            try:
                async with ctx.use_scraper() as scraper:
                    tweets = await scraper.search_tweets(query=search_query, max_results=input_data.max_results)
                    for t in tweets:
                        if ctx.is_cancelled():
                            log.info("RepliesActor run_id=%s cancelled gracefully", ctx.run_id)
                            break
                        yielded += 1
                        ctx.save_checkpoint({"yielded": yielded, "last_reply_id": t.id})
                        yield t
                    return
            except Exception as e:
                log.warning("Browser-based RepliesActor extraction unavailable (%s), falling back to public resolver", e)

        # Zero-Account Autonomous Fallback for Replies
        from leadsweep.adapters import PlatformAdapterRegistry
        adapter = PlatformAdapterRegistry.get("twitter")
        async for candidate in adapter.search(search_query, max_items=input_data.max_results):
            if ctx.is_cancelled() or yielded >= input_data.max_results:
                break
            yielded += 1
            tweet_item = candidate.to_tweet_compat()
            ctx.save_checkpoint({"yielded": yielded, "last_reply_id": tweet_item.id})
            yield tweet_item
