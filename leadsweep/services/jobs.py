"""Background Job Worker and persistence service for asynchronous tasks."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from leadsweep.config import Settings, get_settings
from leadsweep.pipeline.store import Store

log = logging.getLogger("leadsweep.services.jobs")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobWorker:
    _instance: JobWorker | None = None

    def __init__(self, store: Store | Path | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if isinstance(store, (str, Path)):
            self.store = Store(Path(store))
        else:
            self.store = store or Store(self.settings.db_path)
        self._queue: asyncio.Queue[tuple[str, Callable[[Callable[[int, str], Awaitable[None]]], Awaitable[dict[str, Any]]]]] = asyncio.Queue()
        self._running_task: asyncio.Task | None = None
        self._listeners: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}

    @classmethod
    def get_instance(cls, store: Store | Path | None = None) -> JobWorker:
        if cls._instance is None:
            cls._instance = cls(store)
        return cls._instance

    @classmethod
    def cancel_running_worker(cls) -> None:
        """Class-level shutdown hook: cancel the loop only if a worker was ever created."""
        if cls._instance is not None:
            cls._instance.cancel_worker()

    def create_job(self, kind: str, params: dict[str, Any]) -> str:
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        now = _now()
        self.store.db.execute(
            """
            INSERT INTO jobs (id, kind, params, status, progress_percent, current_step, created_at)
            VALUES (?, ?, ?, 'queued', 0, 'Queued', ?)
            """,
            (job_id, kind, json.dumps(params), now),
        )
        self.store.db.commit()
        return job_id

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        row = self.store.db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["params"] = json.loads(d["params"]) if d.get("params") else {}
        d["result_summary"] = json.loads(d["result_summary"]) if d.get("result_summary") else None
        return d

    def list_jobs(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.store.db.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["params"] = json.loads(d["params"]) if d.get("params") else {}
            d["result_summary"] = json.loads(d["result_summary"]) if d.get("result_summary") else None
            out.append(d)
        return out

    async def enqueue(
        self,
        kind: str,
        params: dict[str, Any],
        handler: Callable[[Callable[[int, str], Awaitable[None]]], Awaitable[dict[str, Any]]],
    ) -> str:
        """Create job record and enqueue handler for background execution."""
        job_id = self.create_job(kind, params)
        await self._queue.put((job_id, handler))
        self.ensure_worker_running()
        return job_id

    def ensure_worker_running(self) -> None:
        if self._running_task is None or self._running_task.done():
            self._running_task = asyncio.create_task(self._run_loop())

    def cancel_worker(self) -> None:
        """Stop the background loop. Used by the API shutdown hook."""
        if self._running_task and not self._running_task.done():
            self._running_task.cancel()
        self._running_task = None

    async def _emit_progress(self, job_id: str, percent: int, step: str) -> None:
        self.store.db.execute(
            "UPDATE jobs SET progress_percent = ?, current_step = ? WHERE id = ?",
            (percent, step, job_id),
        )
        self.store.db.commit()
        data = {"job_id": job_id, "type": "progress", "percent": percent, "step": step}
        for q in self._listeners.get(job_id, []):
            await q.put(data)

    async def subscribe(self, job_id: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._listeners.setdefault(job_id, []).append(q)
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        listeners = self._listeners.get(job_id)
        if not listeners:
            return
        if q in listeners:
            listeners.remove(q)
        # Drop the key entirely once nobody is listening, otherwise _listeners grows
        # unbounded across the lifetime of a long-running server.
        if not listeners:
            self._listeners.pop(job_id, None)

    async def _run_loop(self) -> None:
        # Block on the queue rather than polling empty(): a job enqueued in the gap between
        # an empty() check and the loop exit would otherwise sit unprocessed forever.
        while True:
            job_id, handler = await self._queue.get()
            try:
                await self._process(job_id, handler)
            finally:
                self._queue.task_done()

    async def _process(
        self,
        job_id: str,
        handler: Callable[[Callable[[int, str], Awaitable[None]]], Awaitable[dict[str, Any]]],
    ) -> None:
        now = _now()
        self.store.db.execute(
            "UPDATE jobs SET status = 'running', started_at = ?, current_step = 'Starting' WHERE id = ?",
            (now, job_id),
        )
        self.store.db.commit()

        # Bound per invocation so the handler cannot mutate a later job's loop variables.
        job_id_ = job_id

        async def progress_cb(pct: int, msg: str) -> None:
            await self._emit_progress(job_id_, pct, msg)

        try:
            res = await handler(progress_cb)
            self.store.db.execute(
                """
                UPDATE jobs
                SET status = 'succeeded', progress_percent = 100, current_step = 'Completed',
                    result_summary = ?, finished_at = ?
                WHERE id = ?
                """,
                (json.dumps(res, default=str), _now(), job_id_),
            )
            self.store.db.commit()
            await self._emit_terminal(job_id_, {"job_id": job_id_, "type": "complete",
                                               "status": "succeeded", "result": res})
        except asyncio.CancelledError:
            self.store.db.execute(
                """
                UPDATE jobs
                SET status = 'cancelled', current_step = 'Cancelled', finished_at = ?
                WHERE id = ?
                """,
                (_now(), job_id_),
            )
            self.store.db.commit()
            await self._emit_terminal(job_id_, {"job_id": job_id_, "type": "error",
                                               "status": "cancelled", "error": "Job cancelled"})
            raise
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            log.exception("Job %s failed: %s\n%s", job_id_, e, tb)
            self.store.db.execute(
                """
                UPDATE jobs
                SET status = 'failed', current_step = 'Failed', error_code = ?, error_detail = ?, finished_at = ?
                WHERE id = ?
                """,
                (type(e).__name__, tb, _now(), job_id_),
            )
            self.store.db.commit()
            await self._emit_terminal(job_id_, {"job_id": job_id_, "type": "error",
                                               "status": "failed", "error": str(e)})

    async def _emit_terminal(self, job_id: str, event: dict[str, Any]) -> None:
        """Deliver a terminal event to every live listener of a job."""
        for q in list(self._listeners.get(job_id, [])):
            try:
                await q.put(event)
            except Exception:  # noqa: BLE001 - a dead listener must not fail the job
                log.debug("Could not deliver terminal event to a listener of job %s", job_id)
