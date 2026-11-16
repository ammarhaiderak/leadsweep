"""Apify-class Dataset Storage and Runs Engine (Phase B).
Provides:
- DatasetWriter: stores polymorphic items to SQLite and indexes into FTS5
- RunManager: creates, checkpoints, pauses, resumes, and finishes actor runs
"""
# NEW FEATURE (Phase B): Dataset & Run manager
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

log = logging.getLogger("leadsweep.core.datasets")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DatasetEngine:
    """Manages actor runs and datasets with SQLite WAL and FTS5 full-text indexing.

    Connections are short-lived and always closed: :meth:`_conn` is a context manager that
    commits on success, rolls back on error, and closes the handle in every case. Previously
    it returned a bare connection, and ``with conn:`` only ends the transaction - it never
    closes the file handle, which leaked one SQLite connection per API call.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            from leadsweep.config import get_settings
            self.db_path = str(get_settings().db_path)
        else:
            self.db_path = str(db_path)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
        except Exception:
            try:
                conn.rollback()
            except sqlite3.Error:  # pragma: no cover - rollback on an already-closed handle
                pass
            raise
        finally:
            conn.close()

    # --- Run Lifecycle Management
    def create_run(
        self,
        actor_name: str,
        input_data: dict[str, Any],
        run_id: str | None = None,
        user_email: str | None = None,
        user_id: str | None = None,
    ) -> tuple[str, str]:
        run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"
        dataset_id = f"ds_{uuid.uuid4().hex[:12]}"
        now = _now()

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO actor_runs(run_id, actor_name, status, input_json, dataset_id, started_at, items_count, user_email, user_id)
                VALUES (?, ?, 'running', ?, ?, ?, 0, ?, ?)
                """,
                (run_id, actor_name, json.dumps(input_data), dataset_id, now, user_email, user_id),
            )
            conn.commit()
        return run_id, dataset_id

    def update_checkpoint(self, run_id: str, checkpoint: dict[str, Any], items_count: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE actor_runs SET cursor_checkpoint = ?, items_count = ? WHERE run_id = ?",
                (json.dumps(checkpoint, default=str), items_count, run_id),
            )
            conn.commit()

    def update_run_status(self, run_id: str, status: str, error_detail: str | None = None) -> None:
        """Update run status dynamically (e.g. hitl_pending, running, paused, aborted)."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE actor_runs SET status = ?, error_detail = ? WHERE run_id = ?",
                (status, error_detail, run_id),
            )
            conn.commit()

    def finish_run(self, run_id: str, status: str = "succeeded", error_detail: str | None = None, items_count: int | None = None) -> None:
        now = _now()
        with self._conn() as conn:
            if items_count is not None:
                conn.execute(
                    "UPDATE actor_runs SET status = ?, finished_at = ?, error_detail = ?, items_count = ? WHERE run_id = ?",
                    (status, now, error_detail, items_count, run_id),
                )
            else:
                conn.execute(
                    "UPDATE actor_runs SET status = ?, finished_at = ?, error_detail = ? WHERE run_id = ?",
                    (status, now, error_detail, run_id),
                )
            conn.commit()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM actor_runs WHERE run_id = ?", (run_id,)).fetchone()
            return dict(row) if row else None

    def list_runs(self, limit: int = 50, user_email: str | None = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            # Platform owner sees all system runs; specific non-admin users see their isolated runs
            is_owner = False
            if user_email:
                ue = user_email.lower().strip()
                from leadsweep.config import get_settings
                owner = (get_settings().admin_email or "").strip().lower()
                if ue == "all" or (owner and ue == owner):
                    is_owner = True
                else:
                    try:
                        u_row = conn.execute("SELECT role FROM app_users WHERE lower(email) = ?", (ue,)).fetchone()
                        if u_row and u_row["role"] in ("owner", "admin"):
                            is_owner = True
                    except Exception:
                        pass

            if user_email and not is_owner:
                rows = conn.execute(
                    "SELECT * FROM actor_runs WHERE lower(COALESCE(user_email, '')) = ? ORDER BY started_at DESC LIMIT ?",
                    (user_email.lower().strip(), limit),
                ).fetchall()
            else:
                # UPDATED LOGIC: If is_owner or no user_email filter passed, return global runs
                rows = conn.execute(
                    "SELECT * FROM actor_runs ORDER BY started_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def delete_run(self, run_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute("SELECT dataset_id FROM actor_runs WHERE run_id = ?", (run_id,)).fetchone()
            if not row:
                return False
            dataset_id = row["dataset_id"]
            conn.execute("DELETE FROM dataset_items WHERE dataset_id = ?", (dataset_id,))
            conn.execute("DELETE FROM actor_runs WHERE run_id = ?", (run_id,))
            conn.commit()
            return True

    # --- Dataset Item Storage & FTS5
    def append_item(self, dataset_id: str, item_id: str, item_type: str, item_data: Any, dedup: bool = True) -> bool:
        """Store item with auto-deduplication. Returns True if inserted, False if duplicate skipped."""
        now = _now()
        data_dict = item_data.model_dump() if isinstance(item_data, BaseModel) else dict(item_data)
        if "created_at" in data_dict:
            ca = data_dict["created_at"]
            if hasattr(ca, "isoformat"):
                data_dict["created_at"] = ca.isoformat()
            elif isinstance(ca, str) and " " in ca and "T" not in ca:
                data_dict["created_at"] = ca.replace(" ", "T", 1)
        data_json = json.dumps(data_dict, default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o))

        text_content = ""
        if "text" in data_dict and data_dict["text"]:
            text_content = str(data_dict["text"])
        elif "bio" in data_dict and data_dict["bio"]:
            text_content = str(data_dict["bio"])

        composite_id = f"{dataset_id}:{item_id}"
        with self._conn() as conn:
            if dedup:
                # Deduplicate by (dataset_id, item_id) pair within dataset
                existing = conn.execute(
                    "SELECT 1 FROM dataset_items WHERE (id = ? OR id = ?) AND dataset_id = ?",
                    (composite_id, item_id, dataset_id),
                ).fetchone()
                if existing:
                    return False

            conn.execute(
                """
                INSERT OR IGNORE INTO dataset_items(id, dataset_id, item_type, data_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (composite_id, dataset_id, item_type, data_json, now),
            )
            if text_content:
                try:
                    conn.execute(
                        "INSERT INTO items_fts(item_id, content_text) VALUES (?, ?)",
                        (item_id, text_content),
                    )
                except sqlite3.OperationalError:
                    pass
            conn.commit()
            return True

    def get_dataset_items(self, dataset_id: str, limit: int = 1000, offset: int = 0) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM dataset_items WHERE dataset_id = ? ORDER BY created_at ASC LIMIT ? OFFSET ?",
                (dataset_id, limit, offset),
            ).fetchall()
            return [json.loads(r["data_json"]) for r in rows]

    def search_dataset_items(self, query: str, dataset_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Query full-text indexed items using FTS5 and return full item dictionaries."""
        with self._conn() as conn:
            sql = """
            SELECT di.data_json
            FROM items_fts fts
            JOIN dataset_items di ON (fts.item_id = di.id OR di.id = (di.dataset_id || ':' || fts.item_id))
            WHERE items_fts MATCH ?
            """
            params: list[Any] = [query]
            if dataset_id:
                sql += " AND di.dataset_id = ?"
                params.append(dataset_id)
            sql += " LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
            return [json.loads(r["data_json"]) for r in rows]

    def search_dataset_fts(self, query: str, limit: int = 50) -> list[str]:
        """Query full-text indexed items using SQLite FTS5."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT item_id FROM items_fts WHERE items_fts MATCH ? LIMIT ?",
                (query, limit),
            ).fetchall()
            return [r["item_id"].split(":")[-1] for r in rows]

    def vacuum_database(self) -> None:
        """Optimize and vacuum SQLite database to reclaim unindexed space.

        VACUUM cannot run inside a transaction, so isolation_level=None is required here;
        the default sqlite3 behaviour would otherwise raise "cannot VACUUM from within a
        transaction". No explicit transaction is needed because VACUUM is atomic itself.
        """
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0, isolation_level=None)
        try:
            conn.execute("VACUUM")
        finally:
            conn.close()
