"""Persistent Database-Backed Scheduler for LeadSweep.

Architecture (PHASE 10 & 33, 34, 35, 75):
- Persistent in database (survives server and system restarts).
- Calculates next_run_at with timezone awareness (e.g. 10:00 AM in Asia/Karachi or user timezone).
- Executes background incremental scrape and updates last_run_at and next_run_at.
- Recovers queued/missed jobs on startup.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
from typing import Any
from zoneinfo import ZoneInfo

from leadsweep.config import get_settings
from leadsweep.pipeline.store import Store

log = logging.getLogger("leadsweep.scheduler")


def calculate_next_run(
    schedule_time_str: str = "10:00",
    tz_name: str = "Asia/Karachi",
    frequency: str = "daily",
    from_dt: datetime.datetime | None = None,
) -> datetime.datetime:
    """Calculate the next execution timestamp (default 10:00 AM in target timezone)."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")

    now = from_dt or datetime.datetime.now(tz)
    try:
        hour, minute = map(int, schedule_time_str.split(":"))
    except Exception:
        hour, minute = 10, 0

    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)

    return target


class PersistentScheduler:
    """Background service polling SQLite/Postgres scheduled_jobs and running pending tasks."""

    _instance: PersistentScheduler | None = None
    _task: asyncio.Task | None = None

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or get_settings().db_path
        self._running = False

    @classmethod
    def get_instance(cls) -> PersistentScheduler:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._poll_loop())
            log.info("PersistentScheduler started successfully.")

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        log.info("PersistentScheduler stopped.")

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await self._execute_due_jobs()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Scheduler poll error: %s", e)
            await asyncio.sleep(60.0)

    async def _execute_due_jobs(self) -> None:
        """Find jobs where next_run_at <= now, trigger scraping run, and reschedule."""
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        store = Store(self.db_path)
        try:
            sql = """
                SELECT id, user_id, name, platform, query, schedule_time, timezone, frequency, items_per_run
                FROM scheduled_jobs
                WHERE enabled = 1 AND next_run_at <= ?
            """
            due = store.db.execute(sql, (now_utc,)).fetchall()
            for job in due:
                job_id = job["id"]
                platform = job["platform"]
                query = job["query"]
                sch_time = job["schedule_time"]
                tz_name = job["timezone"]
                freq = job["frequency"]
                limit_items = job["items_per_run"]

                log.info("Executing due scheduled job %s ('%s' on %s)", job_id, query, platform)

                # Compute new next_run_at
                next_dt = calculate_next_run(sch_time, tz_name, freq)
                store.db.execute(
                    """
                    UPDATE scheduled_jobs
                    SET last_run_at = ?, next_run_at = ?, last_status = 'running'
                    WHERE id = ?
                    """,
                    (now_utc, next_dt.isoformat(), job_id),
                )
                store.db.commit()

                # Dispatch scrape run via Actor engine
                from leadsweep.core.datasets import DatasetEngine
                from leadsweep.services.jobs import JobWorker
                engine = DatasetEngine(self.db_path)
                run_id, dataset_id = engine.create_run(
                    actor_name="search",
                    input_data={"platform": platform, "query": query, "max_results": limit_items},
                )
                
                # Mark job completed
                store.db.execute("UPDATE scheduled_jobs SET last_status = 'completed' WHERE id = ?", (job_id,))
                store.db.commit()

        finally:
            store.close()
