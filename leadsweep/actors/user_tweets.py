"""UserTweetsActor: Apify-class author timeline harvester actor."""
# NEW FEATURE (Phase C & H2-2): UserTweetsActor
from __future__ import annotations

import logging
import os
from typing import AsyncIterator
from pydantic import BaseModel, Field

from leadsweep.actors.base import Actor, ActorEstimate, RunContext
from leadsweep.exceptions import RateLimitedError, SessionExpiredError, UserNotFoundError
from leadsweep.models import Tweet
from leadsweep.target_grammar import parse_x_target

log = logging.getLogger("leadsweep.actors.user_tweets")


class UserTweetsActorInput(BaseModel):
    handle: str = Field(..., description="Target Twitter/X username, URL, or @handle")
    max_results: int = Field(default=20, ge=1, le=200, description="Number of tweets to harvest")
    cursor: str | None = Field(default=None, description="Resumption cursor")
    with_replies: bool = Field(default=False, description="Scrape Tweets & Replies tab")


class UserTweetsActor(Actor[UserTweetsActorInput, Tweet]):
    name = "user_tweets"
    version = "1.1.0"
    input_schema = UserTweetsActorInput
    risk_level = "low"

    def estimate(self, input_data: UserTweetsActorInput) -> ActorEstimate:
        pages = max(1, (input_data.max_results // 10) + 1)
        est_sec = pages * 3.0 + 3.0
        return ActorEstimate(
            estimated_items=input_data.max_results,
            estimated_seconds=est_sec,
            risk_level="low",
            cost_dollars=0.0,
        )

    async def run(self, input_data: UserTweetsActorInput, ctx: RunContext) -> AsyncIterator[Tweet]:
        parsed = parse_x_target(input_data.handle, "profile")
        if parsed.kind == "invalid":
            ctx.save_checkpoint({"x_status": "INVALID_TARGET", "x_status_detail": parsed.error})
            raise ValueError(parsed.error or "Invalid X profile target")

        clean_handle = parsed.handle or input_data.handle.strip().lstrip("@")
        with_replies = input_data.with_replies or parsed.with_replies

        log.info("Executing UserTweetsActor run_id=%s handle='%s' max=%d with_replies=%s",
                 ctx.run_id, clean_handle, input_data.max_results, with_replies)

        include_retweets = os.getenv("LEADSWEEP_X_PROFILE_INCLUDE_RETWEETS", "false").lower() in ("true", "1", "yes")

        yielded = 0
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
                    tweets = await scraper.fetch_user_profile_tweets(
                        clean_handle, limit=input_data.max_results, with_replies=with_replies
                    )
                    profile = getattr(scraper, "last_profile_data", None)
                    if profile:
                        prof_dict = profile.dict() if hasattr(profile, "dict") else profile.model_dump()
                        ctx.save_checkpoint({"profile_metadata": prof_dict})

                    seen_ids: set[str] = set()
                    for t in tweets:
                        if ctx.is_cancelled():
                            log.info("UserTweetsActor run_id=%s cancelled gracefully", ctx.run_id)
                            break
                        if t.id in seen_ids:
                            continue
                        seen_ids.add(t.id)

                        # Filter retweets if not included
                        if t.is_retweet and not include_retweets:
                            continue

                        yielded += 1
                        status_str = "OK" if yielded >= input_data.max_results else "EXHAUSTED"
                        status_det = (
                            f"Timeline yielded {yielded} posts"
                            if yielded >= input_data.max_results
                            else f"Timeline exhausted after {yielded} posts (requested {input_data.max_results})"
                        )
                        ctx.save_checkpoint({
                            "yielded": yielded,
                            "last_tweet_id": t.id,
                            "x_status": status_str,
                            "x_status_detail": status_det,
                        })
                        yield t

                    if yielded == 0:
                        ctx.save_checkpoint({
                            "x_status": "EMPTY",
                            "x_status_detail": f"@{clean_handle} timeline contains 0 visible posts",
                        })
                    return
            except UserNotFoundError as unfe:
                msg = str(unfe)
                status_code = "NOT_FOUND"
                if "SUSPENDED" in msg:
                    status_code = "SUSPENDED"
                elif "PROTECTED" in msg:
                    status_code = "PROTECTED"
                ctx.save_checkpoint({
                    "x_status": status_code,
                    "x_status_detail": msg,
                })
                raise
            except SessionExpiredError as see:
                ctx.save_checkpoint({
                    "x_status": "SESSION_EXPIRED",
                    "x_status_detail": str(see),
                })
                raise
            except RateLimitedError as rle:
                ctx.save_checkpoint({
                    "x_status": "RATE_LIMITED",
                    "x_status_detail": str(rle),
                })
                raise
            except Exception as e:
                log.warning("Browser-based UserTweetsActor extraction failed (%s)", e)
                ctx.save_checkpoint({
                    "x_status": "FAILED",
                    "x_status_detail": str(e),
                })
                raise

        # Autonomous Fallback for User Timeline if no browser session configured
        from leadsweep.adapters import PlatformAdapterRegistry
        adapter = PlatformAdapterRegistry.get("twitter")
        async for candidate in adapter.search(clean_handle, max_items=input_data.max_results):
            if ctx.is_cancelled() or yielded >= input_data.max_results:
                break
            yielded += 1
            tweet_item = candidate.to_tweet_compat()
            ctx.save_checkpoint({
                "yielded": yielded,
                "last_tweet_id": tweet_item.id,
                "x_status": "OK" if yielded >= input_data.max_results else "EXHAUSTED",
                "x_status_detail": f"Timeline yielded {yielded} posts",
            })
            yield tweet_item
