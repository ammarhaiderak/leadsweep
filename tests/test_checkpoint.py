"""Tests for the SQLite LangGraph checkpointer (PHASE 4)."""
from __future__ import annotations

import asyncio

import pytest
from langgraph.checkpoint.base import create_checkpoint, empty_checkpoint

from leadsweep.pipeline.checkpoint import SQLiteSaver


def _cfg(thread: str, ns: str = "", cid: str | None = None) -> dict:
    conf: dict = {"thread_id": thread, "checkpoint_ns": ns}
    if cid:
        conf["checkpoint_id"] = cid
    return {"configurable": conf}


@pytest.fixture
def saver(tmp_path):
    s = SQLiteSaver(tmp_path / "checkpoints.db")
    yield s
    s.close()


def test_schema_is_created(tmp_path):
    import sqlite3

    path = tmp_path / "cp.db"
    s = SQLiteSaver(path)
    s.close()
    conn = sqlite3.connect(path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"checkpointer_threads", "checkpointer_checkpoints", "checkpointer_writes"} <= tables


def test_put_and_get_roundtrip(saver):
    cp = create_checkpoint(empty_checkpoint(), {}, 1)
    meta = {"source": "loop", "step": 1}
    conf = saver.put(_cfg("thread-1"), cp, meta, {})

    assert conf["configurable"]["checkpoint_id"] == cp["id"]
    got = saver.get_tuple(_cfg("thread-1"))
    assert got is not None
    assert got.checkpoint["id"] == cp["id"]
    assert got.checkpoint["channel_values"] == cp["channel_values"]


def test_get_tuple_returns_none_for_unknown_thread(saver):
    assert saver.get_tuple(_cfg("never-seen")) is None


def test_latest_checkpoint_wins(saver):
    for i in (1, 2, 3):
        saver.put(_cfg("t"), create_checkpoint(empty_checkpoint(), {}, i), {"step": i}, {})
    latest = saver.get_tuple(_cfg("t"))
    assert latest is not None
    assert latest.metadata["step"] == 3


def test_explicit_checkpoint_id_is_honoured(saver):
    cp1 = create_checkpoint(empty_checkpoint(), {}, 1)
    cp2 = create_checkpoint(empty_checkpoint(), {}, 2)
    saver.put(_cfg("t"), cp1, {"step": 1}, {})
    saver.put(_cfg("t"), cp2, {"step": 2}, {})

    got = saver.get_tuple(_cfg("t", cid=cp1["id"]))
    assert got is not None and got.checkpoint["id"] == cp1["id"]


def test_put_writes_and_read_back(saver):
    cp = create_checkpoint(empty_checkpoint(), {}, 1)
    conf = saver.put(_cfg("t"), cp, {}, {})
    saver.put_writes(conf, [("channel_a", 42)], task_id="task-1")

    got = saver.get_tuple(_cfg("t"))
    assert got is not None
    assert any(ch == "channel_a" and v == 42 for ch, v in got.pending_writes)


def test_threads_are_isolated(saver):
    saver.put(_cfg("thread-a"), create_checkpoint(empty_checkpoint(), {}, 1), {"who": "a"}, {})
    saver.put(_cfg("thread-b"), create_checkpoint(empty_checkpoint(), {}, 1), {"who": "b"}, {})

    a = saver.get_tuple(_cfg("thread-a"))
    b = saver.get_tuple(_cfg("thread-b"))
    assert a.metadata["who"] == "a"
    assert b.metadata["who"] == "b"


def test_list_returns_history_newest_first(saver):
    for i in (1, 2, 3):
        saver.put(_cfg("t"), create_checkpoint(empty_checkpoint(), {}, i), {"step": i}, {})
    ids = [t.checkpoint["id"] for t in saver.list(_cfg("t"))]
    assert len(ids) == 3
    assert ids == sorted(ids, reverse=True)


def test_survives_reopen(tmp_path):
    """The whole point: state must outlive the process."""
    path = tmp_path / "persist.db"
    s1 = SQLiteSaver(path)
    cp = create_checkpoint(empty_checkpoint(), {}, 1)
    s1.put(_cfg("durable"), cp, {"persisted": True}, {})
    s1.close()

    s2 = SQLiteSaver(path)
    try:
        got = s2.get_tuple(_cfg("durable"))
        assert got is not None
        assert got.metadata["persisted"] is True
    finally:
        s2.close()


def test_async_api_matches_sync(saver):
    async def run():
        cp = create_checkpoint(empty_checkpoint(), {}, 1)
        conf = await saver.aput(_cfg("async-t"), cp, {"m": 1}, {})
        await saver.aput_writes(conf, [("c", 1)], task_id="t1")
        return await saver.aget_tuple(_cfg("async-t"))

    got = asyncio.run(run())
    assert got is not None and got.metadata["m"] == 1


def test_wal_is_enabled(tmp_path):
    import sqlite3

    path = tmp_path / "wal.db"
    s = SQLiteSaver(path)
    try:
        mode = s._conn.execute("PRAGMA journal_mode").fetchone()[0]  # noqa: SLF001
        assert mode.lower() == "wal"
    finally:
        s.close()


def test_close_is_idempotent(saver):
    saver.close()
    saver.close()