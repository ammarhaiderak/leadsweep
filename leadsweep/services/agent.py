"""Autonomous HITL Agent — the canonical agent implementation (PHASE 2 / PHASE 3).

This module is the single source of truth for agent execution. It supersedes the earlier
``leadsweep/core/agent.py`` prototype, which planned tasks but never executed them.

What it does
------------
1. Resolve a natural-language prompt into an actor plan (``plan`` - deterministic keyword
   routing, not an LLM, so planning cannot hallucinate or cost tokens).
2. Pre-flight estimate (items, runtime, risk, $0 cost).
3. Evaluate the HITL safety gate; pause the run when policy requires a human decision.
4. Execute the actor, streaming progress and persisting each item to a dataset.
5. Resume after approval, abort on rejection, and always release its in-memory state.

Concurrency and lifetime
------------------------
``TaskRegistry`` holds the live task state and the ``asyncio.Event`` each paused task awaits.
Every entry is removed in a ``finally`` block, so neither the registry nor the event map can
grow without bound. Decisions are also written to the ``hitl_decisions`` table for audit, and
the authoritative status of a run always lives in ``actor_runs``.

Persistence boundary (deliberate, and documented rather than implied): the *decision record*
and the *run status* are persistent, but the live coroutine and its resume event are
in-process. A process restart abandons in-flight tasks; their runs stay in ``hitl_pending``
and can still be resolved from the database via the API/CLI, which then reports that no live
execution is attached rather than pretending to resume.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from pydantic import BaseModel, Field

from leadsweep.actors import ActorRegistry
from leadsweep.actors.base import Actor, ActorEstimate, RunContext
from leadsweep.config import get_settings
from leadsweep.core.datasets import DatasetEngine
from leadsweep.core.hitl import HITLGuard, PolicyEvaluation

log = logging.getLogger("leadsweep.services.agent")

# Fallbacks used only when a prompt names no account. They are planning defaults, not demo
# fixtures, and never leak into stored data: the actor re-validates the handle it receives.
_DEFAULT_HANDLES = ("", "")
_DEFAULT_REPLY_TWEET_ID = ""


class AgentState(BaseModel):
    task_id: str
    run_id: str | None = None
    dataset_id: str | None = None
    actor_name: str | None = None
    input_data: dict[str, Any] = Field(default_factory=dict)
    status: str = "initialized"  # initialized | planning | hitl_paused | running | completed | failed | rejected
    paused_reason: str | None = None
    reasons: list[str] = Field(default_factory=list)
    items_scraped: int = 0
    created_at: float = Field(default_factory=time.time)
    feedback_history: list[dict[str, Any]] = Field(default_factory=list)


@dataclass
class _LiveTask:
    """One in-flight task: its state plus the event it blocks on while awaiting a human."""

    state: AgentState
    resume_event: asyncio.Event = field(default_factory=asyncio.Event)
    decided: bool = False  # guarantees a second decision can never resume a run twice


class TaskRegistry:
    """In-process registry of live agent tasks.

    Bounded by design: :meth:`release` is called from a ``finally`` in the executor, and
    :meth:`prune_finished` drops anything abandoned (for example by a crashed coroutine).
    """

    def __init__(self) -> None:
        self._tasks: dict[str, _LiveTask] = {}

    def register(self, state: AgentState) -> _LiveTask:
        task = _LiveTask(state=state)
        self._tasks[state.task_id] = task
        return task

    def get(self, key: str) -> _LiveTask | None:
        """Look a task up by task_id, falling back to run_id."""
        found = self._tasks.get(key)
        if found is not None:
            return found
        for task in self._tasks.values():
            if task.state.run_id and task.state.run_id == key:
                return task
        return None

    def release(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)

    def live_task_ids(self) -> list[str]:
        return sorted(self._tasks)

    def __len__(self) -> int:
        return len(self._tasks)

    def prune_finished(self, max_age_s: float = 3600.0) -> int:
        """Drop terminal tasks older than ``max_age_s``. Returns how many were removed."""
        now = time.time()
        terminal = {"completed", "failed", "rejected", "aborted"}
        stale = [
            tid for tid, task in self._tasks.items()
            if task.state.status in terminal and (now - task.state.created_at) > max_age_s
        ]
        for tid in stale:
            self._tasks.pop(tid, None)
        return len(stale)


# Single process-wide registry. Module level because the API resolves decisions by id from a
# different request/task than the one that created the coroutine.
REGISTRY = TaskRegistry()


def _record_decision(run_id: str | None, action: str, operator: str, note: str | None,
                     source: str) -> None:
    """Persist a HITL decision for audit. Never fails the request."""
    if not run_id:
        return
    try:
        from leadsweep.pipeline.store import Store

        store = Store(get_settings().db_path)
        try:
            store.db.execute(
                """
                CREATE TABLE IF NOT EXISTS hitl_decisions (
                  id TEXT PRIMARY KEY,
                  run_id TEXT NOT NULL,
                  task_id TEXT,
                  action TEXT NOT NULL,
                  operator TEXT NOT NULL,
                  note TEXT,
                  source TEXT NOT NULL,
                  created_at TEXT NOT NULL
                )
                """
            )
            store.db.execute(
                "INSERT INTO hitl_decisions (id, run_id, task_id, action, operator, note, source, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (f"hdl_{uuid.uuid4().hex[:12]}", run_id, None, action, operator, note, source,
                 datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
            store.commit()
        finally:
            store.close()
    except Exception as exc:  # noqa: BLE001 - auditing must never break the decision path
        log.warning("Could not record HITL decision audit row: %s", exc)


def decide_run(
    key: str,
    action: str,
    operator: str = "admin",
    note: str | None = None,
    source: str = "api",
) -> dict[str, Any]:
    """Resolve a paused run. The single decision path used by REST, CLI and MCP.

    Works in two situations:

    * A live task is waiting in this process -> update the database *and* wake the coroutine
      so it resumes (or aborts) immediately.
    * No live task is attached (different process, restart, or the run was created directly)
      -> still resolve the durable run state, and say so explicitly in the response.

    Idempotent: approving twice, or approving an already-rejected run, raises rather than
    resuming a second time.
    """
    if action not in ("approve", "reject"):
        raise ValueError("action must be 'approve' or 'reject'")

    settings = get_settings()
    engine = DatasetEngine(settings.db_path)
    guard = HITLGuard(engine=engine, webhook_url=settings.webhook_url)
    task = REGISTRY.get(key)

    try:
        if task is not None:
            if task.decided:
                raise ValueError(
                    f"Task '{task.state.task_id}' already received a '{task.state.status}' decision"
                )
            run_id = task.state.run_id
            if not run_id:
                raise ValueError(f"Task '{task.state.task_id}' has no run to decide on yet")

            if action == "approve":
                guard.approve_run(run_id=run_id, operator=operator)
                task.state.status = "running"
                task.state.paused_reason = note
            else:
                guard.reject_run(run_id=run_id, operator=operator,
                                 reason=note or "Rejected by operator")
                task.state.status = "rejected"
                task.state.paused_reason = note or "Rejected by operator"

            task.state.feedback_history.append(
                {"action": action, "operator": operator, "note": note, "source": source, "at": time.time()}
            )
            task.decided = True
            task.resume_event.set()
            _record_decision(run_id, action, operator, note, source)

            log.info("HITL %s for task=%s run=%s by %s (%s)",
                     action, task.state.task_id, run_id, operator, source)
            return {
                "task_id": task.state.task_id,
                "run_id": run_id,
                "status": "approved" if action == "approve" else "rejected",
                "resumed_live_task": True,
                "message": "Agent execution resumed." if action == "approve" else "Agent task aborted.",
            }

        # No live task: resolve durable state only.
        run = engine.get_run(key)
        if not run:
            raise ValueError(f"Task or Run '{key}' not found in active agent memory")
        if action == "approve":
            result = guard.approve_run(run_id=key, operator=operator)
        else:
            result = guard.reject_run(run_id=key, operator=operator, reason=note or "Rejected by operator")
        _record_decision(key, action, operator, note, source)
        return {
            "task_id": None,
            "run_id": key,
            "status": "approved" if action == "approve" else "rejected",
            "resumed_live_task": False,
            "detail": result,
            "message": "Run state updated. No in-process agent is attached to this run "
                       "(it was created by another process or a previous restart), so no "
                       "coroutine resumed; re-run the task to execute it.",
        }
    finally:
        # DatasetEngine opens short-lived connections internally, so there is no handle to close.
        pass


class HITLAutonomousAgent:
    """Production agent: plans, gates on human approval, executes actors, persists datasets."""

    def __init__(
        self,
        engine: DatasetEngine | None = None,
        guard: HITLGuard | None = None,
    ) -> None:
        settings = get_settings()
        self.engine = engine or DatasetEngine(settings.db_path)
        self.guard = guard or HITLGuard(
            engine=self.engine,
            webhook_url=settings.webhook_url,
            max_auto_items=50,
            risk_threshold="medium",
        )

    # ------------------------------------------------------------------ planning
    def plan(self, prompt: str) -> dict[str, Any]:
        """Map a natural-language request onto an actor and validated input.

        Deterministic keyword routing on purpose: intent parsing here must be reproducible
        and free. Ambiguity is resolved by the HITL gate and by actor input validation,
        not by a language model guessing.
        """
        p = prompt.lower()
        words = prompt.replace("@", " @").split()

        def handle(default: str) -> str:
            for w in words:
                if w.startswith("@") and len(w) > 1:
                    return w.lstrip("@").strip(",.!?:;\"'")
            return default

        def count(default: int, cap: int) -> int:
            for w in words:
                if w.isdigit():
                    try:
                        n = int(w)
                    except ValueError:
                        continue
                    if 1 <= n <= cap:
                        return n
            return default

        def tweet_id() -> str:
            for w in words:
                if w.isdigit() and len(w) > 9:
                    return w
            # No usable id in the prompt: leave it empty so actor validation rejects the
            # request loudly instead of silently scraping an unrelated hardcoded tweet.
            return _DEFAULT_REPLY_TWEET_ID

        # Order matters: more specific intents are tested first.
        if "follower" in p:
            h, n = handle(_DEFAULT_HANDLES[0]), count(30, 500)
            return {"actor": "followers", "input": {"handle": h, "max_results": n},
                    "explanation": f"Scraping followers network of @{h} (Target: {n} users).",
                    "requires_review_if": n > 50}

        if any(k in p for k in ("user", "timeline", "tweets from @", "profile tweets")):
            h, n = handle(_DEFAULT_HANDLES[1]), count(20, 200)
            return {"actor": "user_tweets", "input": {"handle": h, "max_results": n},
                    "explanation": f"Harvesting recent author tweets from @{h} (Target: {n} tweets).",
                    "requires_review_if": False}

        if any(k in p for k in ("reply", "replies", "thread")):
            tid = tweet_id()
            return {"actor": "replies", "input": {"tweet_id": tid, "max_results": 25},
                    "explanation": f"Extracting discussion thread replies under Tweet ID {tid or '(none supplied)'}.",
                    "requires_review_if": False}

        if any(k in p for k in ("liker", "engager", "who liked")):
            tid = tweet_id()
            return {"actor": "likers", "input": {"tweet_id": tid, "max_results": 20},
                    "explanation": f"Identifying engaging audience profiles for Tweet ID {tid or '(none supplied)'}.",
                    "requires_review_if": False}

        if any(k in p for k in ("bio of @", "who is @", "profile of @")):
            h = handle("")
            return {"actor": "profile", "input": {"handle": h},
                    "explanation": f"Inspecting profile metadata and audience stats for @{h}.",
                    "requires_review_if": False}

        # Default: strip conversational filler and run a live keyword search.
        clean = prompt
        for sw in ("find", "search for", "search", "scrape", "extract", "get me", "get",
                   "look for", "show me", "show", "please", "with high intent", "high intent", "me"):
            clean = re.sub(rf"(?i)\b{re.escape(sw)}\b", " ", clean)
        clean = " ".join(clean.split()).strip(" -:,.")
        n = count(20, 300)
        return {"actor": "search", "input": {"query": clean, "max_results": n, "tab": "live"},
                "explanation": f"Harvesting live X posts matching '{clean}' (Target: {n} items).",
                "requires_review_if": n > 60}

    # ------------------------------------------------------------------ execution
    async def execute_stream(
        self,
        prompt: str,
        task_id: str | None = None,
        scraper: Any | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream planning, gating and execution events. Always releases registry state.

        ``scraper`` optionally injects a caller-owned :class:`XScraper` shared across the
        whole run (PHASE 5). Pass one to avoid launching a browser per actor; omit it and
        each actor manages its own, which is the historical behaviour.
        """
        settings = get_settings()
        task_id = task_id or f"task_{uuid.uuid4().hex[:10]}"
        state = AgentState(task_id=task_id, status="planning")
        live = REGISTRY.register(state)

        try:
            yield {"step": "planning", "task_id": task_id,
                   "message": f"Analyzing task objective: '{prompt}'"}

            plan = self.plan(prompt)
            actor_name = plan["actor"]
            input_data = plan["input"]
            state.actor_name = actor_name
            state.input_data = input_data

            yield {"step": "intent_resolved", "task_id": task_id, "actor": actor_name,
                   "explanation": plan["explanation"], "input": input_data,
                   "message": f"Plan Formulated: Actor '{actor_name}' - {plan['explanation']}"}

            try:
                actor: Actor[Any, Any] = ActorRegistry.get(actor_name)
            except Exception as exc:  # noqa: BLE001 - surface as a stream event, not a traceback
                yield {"step": "error", "task_id": task_id, "message": f"Actor lookup failed: {exc}"}
                state.status = "failed"
                return

            # Actor schemas are the single validation point; a bad plan fails here, loudly.
            try:
                validated_input = actor.input_schema(**input_data)
            except Exception as exc:  # noqa: BLE001
                yield {"step": "error", "task_id": task_id,
                       "message": f"Invalid input for actor '{actor_name}': {exc}"}
                state.status = "failed"
                return

            estimate: ActorEstimate = actor.estimate(validated_input)
            yield {"step": "preflight_estimate", "task_id": task_id,
                   "estimated_items": estimate.estimated_items,
                   "estimated_seconds": estimate.estimated_seconds,
                   "risk_level": estimate.risk_level,
                   "cost": f"${estimate.cost_dollars:.2f} (Local zero-cost engine)",
                   "message": (f"Pre-flight Estimate: ~{estimate.estimated_items} items, "
                               f"anti-ban risk: {estimate.risk_level.upper()}, "
                               f"runtime: {estimate.estimated_seconds:.1f}s ($0 cost).")}

            run_id, dataset_id = self.engine.create_run(actor_name, input_data)
            state.run_id = run_id
            state.dataset_id = dataset_id
            log.info("Agent task=%s run=%s actor=%s", task_id, run_id, actor_name)

            policy: PolicyEvaluation = self.guard.evaluate_request(actor, validated_input)
            needs_review = bool(policy.requires_approval or plan.get("requires_review_if"))

            if needs_review:
                if not live.resume_event.is_set():
                    state.status = "hitl_paused"
                    state.reasons = policy.reasons or ["Operation exceeds standard automatic ceiling"]
                    self.guard.trigger_guard(run_id, actor_name, state.reasons, input_data)

                    yield {"step": "hitl_paused", "task_id": task_id, "run_id": run_id,
                           "dataset_id": dataset_id, "status": "hitl_pending",
                           "reasons": state.reasons,
                           "timeout_s": settings.hitl_timeout_s,
                           "message": (f"[HUMAN-IN-THE-LOOP] Run {run_id} paused for review.\n"
                                       f"Risk: {policy.risk_level.upper()}. "
                                       f"Reason: {', '.join(state.reasons)}.\n"
                                       f"Awaiting human approval or rejection."),
                           "action_required": "Operator must Approve or Reject via UI/API/CLI"}

                    timeout_s = settings.hitl_timeout_s
                    try:
                        await asyncio.wait_for(live.resume_event.wait(), timeout=timeout_s)
                    except asyncio.TimeoutError:
                        state.status = "aborted"
                        self.engine.finish_run(run_id, status="aborted",
                                               error_detail="Timed out waiting for HITL approval")
                        yield {"step": "hitl_timeout", "task_id": task_id, "run_id": run_id,
                               "message": f"HITL decision timed out after {timeout_s}s. Run aborted."}
                        return

                    if state.status == "rejected":
                        yield {"step": "hitl_rejected", "task_id": task_id, "run_id": run_id,
                               "message": (f"Run {run_id} rejected by operator: "
                                           f"{state.paused_reason or 'no reason provided'}")}
                        return

                    yield {"step": "hitl_resumed", "task_id": task_id, "run_id": run_id,
                           "message": "Human approval received. Resuming autonomous scraping workflow..."}

            state.status = "running"
            yield {"step": "execution_started", "task_id": task_id, "run_id": run_id,
                   "dataset_id": dataset_id,
                   "message": f"Starting scraping pipeline for actor '{actor_name}'..."}

            ctx = RunContext(run_id=run_id, dataset_id=dataset_id, scraper=scraper)
            count = 0
            try:
                async for item in actor.run(validated_input, ctx):
                    count += 1
                    state.items_scraped = count
                    item_id = str(getattr(item, "id", None) or getattr(item, "rest_id", None)
                                  or uuid.uuid4())
                    self.engine.append_item(dataset_id=dataset_id, item_id=item_id,
                                            item_type=actor_name, item_data=item, dedup=True)
                    self.engine.update_checkpoint(run_id, ctx.checkpoint, count)

                    if count % 5 == 0 or count == 1:
                        yield {"step": "scraping_progress", "task_id": task_id, "run_id": run_id,
                               "dataset_id": dataset_id, "items_collected": count,
                               "message": f"Scraped {count} items into dataset {dataset_id}..."}

                self.engine.finish_run(run_id, status="succeeded")
                state.status = "completed"
                yield {"step": "execution_completed", "task_id": task_id, "run_id": run_id,
                       "dataset_id": dataset_id, "total_items": count,
                       "export_urls": {
                           "json": f"/api/datasets/{dataset_id}/export?format=json",
                           "csv": f"/api/datasets/{dataset_id}/export?format=csv",
                           "jsonl": f"/api/datasets/{dataset_id}/export?format=jsonl",
                           "xml": f"/api/datasets/{dataset_id}/export?format=xml",
                       },
                       "message": (f"Job completed successfully. Scraped {count} items into "
                                   f"dataset '{dataset_id}'. Ready for instant export.")}
            except asyncio.CancelledError:
                self.engine.finish_run(run_id, status="aborted", error_detail="Client disconnected")
                state.status = "aborted"
                raise
            except Exception as exc:  # noqa: BLE001 - report, never leak a stack trace to the client
                detail = str(exc).strip() or type(exc).__name__
                log.exception("Actor run %s failed", run_id)
                self.engine.finish_run(run_id, status="failed", error_detail=detail)
                state.status = "failed"
                yield {"step": "execution_failed", "task_id": task_id, "run_id": run_id,
                       "error": detail, "message": f"Execution halted: {detail}"}
        finally:
            # Unconditional: a crashed or completed task must never leak registry state.
            REGISTRY.release(task_id)

    # ------------------------------------------------------------------ decisions
    @classmethod
    def submit_feedback(cls, task_id: str, action: str, operator: str = "admin",
                        note: str | None = None) -> dict[str, Any]:
        """Backwards-compatible wrapper around :func:`decide_run`."""
        return decide_run(task_id, action=action, operator=operator, note=note, source="agent_feedback_api")

    @staticmethod
    def live_task_ids() -> list[str]:
        return REGISTRY.live_task_ids()

    @staticmethod
    def prune(max_age_s: float = 3600.0) -> int:
        return REGISTRY.prune_finished(max_age_s)