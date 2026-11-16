"""ProfileActor: Apify-class user profile metadata actor."""
# NEW FEATURE (Phase C): ProfileActor
from __future__ import annotations

import logging
from typing import AsyncIterator
from pydantic import BaseModel, Field

from leadsweep.actors.base import Actor, ActorEstimate, RunContext
from leadsweep.models import XUser

log = logging.getLogger("leadsweep.actors.profile")


class ProfileActorInput(BaseModel):
    handle: str = Field(..., description="Target Twitter/X screen name or username without @")


class ProfileActor(Actor[ProfileActorInput, XUser]):
    name = "profile"
    version = "1.0.0"
    input_schema = ProfileActorInput
    risk_level = "low"

    def estimate(self, input_data: ProfileActorInput) -> ActorEstimate:
        return ActorEstimate(
            estimated_items=1,
            estimated_seconds=4.0,
            risk_level="low",
            cost_dollars=0.0,
        )

    async def run(self, input_data: ProfileActorInput, ctx: RunContext) -> AsyncIterator[XUser]:
        from leadsweep.exceptions import UserNotFoundError
        from leadsweep.target_grammar import parse_x_target

        target = parse_x_target(input_data.handle, wizard_type="profile")
        if target.kind == "invalid":
            ctx.save_checkpoint({
                "x_status": "INVALID_TARGET",
                "x_status_detail": target.error or f"Invalid handle '{input_data.handle}'",
            })
            raise ValueError(target.error or "Invalid X target")

        clean_handle = target.handle or input_data.handle.strip().lstrip("@")
        log.info("Executing ProfileActor run_id=%s handle='%s'", ctx.run_id, clean_handle)

        async with ctx.use_scraper() as scraper:
            try:
                await scraper.fetch_user_profile_tweets(clean_handle, limit=1)
            except Exception as e:
                if not getattr(scraper, "last_profile_data", None):
                    status_code = "FAILED"
                    err_str = str(e)
                    if "NOT_FOUND" in err_str or isinstance(e, UserNotFoundError):
                        status_code = "NOT_FOUND"
                    elif "SUSPENDED" in err_str:
                        status_code = "SUSPENDED"
                    elif "PROTECTED" in err_str:
                        status_code = "PROTECTED"
                    ctx.save_checkpoint({
                        "x_status": status_code,
                        "x_status_detail": err_str,
                    })
                    raise

            user_obj = getattr(scraper, "last_profile_data", None)
            if user_obj:
                ctx.save_checkpoint({
                    "yielded": 1,
                    "handle": clean_handle,
                    "x_status": "OK",
                    "x_status_detail": "1 profile record",
                })
                yield user_obj
            else:
                ctx.save_checkpoint({
                    "x_status": "NOT_FOUND",
                    "x_status_detail": f"@{clean_handle} profile not found or unavailable",
                })
                raise UserNotFoundError(f"NOT_FOUND - @{clean_handle} profile not found or unavailable")
