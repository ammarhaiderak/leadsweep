"""Cookie session pool V2 (Phase D): Anti-Ban, Sliding-Window Budgeting & Warmup Ramp.

Backwards-compatible drop-in for SessionPool with enhanced resilience:
- Warmup Schedule: Daily quota scales progressively based on session age.
- Hourly Budget Enforcement: Sliding 60-minute window request caps (default 120 req/hr).
- Automated Cooldown on 429: Exponential backoff with jitter (900s base, up to 7200s).
- Dead Session Alerter: Proactively marks unrecoverable sessions and alerts via webhook.
"""
# NEW FEATURE (Phase D): Anti-Ban & Session Pool V2
from __future__ import annotations

import json
import logging
import random
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .exceptions import NoSessionAvailableError

log = logging.getLogger("leadsweep.pool")

# Strong references to in-flight alert threads, so they are not garbage-collected mid-flight.
_ALERT_THREADS: set[threading.Thread] = set()


class SessionCreds(BaseModel):
    id: str
    auth_token: str
    ct0: str


class SessionMetrics(BaseModel):
    first_seen: float = Field(default_factory=time.time)
    last_used: float = 0.0
    cooldown_until: float = 0.0
    consecutive_429s: int = 0
    dead: bool = False
    reason: str = ""
    request_timestamps: list[float] = Field(default_factory=list)
    daily_request_count: int = 0
    last_day_reset: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d"))


class SessionPool:
    """Session Pool V2: Enhanced with sliding window, daily warmup, and exponential backoff.

    PHASE 7 note on blocking calls: :meth:`acquire`, :meth:`mark_cooldown` and
    :meth:`mark_dead` all run inside the scraper's asyncio event loop. Webhook delivery is
    therefore scheduled on the loop with :func:`asyncio.create_task` when one is running, and
    falls back to a synchronous call otherwise. Alerting must never stall scraping.
    """

    def __init__(
        self,
        sessions_file: Path | str,
        state_file: Path | str,
        webhook_url: str | None = None,
        hourly_budget: int = 120,
        warmup_days: int = 7,
        base_daily_quota: int = 50,
        max_daily_quota: int = 300,
    ) -> None:
        self.sessions_file = Path(sessions_file)
        self.state_file = Path(state_file)
        self.webhook_url = webhook_url
        self.hourly_budget = hourly_budget
        self.warmup_days = warmup_days
        self.base_daily_quota = base_daily_quota
        self.max_daily_quota = max_daily_quota

        self.sessions = []
        if self.sessions_file.exists():
            try:
                raw = json.loads(self.sessions_file.read_text(encoding="utf-8"))
                sessions_raw = raw.get("sessions", [])
                if not sessions_raw:
                    raise ValueError(f"sessions_file '{self.sessions_file}' contains no sessions")
                self.sessions = [SessionCreds(**s) for s in sessions_raw]
            except ValueError:
                raise
            except Exception as e:
                log.warning("Could not read sessions file %s: %s", self.sessions_file, e)
        else:
            log.info("sessions_file '%s' not present; SessionPool running in zero-session mode.", self.sessions_file)

        self.state: dict[str, SessionMetrics] = {}
        if self.state_file.exists():
            try:
                raw_state = json.loads(self.state_file.read_text(encoding="utf-8"))
                for sid, data in raw_state.items():
                    if isinstance(data, dict):
                        self.state[sid] = SessionMetrics(**data)
            except Exception as e:
                log.warning("Could not read existing state file, initializing fresh: %s", e)

        # Initialize defaults for new sessions
        now = time.time()
        for s in self.sessions:
            if s.id not in self.state:
                self.state[s.id] = SessionMetrics(first_seen=now)

    def _save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        dump_dict = {sid: m.model_dump() for sid, m in self.state.items()}
        self.state_file.write_text(json.dumps(dump_dict, indent=2), encoding="utf-8")

    def get_effective_daily_quota(self, sid: str) -> int:
        """Warmup schedule: ramp quota over warmup_days from base to max."""
        m = self.state[sid]
        age_days = max(0, int((time.time() - m.first_seen) / 86400))
        if age_days >= self.warmup_days:
            return self.max_daily_quota
        fraction = age_days / float(self.warmup_days)
        return int(self.base_daily_quota + fraction * (self.max_daily_quota - self.base_daily_quota))

    def _prune_sliding_window(self, sid: str) -> None:
        """Remove timestamps older than 1 hour and reset daily quota if day changed."""
        now = time.time()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        m = self.state[sid]

        if m.last_day_reset != today:
            m.last_day_reset = today
            m.daily_request_count = 0

        cutoff = now - 3600.0
        m.request_timestamps = [t for t in m.request_timestamps if t > cutoff]

    def _send_alert(self, event_type: str, message: str, details: dict | None = None) -> None:
        """Fire-and-forget alert delivery. Never raises, never blocks the event loop.

        PHASE 7. A dedicated daemon thread is used rather than an asyncio task: a task would
        have to be tied to the running loop, and if that loop closes (short-lived CLI runs,
        tests) the in-flight webhook delivery dies with an "Event loop is closed" error. A
        plain thread has no such coupling and keeps 429/dead-session handling off the hot path.
        """
        webhook = self.webhook_url
        if not webhook:
            return
        try:
            from .resilience import notify_alert

            thread = threading.Thread(
                target=notify_alert,
                args=(webhook, event_type, message, details),
                name=f"leadsweep-alert-{event_type.lower()}",
                daemon=True,
            )
            thread.start()
            _ALERT_THREADS.add(thread)
            thread.add_done_callback(lambda t: _ALERT_THREADS.discard(t))
        except Exception:  # noqa: BLE001 - alerting must never break scraping
            log.debug("Could not dispatch alert %s", event_type, exc_info=True)

    def acquire(self) -> SessionCreds:
        """Acquire optimal session respecting cooldowns, hourly budgets, and daily warmup."""
        now = time.time()
        live = [s for s in self.sessions if not self.state[s.id].dead]
        if not live:
            msg = "All sessions are dead — update cookies in sessions.json"
            self._send_alert("SESSIONS_ALL_DEAD", msg)
            raise NoSessionAvailableError(msg)

        ready: list[SessionCreds] = []
        cooling: list[float] = []

        for s in live:
            self._prune_sliding_window(s.id)
            m = self.state[s.id]

            # 1. Cooldown check
            if m.cooldown_until > now:
                cooling.append(m.cooldown_until - now)
                continue

            # 2. Hourly sliding window check
            if len(m.request_timestamps) >= self.hourly_budget:
                oldest_in_window = min(m.request_timestamps)
                wait_needed = max(1.0, 3600.0 - (now - oldest_in_window))
                cooling.append(wait_needed)
                continue

            # 3. Daily warmup quota check
            quota = self.get_effective_daily_quota(s.id)
            if m.daily_request_count >= quota:
                log.warning("Session %s reached warmup daily quota (%d reqs)", s.id, quota)
                cooling.append(3600.0)
                continue

            ready.append(s)

        if not ready:
            min_wait = min(cooling) if cooling else 60.0
            raise NoSessionAvailableError(f"All sessions throttled or cooling down; next ready in {min_wait:.0f}s")

        pick = min(ready, key=lambda s: self.state[s.id].last_used)
        log.info(
            "Acquired session %s (hourly: %d/%d, daily: %d/%d)",
            pick.id,
            len(self.state[pick.id].request_timestamps),
            self.hourly_budget,
            self.state[pick.id].daily_request_count,
            self.get_effective_daily_quota(pick.id),
        )
        return pick

    def mark_used(self, sid: str) -> None:
        """Register successful request timestamp and update LRU."""
        now = time.time()
        self._prune_sliding_window(sid)
        m = self.state[sid]
        m.last_used = now
        m.request_timestamps.append(now)
        m.daily_request_count += 1
        m.consecutive_429s = 0
        self._save()

    def mark_cooldown(self, sid: str, seconds: int = 900) -> None:
        """Quarantine session with exponential backoff on consecutive 429s."""
        m = self.state[sid]
        m.consecutive_429s += 1
        multiplier = 2 ** min(3, m.consecutive_429s - 1)
        jitter_s = random.uniform(5.0, 30.0)
        cooldown_s = min(7200, int(seconds * multiplier + jitter_s))

        m.cooldown_until = time.time() + cooldown_s
        m.last_used = time.time()
        log.warning("Session %s cooling down for %ds (consecutive_429s=%d)", sid, cooldown_s, m.consecutive_429s)
        self._save()

        if m.consecutive_429s >= 2:
            self._send_alert(
                "SESSION_RATE_LIMITED",
                f"Session {sid} received {m.consecutive_429s} consecutive 429 rate limits",
                {"cooldown_seconds": cooldown_s},
            )

    def mark_dead(self, sid: str, reason: str) -> None:
        """Permanently retire invalid session and trigger immediate notification."""
        m = self.state[sid]
        m.dead = True
        m.reason = reason
        log.error("Session %s marked DEAD: %s", sid, reason)
        self._save()
        self._send_alert("SESSION_DEAD", f"Session {sid} marked DEAD: {reason}")

    def summary(self) -> list[dict[str, Any]]:
        now = time.time()
        out = []
        for s in self.sessions:
            self._prune_sliding_window(s.id)
            m = self.state[s.id]
            out.append({
                "id": s.id,
                "dead": m.dead,
                "cooldown_s": max(0, int(m.cooldown_until - now)),
                "hourly_requests": len(m.request_timestamps),
                "daily_requests": m.daily_request_count,
                "daily_quota": self.get_effective_daily_quota(s.id),
                "consecutive_429s": m.consecutive_429s,
                "reason": m.reason,
            })
        return out
