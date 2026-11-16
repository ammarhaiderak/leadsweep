"""Actor scraper lifecycle tests (PHASE 5).

Verifies that an injected scraper is reused and that no actor opens its own Chromium.
Everything here uses fakes - no browser is launched and no X request is made.
"""
from __future__ import annotations

import pytest

from leadsweep.actors import ActorRegistry
from leadsweep.actors.base import RunContext
from leadsweep.actors.followers import FollowersActorInput
from leadsweep.actors.likers import LikersActorInput
from leadsweep.actors.profile import ProfileActorInput
from leadsweep.actors.replies import RepliesActorInput
from leadsweep.actors.search import SearchActorInput
from leadsweep.actors.user_tweets import UserTweetsActorInput
from leadsweep.models import Tweet, XUser


class FakeScraper:
    """Records how many scraper instances were constructed vs reused."""

    instances_created = 0

    def __init__(self):
        FakeScraper.instances_created += 1
        self.calls: list[tuple] = []

    async def search_tweets(self, query, max_results=15, tab="live"):
        self.calls.append(("search_tweets", query, max_results))
        return [Tweet(id=f"t{len(self.calls)}", url="u", text="x" * 60,
                      author_username="a", like_count=1)]

    async def fetch_user_profile_tweets(self, username, limit=10, with_replies=False, **kwargs):
        self.calls.append(("profile", username, limit))
        self.last_profile_data = XUser(rest_id=f"u_{username}", handle=username, name=username.title())
        return [Tweet(id=f"p{len(self.calls)}", url="u", text="y" * 60, author_username=username)]

    async def fetch_user_followers(self, username, limit=50):
        self.calls.append(("followers", username, limit))
        return [XUser(rest_id=f"u{len(self.calls)}", handle=f"@{username}", bio="hello world")]


@pytest.fixture(autouse=True)
def _reset_counter():
    FakeScraper.instances_created = 0


def test_injected_scraper_is_reused_not_replaced():
    """The single most important lifecycle guarantee: zero extra browsers per run."""
    import asyncio

    async def go():
        scraper = FakeScraper()
        before = FakeScraper.instances_created

        actor = ActorRegistry.get("search")
        ctx = RunContext(run_id="r1", dataset_id="d1", scraper=scraper)
        out = [t async for t in actor.run(SearchActorInput(query="ai", max_results=3), ctx)]

        assert out, "actor produced no items"
        assert FakeScraper.instances_created == before, "actor created a new scraper despite injection"
        assert scraper.calls, "actor did not use the injected scraper"

    asyncio.run(go())


@pytest.mark.parametrize(
    "actor_name,actor_input,expected_call",
    [
        ("search", SearchActorInput(query="ai agents", max_results=3), "search_tweets"),
        ("user_tweets", UserTweetsActorInput(handle="github", max_results=3), "profile"),
        ("profile", ProfileActorInput(handle="github"), "profile"),
        ("followers", FollowersActorInput(handle="github", max_results=3), "followers"),
        ("replies", RepliesActorInput(tweet_id="1234567890", max_results=3), "search_tweets"),
        ("likers", LikersActorInput(tweet_id="1234567890", max_results=3), "search_tweets"),
    ],
)
def test_every_actor_respects_the_injected_scraper(actor_name, actor_input, expected_call):
    import asyncio

    async def go():
        scraper = FakeScraper()
        before = FakeScraper.instances_created
        actor = ActorRegistry.get(actor_name)
        ctx = RunContext(run_id="r", dataset_id="d", scraper=scraper)

        items = [i async for i in actor.run(actor_input, ctx)]

        assert FakeScraper.instances_created == before, f"{actor_name} opened its own browser"
        assert scraper.calls, f"{actor_name} ignored the injected scraper"
        assert scraper.calls[0][0] == expected_call, (
            f"{actor_name} called {scraper.calls[0][0]}, expected {expected_call}"
        )
        return items

    asyncio.run(go())


def test_cancellation_stops_the_actor_early():
    import asyncio

    async def go():
        scraper = FakeScraper()
        actor = ActorRegistry.get("search")
        ctx = RunContext(run_id="r", dataset_id="d", scraper=scraper)

        ctx.cancelled.set()
        items = [t async for t in actor.run(SearchActorInput(query="ai", max_results=5), ctx)]
        assert items == [], "a cancelled context must yield nothing"

    asyncio.run(go())


def test_checkpoint_records_progress():
    import asyncio

    async def go():
        scraper = FakeScraper()
        actor = ActorRegistry.get("search")
        ctx = RunContext(run_id="r", dataset_id="d", scraper=scraper)

        items = [t async for t in actor.run(SearchActorInput(query="ai", max_results=3), ctx)]
        assert ctx.checkpoint.get("yielded") == len(items)
        assert "last_tweet_id" in ctx.checkpoint

    asyncio.run(go())


def test_all_registered_actors_declare_a_risk_level():
    for entry in ActorRegistry.list_all():
        assert entry["risk_level"] in ("low", "medium", "high"), entry["name"]
        assert entry["input_schema"], f"{entry['name']} has no input schema"


def test_actor_estimate_is_monotonic_in_volume():
    actor = ActorRegistry.get("search")
    small = actor.estimate(SearchActorInput(query="x", max_results=5))
    large = actor.estimate(SearchActorInput(query="x", max_results=200))
    assert large.estimated_seconds >= small.estimated_seconds
    assert large.estimated_items == 200
    # $0 baseline must hold.
    assert large.cost_dollars == 0.0