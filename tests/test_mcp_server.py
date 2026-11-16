import asyncio

import pytest

from leadsweep import mcp_server as m
from leadsweep.exceptions import (EndpointChangedError, NoSessionAvailableError, RateLimitedError,
                               SessionExpiredError, UserNotFoundError)
from leadsweep.models import Tweet


class FakeScraper:
    def __init__(self, behavior):
        self.behavior, self.calls = behavior, 0

    async def search_with_failover(self, query, max_results=15, attempts=3):
        self.calls += 1
        return await self.behavior()

    async def profile_with_failover(self, username, limit=10, attempts=3):
        self.calls += 1
        return await self.behavior()

    async def followers_with_failover(self, username, limit=50, attempts=3):
        self.calls += 1
        return await self.behavior()


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setenv("LEADSWEEP_CALL_GAP_MIN", "0")
    monkeypatch.setenv("LEADSWEEP_CALL_GAP_MAX", "0")
    yield
    m.STATE.scraper = None


def _use(behavior):
    fake = FakeScraper(behavior)
    m.STATE.scraper = fake
    return fake


def run(coro):
    return asyncio.run(coro)


def test_tools_registered_with_output_schema():
    tools = run(m.mcp.list_tools())
    assert {t.name for t in tools} == {"search_tweets", "fetch_user_profile_tweets", "fetch_user_followers", "session_status"}
    assert all(t.outputSchema for t in tools)  # structured output advertised to clients


def test_search_success():
    async def ok():
        return [Tweet(id="1", url="u", text="t")]
    _use(ok)
    r = run(m.search_tweets("ai", 5))
    assert r.ok and r.count == 1 and r.error is None


@pytest.mark.parametrize("exc,code,retryable", [
    (RateLimitedError("429"), "RATE_LIMITED", True),
    (SessionExpiredError("x"), "SESSION_EXPIRED", False),
    (NoSessionAvailableError("none"), "NO_SESSION_AVAILABLE", True),
    (EndpointChangedError("drift"), "ENDPOINT_CHANGED", False),
    (RuntimeError("boom"), "INTERNAL", False),
])
def test_error_mapping(exc, code, retryable):
    async def bad():
        raise exc
    _use(bad)
    r = run(m.search_tweets("ai", 5))
    assert not r.ok and r.error.code == code and r.error.retryable is retryable


def test_profile_user_not_found_and_validation():
    async def missing():
        raise UserNotFoundError("nope")
    fake = _use(missing)
    assert run(m.fetch_user_profile_tweets("@ghost", 3)).error.code == "USER_NOT_FOUND"
    calls = fake.calls
    bad = run(m.fetch_user_profile_tweets("bad name!", 3))
    assert bad.error.code == "INVALID_INPUT" and fake.calls == calls  # rejected before scraping


def test_blank_query_rejected_without_scraping():
    fake = _use(lambda: None)
    assert run(m.search_tweets("   ", 5)).error.code == "INVALID_INPUT" and fake.calls == 0


def test_uninitialised_scraper_is_structured_error():
    m.STATE.scraper = None
    assert run(m.search_tweets("ai", 5)).error.code == "INTERNAL"


def test_followers_tool_success_and_validation():
    from leadsweep.models import XUser
    async def ok():
        return [XUser(rest_id="101", handle="test_user", followers_count=150)]
    fake = _use(ok)
    res = run(m.fetch_user_followers("test_user", 20))
    assert res.ok and res.count == 1 and res.users[0].handle == "test_user"

    calls = fake.calls
    bad = run(m.fetch_user_followers("bad user!", 20))
    assert bad.error.code == "INVALID_INPUT" and fake.calls == calls
