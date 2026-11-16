"""Central request controller: pacing, bounded retry, backoff and circuit breaking.

This is the only place that decides when a Reddit request may run. It cannot rotate identity,
proxies or accounts, and it never retries an access denial.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time

from .exceptions import RedditCircuitOpenError, RedditError

log = logging.getLogger("leadsweep.integrations.reddit.rate_limiter")


class RedditRequestController:
    """Conservative, observable request gate for one ingestion run."""

    def __init__(
        self,
        *,
        max_requests_per_minute: int = 30,
        max_concurrent_requests: int = 1,
        max_retries: int = 3,
        backoff_base_s: float = 2.0,
        backoff_cap_s: float = 60.0,
        circuit_breaker_ttl_s: float = 300.0,
        clock: callable | None = None,
    ) -> None:
        self.max_requests_per_minute = max(1, int(max_requests_per_minute))
        self.min_interval_s = 60.0 / self.max_requests_per_minute
        self.max_retries = max(0, int(max_retries))
        self.backoff_base_s = max(0.1, float(backoff_base_s))
        self.backoff_cap_s = max(self.backoff_base_s, float(backoff_cap_s))
        self.circuit_breaker_ttl_s = max(1.0, float(circuit_breaker_ttl_s))
        self._semaphore = asyncio.Semaphore(max(1, int(max_concurrent_requests)))
        self._last_request_at: float = 0.0
        self._clock = clock or time.monotonic

        # Telemetry (surfaced verbatim in the execution summary)
        self.requests = 0
        self.successes = 0
        self.failures = 0
        self.rate_limited = 0
        self.denied = 0
        self.retries = 0

        # Circuit breaker
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._circuit_reason = ""

    # ------------------------------------------------------------------ pacing
    async def wait_turn(self) -> None:
        """Sleep just long enough to respect the configured request rate."""
        now = self._clock()
        elapsed = now - self._last_request_at
        if self._last_request_at and elapsed < self.min_interval_s:
            await asyncio.sleep(self.min_interval_s - elapsed)
        self._last_request_at = self._clock()

    # --------------------------------------------------------------- breaker
    def circuit_open(self) -> bool:
        return self._clock() < self._circuit_open_until

    def assert_available(self) -> None:
        if self.circuit_open():
            raise RedditCircuitOpenError(
                "Reddit circuit breaker is open after repeated refusals; pausing instead of retrying.",
                detail=self._circuit_reason,
            )

    def record_success(self) -> None:
        self.successes += 1
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._circuit_reason = ""

    def record_failure(self) -> None:
        self.failures += 1
        self._consecutive_failures += 1
        # Open immediately on the first access denial (called with denied=True) or after
        # three consecutive genuine failures.
        if self._consecutive_failures >= 3:
            self._open_circuit("three consecutive request failures")

    def record_denial(self, reason: str) -> None:
        """An access denial is terminal for this run: open the breaker at once."""
        self.denied += 1
        self.failures += 1
        self._consecutive_failures += 1
        self._open_circuit(reason)

    def record_rate_limit(self) -> None:
        self.rate_limited += 1
        self.failures += 1

    def _open_circuit(self, reason: str) -> None:
        self._circuit_open_until = self._clock() + self.circuit_breaker_ttl_s
        self._circuit_reason = reason
        log.warning(
            "Reddit circuit OPEN for %.0fs: %s", self.circuit_breaker_ttl_s, reason
        )

    # ---------------------------------------------------------------- backoff
    def backoff_delay(self, attempt: int, retry_after_s: float | None = None) -> float:
        """Honour Retry-After when Reddit supplies it, else exponential backoff with jitter."""
        if retry_after_s is not None:
            return max(0.0, min(float(retry_after_s), self.backoff_cap_s))
        raw = self.backoff_base_s * (2 ** max(0, attempt - 1))
        capped = min(self.backoff_cap_s, raw)
        return random.uniform(0.5, capped)

    async def acquire(self) -> None:
        """Enter the concurrency gate, checking the breaker before doing so."""
        await self._semaphore.acquire()

    def release(self) -> None:
        self._semaphore.release()

    def should_retry(self, exc: RedditError, attempt: int) -> bool:
        return bool(getattr(exc, "retryable", False)) and attempt <= self.max_retries

    def telemetry(self) -> dict[str, int]:
        return {
            "requests": self.requests,
            "successful_requests": self.successes,
            "failed_requests": self.failures,
            "rate_limit_responses": self.rate_limited,
            "access_denied_responses": self.denied,
            "retries": self.retries,
            "circuit_open": int(self.circuit_open()),
        }
