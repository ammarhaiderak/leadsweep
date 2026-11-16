"""Durable-resume integration tests for the LangGraph pipeline (PHASE 4).

These run the real graph with a fake scrape client, so no X request is made.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from leadsweep.config import Settings
from leadsweep.pipeline.graph import Deps, make_checkpointer, new_run_id, run_graph
from leadsweep.pipeline.models import AgencyProfile, PipelineConfig, QuerySpec
from leadsweep.pipeline.store import Store
from leadsweep.schemas import ErrorInfo, SearchResponse
from leadsweep.models import Tweet


def _tweet(i: int) -> Tweet:
    return Tweet(
        id=f"tw{i}",
        url=f"https://x.com/i/status/tw{i}",
        text=f"We need an AI developer for automation project number {i} " + "detail " * 20,
        author_username=f"user{i}",
        author_followers=1000,
        like_count=5,
    )


class FakeClient:
    """Records every search so a resume can be shown not to re-scrape."""

    def __init__(self, tweets_per_query: int = 2):
        self.calls: list[str] = []
        self.tweets_per_query = tweets_per_query

    async def search(self, query: str, max_results: int) -> SearchResponse:
        self.calls.append(query)
        n = self.tweets_per_query
        return SearchResponse(
            ok=True, query=query, count=n,
            tweets=[_tweet(i) for i in range(n)],
        )


class FailingClient:
    """Fails the first N queries, to model a recoverable mid-run failure."""

    def __init__(self, fail_first: int):
        self.calls: list[str] = []
        self.fail_first = fail_first

    async def search(self, query: str, max_results: int) -> SearchResponse:
        self.calls.append(query)
        if len(self.calls) <= self.fail_first:
            return SearchResponse(
                ok=False, query=query, count=0,
                error=ErrorInfo(code="MCP_TRANSPORT", message="simulated transport failure",
                                retryable=True),
            )
        return SearchResponse(ok=True, query=query, count=1, tweets=[_tweet(99)])


def _cfg(n_queries: int = 2) -> PipelineConfig:
    return PipelineConfig(
        queries=[QuerySpec(name=f"q{i}", type="lead", q=f"query {i}") for i in range(n_queries)],
        max_results_per_query=5,
        min_score=10,
        heuristic_min_score=10,
        agency=AgencyProfile(services=["ai developer"], ideal_clients=[]),
    )


def _settings(tmp_path) -> Settings:
    return Settings(
        db_path=tmp_path / "store.db",
        out_dir=tmp_path / "out",
        min_score=None,
        llm_top_n=15,
        llm_timeout_s=5,
    )


def _deps(tmp_path, client) -> Deps:
    return Deps(
        client=client,
        store=Store(tmp_path / "store.db"),
        cfg=_cfg(),
        settings=_settings(tmp_path),
        scorer=None,
        scorer_label="heuristic",
        out_dir=tmp_path / "out",
    )


# --------------------------------------------------------------------------- checkpointer wiring
def test_graph_compiles_with_checkpointer(tmp_path):
    saver = make_checkpointer(tmp_path / "cp.db")
    d = _deps(tmp_path, FakeClient())
    try:
        res = asyncio.run(run_graph(d, thread_id="t-compile", checkpointer=saver))
        assert res["status"] in ("ok", "partial")
    finally:
        d.store.close()
        saver.close()


def test_pipeline_runs_without_checkpointer(tmp_path):
    """Existing behaviour must be preserved when checkpointing is not requested."""
    d = _deps(tmp_path, FakeClient())
    try:
        res = asyncio.run(run_graph(d))
        assert res["status"] in ("ok", "partial")
        assert res["stats"]["queries_total"] == 2
    finally:
        d.store.close()


# --------------------------------------------------------------------------- resume
def test_checkpoint_is_written_per_run(tmp_path):
    saver = make_checkpointer(tmp_path / "cp.db")
    client = FakeClient()
    d = _deps(tmp_path, client)
    try:
        asyncio.run(run_graph(d, thread_id="t-history", checkpointer=saver))
        history = list(saver.list({"configurable": {"thread_id": "t-history", "checkpoint_ns": ""}}))
        assert history, "expected at least one checkpoint to be persisted"
        latest = saver.get_tuple({"configurable": {"thread_id": "t-history", "checkpoint_ns": ""}})
        assert latest is not None
    finally:
        d.store.close()
        saver.close()


def test_resume_restores_state_from_checkpoint(tmp_path):
    """A second run on the same thread restores the saved channel values."""
    saver = make_checkpointer(tmp_path / "cp.db")
    d = _deps(tmp_path, FakeClient())
    cfg = {"configurable": {"thread_id": "t-resume", "checkpoint_ns": ""}}
    try:
        first = asyncio.run(run_graph(d, thread_id="t-resume", checkpointer=saver))
        assert first["status"] in ("ok", "partial")

        saved = saver.get_tuple(cfg)
        assert saved is not None
        values = saved.checkpoint["channel_values"]
        # The completed queries must be recoverable, which is what makes resume skip work.
        assert "done_queries" in values
        assert len(values["done_queries"]) == 2
    finally:
        d.store.close()
        saver.close()


def test_resume_does_not_rescrape_completed_queries(tmp_path):
    """The core resume guarantee: already-fetched queries are not fetched again."""
    saver = make_checkpointer(tmp_path / "cp.db")
    client = FakeClient()
    d = _deps(tmp_path, client)
    cfg = {"configurable": {"thread_id": "t-nodupe", "checkpoint_ns": ""}}
    try:
        asyncio.run(run_graph(d, thread_id="t-nodupe", checkpointer=saver))
        calls_after_first = list(client.calls)
        assert len(calls_after_first) == 2

        # Resume: the checkpoint says both queries are done, so nothing new is fetched.
        res = asyncio.run(run_graph(d, thread_id="t-nodupe", checkpointer=saver, resume=True))
        assert res["status"] in ("ok", "partial")
        assert client.calls == calls_after_first, "resume re-scraped a completed query"
        assert res["stats"]["resumed_at_query"] == 2
    finally:
        d.store.close()
        saver.close()


def test_resume_is_idempotent_for_stored_rows(tmp_path):
    """Re-saving the same scored tweets must not duplicate rows.

    `rescore` lives on Deps (it relaxes the 'already seen' filter) rather than on run_graph.
    """
    d = _deps(tmp_path, FakeClient())
    try:
        asyncio.run(run_graph(d))
        first_count = d.store.db.execute("SELECT COUNT(*) FROM tweets").fetchone()[0]
        score_count = d.store.db.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
        assert first_count > 0

        d.rescore = True  # bypass the already-seen filter so the same tweets are saved again
        asyncio.run(run_graph(d))
        assert d.store.db.execute("SELECT COUNT(*) FROM tweets").fetchone()[0] == first_count
        assert d.store.db.execute("SELECT COUNT(*) FROM scores").fetchone()[0] == score_count
    finally:
        d.store.close()


def test_thread_ids_are_independent(tmp_path):
    saver = make_checkpointer(tmp_path / "cp.db")
    d = _deps(tmp_path, FakeClient())
    try:
        asyncio.run(run_graph(d, thread_id="thread-one", checkpointer=saver))
        asyncio.run(run_graph(d, thread_id="thread-two", checkpointer=saver))
        for tid in ("thread-one", "thread-two"):
            got = saver.get_tuple({"configurable": {"thread_id": tid, "checkpoint_ns": ""}})
            assert got is not None, f"{tid} has no checkpoint"
    finally:
        d.store.close()
        saver.close()


def test_checkpoint_survives_process_restart(tmp_path):
    """State must be readable by a fresh saver instance, i.e. a restarted process."""
    db = tmp_path / "cp-persist.db"
    client = FakeClient()

    s1 = make_checkpointer(db)
    d1 = _deps(tmp_path, client)
    try:
        asyncio.run(run_graph(d1, thread_id="restart-thread", checkpointer=s1))
    finally:
        d1.store.close()
        s1.close()

    s2 = make_checkpointer(db)
    d2 = _deps(tmp_path, client)
    try:
        saved = s2.get_tuple({"configurable": {"thread_id": "restart-thread", "checkpoint_ns": ""}})
        assert saved is not None, "checkpoint did not survive saver close/reopen"
        assert len(saved.checkpoint["channel_values"]["done_queries"]) == 2

        # And resuming from the restored checkpoint fetches nothing new.
        asyncio.run(run_graph(d2, thread_id="restart-thread", checkpointer=s2, resume=True))
        assert client.calls == ["query 0", "query 1"]
    finally:
        d2.store.close()
        s2.close()


def test_new_run_id_is_unique():
    ids = {new_run_id() for _ in range(50)}
    assert len(ids) == 50