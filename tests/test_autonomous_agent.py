"""Unit and integration tests for the canonical autonomous agent (PHASE 2 / PHASE 3).

Targets leadsweep.services.agent.HITLAutonomousAgent - the implementation the REST API and the
CLI both use. The former leadsweep.core.agent.AutonomousAgent prototype is gone.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from leadsweep.api import app
from leadsweep.core.datasets import DatasetEngine
from leadsweep.core.hitl import HITLGuard
from leadsweep.pipeline.store import Store
from leadsweep.services.agent import HITLAutonomousAgent


@pytest.fixture
def short_hitl_timeout(monkeypatch):
    """Keep HITL-gated tests fast.

    A gated task blocks on its resume event for LEADSWEEP_HITL_TIMEOUT_S seconds (3600 by
    default). Tests that exercise the gate must therefore shorten it, otherwise the suite
    would wait an hour per test. Production behaviour is unchanged.
    """
    monkeypatch.setenv("LEADSWEEP_HITL_TIMEOUT_S", "1")
    return 1


@pytest.fixture
def agent_setup(tmp_path, short_hitl_timeout):
    db_file = tmp_path / "test_agent.db"
    Store(db_file).close()
    engine = DatasetEngine(db_file)
    guard = HITLGuard(engine=engine, max_auto_items=50, risk_threshold="medium")
    return HITLAutonomousAgent(engine=engine, guard=guard)


# --------------------------------------------------------------------------- planning
def test_agent_plan_resolution(agent_setup):
    agent = agent_setup

    plan_search = agent.plan("Find AI developers looking to hire in SF")
    assert plan_search["actor"] == "search"
    assert "developer" in plan_search["input"]["query"].lower()

    plan_tweets = agent.plan("Get the recent tweets from @sama")
    assert plan_tweets["actor"] == "user_tweets"
    assert plan_tweets["input"]["handle"] == "sama"

    plan_followers = agent.plan("Scrape followers of @karpathy")
    assert plan_followers["actor"] == "followers"
    assert plan_followers["input"]["handle"] == "karpathy"


def test_agent_plan_never_invents_a_target_account(agent_setup):
    """A prompt naming no account must not silently scrape a hardcoded demo handle."""
    agent = agent_setup
    for prompt in ("get the recent tweets", "scrape followers of", "who is this person"):
        plan = agent.plan(prompt)
        if plan["actor"] in ("user_tweets", "followers", "profile"):
            assert plan["input"].get("handle") == "", (
                f"{prompt!r} produced a fabricated handle: {plan['input']}"
            )


def test_agent_plan_does_not_invent_a_tweet_id(agent_setup):
    agent = agent_setup
    plan = agent.plan("show me the replies to that tweet")
    assert plan["actor"] == "replies"
    assert plan["input"]["tweet_id"] == ""


def test_agent_plan_respects_requested_volume(agent_setup):
    agent = agent_setup
    plan = agent.plan("scrape 120 followers from @github")
    assert plan["input"]["max_results"] == 120
    assert plan["requires_review_if"] is True


# --------------------------------------------------------------------------- execution
def test_safe_prompt_streams_without_hitl(agent_setup, fake_scraper):
    """A small search must reach execution and complete, using the injected scraper."""
    import asyncio

    agent = agent_setup
    scraper = fake_scraper()

    async def collect():
        return [c async for c in agent.execute_stream("Search for LangChain automation", scraper=scraper)]

    chunks = asyncio.run(collect())
    steps = [c["step"] for c in chunks]
    assert steps[:3] == ["planning", "intent_resolved", "preflight_estimate"]
    assert "hitl_paused" not in steps
    assert steps[-1] == "execution_completed"
    assert scraper.calls, "the injected scraper was not used"
    done = next(c for c in chunks if c["step"] == "execution_completed")
    assert done["total_items"] >= 1
    assert "xml" in done["export_urls"]


def test_completed_run_persists_dataset_items(agent_setup, fake_scraper, tmp_path):
    """A successful run must store its items in a dataset and finish the run row."""
    import asyncio

    from leadsweep.core.datasets import DatasetEngine

    agent = agent_setup

    async def collect():
        return [c async for c in agent.execute_stream("Search LangChain automation", scraper=fake_scraper())]

    chunks = asyncio.run(collect())
    done = next(c for c in chunks if c["step"] == "execution_completed")

    engine = DatasetEngine(agent.engine.db_path)
    assert engine.get_dataset_items(done["dataset_id"], limit=10)
    run = engine.get_run(done["run_id"])
    assert run is not None
    assert run["status"] == "succeeded"
    assert run["items_count"] >= 1


def test_blocked_browser_reports_failure_not_crash(agent_setup):
    """With no scraper injected and live launch blocked, the agent must fail cleanly."""
    import asyncio

    agent = agent_setup

    async def collect():
        return [c async for c in agent.execute_stream("Search LangChain automation")]

    chunks = asyncio.run(collect())
    steps = [c["step"] for c in chunks]
    assert steps[-1] == "execution_failed"
    # The failure must be reported, never raised into the stream consumer.
    assert "Live browser launch is blocked" in chunks[-1]["error"]
    assert "Traceback" not in chunks[-1]["error"]


def test_high_risk_prompt_trips_hitl_and_releases_state(agent_setup, fake_scraper):
    """The gate must fire, and the registry must not leak once the stream ends.

    With LEADSWEEP_HITL_TIMEOUT_S=1 the gate expires almost immediately, so this asserts both
    the pause event AND the deterministic timeout-abort path.
    """
    import asyncio

    from leadsweep.services.agent import REGISTRY

    agent = agent_setup

    async def collect():
        return [c async for c in agent.execute_stream(
            "Scrape 300 followers from @sama", scraper=fake_scraper())]

    chunks = asyncio.run(collect())
    steps = [c["step"] for c in chunks]
    assert "hitl_paused" in steps
    paused = next(c for c in chunks if c["step"] == "hitl_paused")
    assert paused["status"] == "hitl_pending"
    assert paused["reasons"]
    # Deterministic timeout: the run must abort rather than hang forever.
    assert "hitl_timeout" in steps
    # The registry must not leak entries once the generator finishes.
    assert REGISTRY.live_task_ids() == []


def test_registry_never_accumulates_across_many_runs(agent_setup, fake_scraper):
    """R5 regression: the old design appended to ACTIVE_TASKS forever."""
    import asyncio

    from leadsweep.services.agent import REGISTRY

    agent = agent_setup

    async def go():
        for _ in range(12):
            async for _ in agent.execute_stream("Search LangChain automation", scraper=fake_scraper()):
                pass

    asyncio.run(go())
    assert REGISTRY.live_task_ids() == [], "TaskRegistry leaked entries across runs"
    assert len(REGISTRY) == 0


def test_abandoned_generator_still_releases_registry(agent_setup, fake_scraper):
    """Cancelling a stream mid-flight must not leave a task registered forever."""
    import asyncio

    from leadsweep.services.agent import REGISTRY

    agent = agent_setup

    async def go():
        gen = agent.execute_stream("Search LangChain automation", scraper=fake_scraper())
        await gen.__anext__()  # planning
        await gen.aclose()     # client disconnects

    asyncio.run(go())
    assert REGISTRY.live_task_ids() == []


def test_invalid_plan_input_fails_fast(agent_setup):
    """An actor whose required input is missing must error, not raise into the stream."""
    import asyncio

    agent = agent_setup
    agent.plan = lambda prompt: {  # noqa: SLF001 - deliberately inject a broken plan
        "actor": "search", "input": {}, "explanation": "broken", "requires_review_if": False
    }

    async def collect():
        return [c async for c in agent.execute_stream("anything")]

    chunks = asyncio.run(collect())
    assert chunks[-1]["step"] == "error"
    assert "Invalid input" in chunks[-1]["message"]


def test_unknown_actor_reports_error(agent_setup):
    import asyncio

    agent = agent_setup
    agent.plan = lambda prompt: {  # noqa: SLF001
        "actor": "does_not_exist", "input": {}, "explanation": "x", "requires_review_if": False
    }

    async def collect():
        return [c async for c in agent.execute_stream("anything")]

    chunks = asyncio.run(collect())
    assert chunks[-1]["step"] == "error"
    assert "Actor lookup failed" in chunks[-1]["message"]


# --------------------------------------------------------------------------- API
def test_chat_stream_api_endpoint(auth_headers, tmp_db):
    client = TestClient(app, headers=auth_headers)
    res = client.post("/api/chat/stream", json={"message": "Find Python developers"})
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]


def test_chat_stream_emits_sse_frames(auth_headers, tmp_db):
    client = TestClient(app, headers=auth_headers)
    res = client.post("/api/chat/stream", json={"message": "Search LangChain automation"})
    assert res.status_code == 200
    body = res.text
    assert "data: " in body
    # Every frame must be a JSON object carrying the documented step discriminator.
    frames = [ln[6:] for ln in body.splitlines() if ln.startswith("data: ")]
    assert frames, "expected at least one SSE frame"
    import json

    parsed = [json.loads(f) for f in frames]
    assert all("step" in p for p in parsed)


def test_shared_scraper_manager_degrades_without_a_browser(auth_headers, tmp_db):
    """A browser failure must not prevent the API from streaming an agent error."""
    import asyncio

    from leadsweep.api import _ScraperManager

    mgr = _ScraperManager()
    try:
        result = asyncio.run(mgr.acquire())
        assert result is None, "live browser launch should be blocked in tests"
        assert mgr.available is False
        assert mgr.last_error and "blocked" in mgr.last_error
    finally:
        asyncio.run(mgr.release())


def test_shared_scraper_is_reused_across_acquires(tmp_db):
    """Once acquired, the manager must hand back the SAME scraper, never a new browser."""
    import asyncio

    from leadsweep.api import _ScraperManager

    sentinel = object()
    mgr = _ScraperManager()
    mgr._scraper = sentinel  # noqa: SLF001 - pretend a browser is already up
    try:
        assert asyncio.run(mgr.acquire()) is sentinel
        assert asyncio.run(mgr.acquire()) is sentinel
        assert mgr.available is False or mgr.available is True  # state flag only
    finally:
        mgr._scraper = None  # noqa: SLF001