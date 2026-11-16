"""Database resource-management tests (PHASE 7).

Two defects are pinned here:
  1. DatasetEngine._conn() used to return a bare connection, and ``with conn:`` only ends a
     transaction - it never closed the handle, leaking one SQLite connection per API call.
  2. vacuum_database() used to run VACUUM inside a transaction, which SQLite rejects.
"""
from __future__ import annotations

import gc
import sqlite3

import pytest

from leadsweep.core.datasets import DatasetEngine
from leadsweep.pipeline.store import Store


@pytest.fixture
def engine(tmp_path):
    e = DatasetEngine(tmp_path / "ds.db")
    # The engine expects a migrated file; DatasetEngine does not migrate on its own.
    Store(tmp_path / "ds.db").close()
    yield e


# --------------------------------------------------------------------------- connection lifecycle
def test_conn_context_manager_closes_the_handle(engine):
    """The handle must be unusable after the block exits."""
    with engine._conn() as conn:  # noqa: SLF001
        conn.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        conn.execute("SELECT 1")


def test_conn_closes_on_error(engine):
    captured = {}
    with pytest.raises(RuntimeError):
        with engine._conn() as conn:  # noqa: SLF001
            captured["c"] = conn
            raise RuntimeError("boom")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        captured["c"].execute("SELECT 1")


def test_repeated_operations_do_not_accumulate_connections(engine):
    """Operations are the hot path; none may hold a handle open afterwards."""
    for i in range(200):
        engine.append_item("ds", f"i{i}", "tweet", {"id": f"i{i}", "text": f"item {i}"})

    # Force a collection; an unclosed handle would still be referenced or open here.
    gc.collect()
    open_handles = [
        o for o in gc.get_objects()
        if isinstance(o, sqlite3.Connection) and _is_usable(o)
    ]
    assert len(open_handles) <= 1, f"{len(open_handles)} SQLite connections still open"


def _is_usable(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def test_engine_needs_no_explicit_close(engine):
    """DatasetEngine owns no persistent handle, so there is nothing for callers to close.

    This is the property that lets the API call sites stay simple and leak-free.
    """
    for i in range(5):
        engine.append_item("ds", f"x{i}", "tweet", {"id": f"x{i}", "text": "t"})
    assert len(engine.get_dataset_items("ds")) == 5


def test_foreign_keys_are_enforced_on_engine_connections(engine):
    """PRAGMA foreign_keys is per-connection, so it must be set on every _conn()."""
    with engine._conn() as conn:  # noqa: SLF001
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


# --------------------------------------------------------------------------- vacuum
def test_vacuum_succeeds(engine):
    """VACUUM outside a transaction. Previously raised 'cannot VACUUM from within a transaction'."""
    engine.append_item("ds", "v1", "tweet", {"id": "v1", "text": "vacuum me"})
    engine.vacuum_database()  # must not raise
    assert len(engine.get_dataset_items("ds")) == 1


def test_vacuum_preserves_data(engine):
    for i in range(25):
        engine.append_item("ds", f"k{i}", "tweet", {"id": f"k{i}", "text": f"keep {i}"})
    before = len(engine.get_dataset_items("ds"))
    engine.vacuum_database()
    assert len(engine.get_dataset_items("ds")) == before


# --------------------------------------------------------------------------- data integrity
def test_existing_database_remains_readable(tmp_path):
    """A file created by the pre-PHASE-7 code must still open and query cleanly."""
    path = tmp_path / "legacy.db"
    store = Store(path)
    store.db.execute(
        "INSERT INTO tweets (id, url, text, author_username, scraped_at, first_run_id) VALUES (?,?,?,?,?,?)",
        ("legacy1", "u", "old row", "someone", "now", "run"),
    )
    store.db.execute("INSERT OR REPLACE INTO scores VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     ("legacy1", "run", "q", "lead", 80, "lead", "[]", "r", "a", "rules", 80, "now"))
    store.db.commit()
    store.db.close()

    reopened = DatasetEngine(path)
    assert reopened.get_dataset_items("ds_none") == []
    store2 = Store(path)
    try:
        assert store2.db.execute("SELECT COUNT(*) FROM tweets").fetchone()[0] == 1
    finally:
        store2.close()


def test_store_applies_wal_and_foreign_keys(tmp_path):
    store = Store(tmp_path / "s.db")
    try:
        assert store.db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert store.db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert store.db.execute("PRAGMA user_version").fetchone()[0] >= 4
    finally:
        store.close()


def test_store_close_is_idempotent(tmp_path):
    store = Store(tmp_path / "s2.db")
    store.close()
    store.close()  # must not raise


def test_migrations_are_backward_compatible(tmp_path):
    """Opening a v0 database must bring it fully up to date, and re-opening is a no-op."""
    path = tmp_path / "fresh.db"
    s1 = Store(path)
    v = s1.db.execute("PRAGMA user_version").fetchone()[0]
    s1.close()

    s2 = Store(path)
    try:
        assert s2.db.execute("PRAGMA user_version").fetchone()[0] == v
        tables = {r[0] for r in s2.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"tweets", "scores", "runs", "actor_runs", "dataset_items", "items_fts", "jobs"} <= tables
    finally:
        s2.close()