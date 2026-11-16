"""Durable SQLite checkpointer for the LangGraph pipeline (PHASE 4).

Why this exists
---------------
``langgraph-checkpoint-sqlite`` is not a dependency of this project, and the $0 /
dependency-discipline rules say not to add one when the installed
``langgraph-checkpoint`` package already exposes the abstract
:class:`~langgraph.checkpoint.base.BaseCheckpointSaver` we need. This module implements that
interface on top of stdlib ``sqlite3`` plus the bundled ``JsonPlusSerializer``.

What it buys
------------
A pipeline run can be interrupted and resumed. Before this, a crash mid-run lost every fetch
and score result because the graph held all state in memory.

Schema (created on demand, ``IF NOT EXISTS`` everywhere, so it is safe to re-run):

    checkpointer_threads  thread_id, checkpoint_ns, checkpoint_id  (PK)
    checkpointer_checkpoints   checkpoint_id, parent_checkpoint_id, type, blob, metadata
    checkpointer_writes        thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel,
                               type, blob

Concurrency
-----------
WAL journalling plus ``BEGIN IMMEDIATE`` means a checkpoint write cannot interleave with a
concurrent writer, and readers never block. A per-thread connection is reused rather than
opened per call, and :meth:`close` releases it.
"""
from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

SCHEMA = """
-- Every checkpoint, tagged with the thread that owns it. History is stored here (not only in
-- checkpointer_threads) so `list()` can return the full run history, not just the newest row.
CREATE TABLE IF NOT EXISTS checkpointer_checkpoints (
    checkpoint_id        TEXT PRIMARY KEY,
    parent_checkpoint_id TEXT,
    thread_id            TEXT NOT NULL DEFAULT '',
    checkpoint_ns        TEXT NOT NULL DEFAULT '',
    type                 TEXT,
    blob                 BLOB,
    metadata             BLOB
);

CREATE INDEX IF NOT EXISTS idx_cp_thread_history
    ON checkpointer_checkpoints (thread_id, checkpoint_ns);

-- Pointer to the newest checkpoint per thread, for cheap "load latest".
CREATE TABLE IF NOT EXISTS checkpointer_threads (
    thread_id     TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_ns)
);

CREATE TABLE IF NOT EXISTS checkpointer_writes (
    thread_id     TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id       TEXT NOT NULL,
    idx           INTEGER NOT NULL,
    channel       TEXT NOT NULL,
    type          TEXT,
    blob          BLOB,
    task_path     TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel)
);

CREATE INDEX IF NOT EXISTS idx_cp_thread
    ON checkpointer_checkpoints (checkpoint_id);
"""


class SQLiteSaver(BaseCheckpointSaver):
    """A :class:`BaseCheckpointSaver` backed by a SQLite file."""

    def __init__(self, db_path: Path | str, serde: Any | None = None) -> None:
        super().__init__(serde=serde or JsonPlusSerializer())
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._shared: sqlite3.Connection | None = None
        # A plain :memory: database cannot be reopened per thread, so those share one handle.
        self._is_memory = self.db_path == ":memory:"
        # Bootstrap on a throwaway connection, then close it before any real work begins.
        bootstrap = self._new_connection()
        try:
            bootstrap.executescript(SCHEMA)
            bootstrap.commit()
        finally:
            bootstrap.close()

    # ------------------------------------------------------------------ connections
    def _new_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30.0,
            # isolation_level=None keeps us in explicit transaction control, which is what
            # BEGIN IMMEDIATE below requires.
            isolation_level=None,
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @property
    def _conn(self) -> sqlite3.Connection:
        if self._is_memory:
            if self._shared is None:
                self._shared = self._new_connection()
            return self._shared
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._new_connection()
            self._local.conn = conn
        return conn

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _ident(config: dict[str, Any]) -> tuple[str, str]:
        conf = config.get("configurable") or {}
        return conf.get("thread_id", "") or "", conf.get("checkpoint_ns", "") or ""

    @staticmethod
    def _dump(serde: Any, value: Any) -> tuple[str, bytes]:
        return serde.dumps_typed(value)

    @staticmethod
    def _load(serde: Any, row: Any) -> Any:
        type_, blob = row
        return serde.loads_typed((type_, blob))

    # ------------------------------------------------------------------ sync API
    def put(
        self,
        config: dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> dict[str, Any]:
        thread_id, ns = self._ident(config)
        blob = self._dump(self.serde, checkpoint)
        meta_blob = self._dump(self.serde, metadata)
        # NOTE: langgraph's get_checkpoint_id() reads a RunnableConfig, not a Checkpoint.
        # A Checkpoint carries its own id under the "id" key.
        checkpoint_id = checkpoint["id"]
        parent = (config.get("configurable") or {}).get("checkpoint_id")

        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "INSERT OR REPLACE INTO checkpointer_checkpoints "
                "(checkpoint_id, parent_checkpoint_id, thread_id, checkpoint_ns, type, blob, metadata) "
                "VALUES (?,?,?,?,?,?,?)",
                (checkpoint_id, parent, thread_id, ns, blob[0], blob[1], meta_blob[1]),
            )
            conn.execute(
                "INSERT OR REPLACE INTO checkpointer_threads (thread_id, checkpoint_ns, checkpoint_id) "
                "VALUES (?,?,?)",
                (thread_id, ns, checkpoint_id),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ns,
                                 "checkpoint_id": checkpoint_id}}

    def put_writes(
        self,
        config: dict[str, Any],
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id, ns = self._ident(config)
        conf = config.get("configurable") or {}
        checkpoint_id = conf.get("checkpoint_id", "")
        rows = [
            (thread_id, ns, checkpoint_id, task_id, idx, channel,
             *self._dump(self.serde, value), task_path)
            for idx, (channel, value) in enumerate(writes)
        ]
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.executemany(
                "INSERT OR REPLACE INTO checkpointer_writes "
                "(thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, blob, task_path) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                rows,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def get_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:
        thread_id, ns = self._ident(config)
        checkpoint_id = (config.get("configurable") or {}).get("checkpoint_id")

        conn = self._conn
        if checkpoint_id:
            row = conn.execute(
                "SELECT checkpoint_id, parent_checkpoint_id, type, blob FROM checkpointer_checkpoints "
                "WHERE checkpoint_id = ?",
                (checkpoint_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT c.checkpoint_id, c.parent_checkpoint_id, c.type, c.blob "
                "FROM checkpointer_threads t "
                "JOIN checkpointer_checkpoints c ON c.checkpoint_id = t.checkpoint_id "
                "WHERE t.thread_id = ? AND t.checkpoint_ns = ?",
                (thread_id, ns),
            ).fetchone()
        return self._to_tuple(conn, row)

    def list(
        self,
        config: dict[str, Any] | None,
        *,
        filter: dict[str, Any] | None = None,  # noqa: A002 - matches base class signature
        before: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        thread_id, ns = self._ident(config or {})
        # History comes from checkpointer_checkpoints (every step), not from the
        # checkpointer_threads pointer (newest only).
        sql = (
            "SELECT checkpoint_id, parent_checkpoint_id, type, blob FROM checkpointer_checkpoints "
            "WHERE thread_id = ? AND checkpoint_ns = ? ORDER BY checkpoint_id DESC"
        )
        params: list[Any] = [thread_id, ns]
        if before is not None:
            before_id = (before.get("configurable") or {}).get("checkpoint_id")
            if before_id:
                sql += " AND c.checkpoint_id < ?"
                params.append(before_id)
        if limit:
            sql += " LIMIT ?"
            params.append(limit)

        conn = self._conn
        for row in conn.execute(sql, params).fetchall():
            item = self._to_tuple(conn, row)
            if item is not None:
                yield item

    # ------------------------------------------------------------------ async API
    async def aput(self, config: dict[str, Any], checkpoint: Checkpoint,
                   metadata: CheckpointMetadata, new_versions: ChannelVersions) -> dict[str, Any]:
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config: dict[str, Any], writes: Sequence[tuple[str, Any]],
                          task_id: str, task_path: str = "") -> None:
        self.put_writes(config, writes, task_id, task_path)

    async def aget_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:
        return self.get_tuple(config)

    async def alist(self, config: dict[str, Any] | None, *,
                    filter: dict[str, Any] | None = None,  # noqa: A002
                    before: dict[str, Any] | None = None,
                    limit: int | None = None) -> Iterator[CheckpointTuple]:
        for item in self.list(config, filter=filter, before=before, limit=limit):
            yield item

    # ------------------------------------------------------------------ internals
    def _to_tuple(self, conn: sqlite3.Connection, row: Any) -> CheckpointTuple | None:
        if row is None:
            return None
        checkpoint_id, parent_id, type_, blob = row
        checkpoint = self._load(self.serde, (type_, blob))
        metadata_row = conn.execute(
            "SELECT metadata FROM checkpointer_checkpoints WHERE checkpoint_id = ?", (checkpoint_id,)
        ).fetchone()
        metadata = self._load(self.serde, ("msgpack", metadata_row[0])) if metadata_row else {}
        writes: list[tuple[str, Any]] = []
        for channel, wtype, wblob in conn.execute(
            "SELECT channel, type, blob FROM checkpointer_writes "
            "WHERE checkpoint_id = ? ORDER BY task_id, idx",
            (checkpoint_id,),
        ):
            writes.append((channel, self._load(self.serde, (wtype, wblob))))
        return CheckpointTuple(checkpoint=checkpoint, metadata=metadata,
                               config={"configurable": {"thread_id": "", "checkpoint_ns": "",
                                                        "checkpoint_id": checkpoint_id}},
                               parent_config=({"configurable": {"thread_id": "", "checkpoint_ns": "",
                                                                 "checkpoint_id": parent_id}}
                                              if parent_id else None),
                               pending_writes=writes)

    def close(self) -> None:
        """Release the SQLite handle(s). Safe to call more than once."""
        if self._shared is not None:
            self._shared.close()
            self._shared = None
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


def open_checkpointer(db_path: Path | str) -> SQLiteSaver:
    """Convenience factory used by the pipeline and tests."""
    return SQLiteSaver(db_path)