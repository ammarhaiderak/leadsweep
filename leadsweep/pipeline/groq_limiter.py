"""Groq free-tier pacing, token estimation, rate-limit classification, and retry management.

Differentiates per-minute (TPM/OTPM) 429 limits from true daily (TPD) quota exhaustion.
Enforces safe token window estimation, exponential jitter backoff, and bounded concurrency.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any

log = logging.getLogger("leadsweep.pipeline.groq_limiter")


class DailyQuotaExhaustedError(RuntimeError):
    """Raised when Groq daily quota (TPD/RPD) has been completely exhausted."""
    def __init__(self, message: str, reset_time: str = ""):
        super().__init__(message)
        self.reset_time = reset_time


def parse_groq_reset_seconds(val: str | int | float | None) -> float:
    """Parses Groq reset interval string or number into seconds.
    
    Supports:
      '1.85s' -> 1.85
      '500ms' -> 0.5
      '1m30s' -> 90.0
      '4h32m10s' -> 16330.0
      '60' -> 60.0
    """
    if not val:
        return 2.0
    if isinstance(val, (int, float)):
        return max(0.001, float(val))
    val_str = str(val).strip()
    try:
        return max(0.001, float(val_str))
    except ValueError:
        pass

    total = 0.0
    matched = False

    h = re.search(r'(\d+(?:\.\d+)?)\s*h', val_str, re.IGNORECASE)
    if h:
        total += float(h.group(1)) * 3600.0
        matched = True
    m = re.search(r'(\d+(?:\.\d+)?)\s*m(?!s)', val_str, re.IGNORECASE)
    if m:
        total += float(m.group(1)) * 60.0
        matched = True
    s = re.search(r'(\d+(?:\.\d+)?)\s*s(?!m)', val_str, re.IGNORECASE)
    if s:
        total += float(s.group(1))
        matched = True
    ms = re.search(r'(\d+(?:\.\d+)?)\s*ms', val_str, re.IGNORECASE)
    if ms:
        total += float(ms.group(1)) / 1000.0
        matched = True

    return max(0.001, total) if matched else 2.0


def classify_groq_rate_limit(err: Exception) -> tuple[str, str, float]:
    """Classifies a Groq error into ('tpd', reset_detail, wait_s), ('tpm', reset_detail, wait_s), or ('other', msg, 0.0).

    Returns:
      (kind, status_detail, wait_seconds)
    """
    err_str = str(err)
    headers: dict[str, str] = {}
    if hasattr(err, "response") and getattr(err.response, "headers", None):
        headers = {str(k).lower(): str(v) for k, v in err.response.headers.items()}

    # Check for TPD (Tokens Per Day) or RPD (Requests Per Day)
    is_tpd = (
        "tokens per day" in err_str.lower()
        or "requests per day" in err_str.lower()
        or "(tpd)" in err_str.lower()
        or "(rpd)" in err_str.lower()
        or (
            headers.get("x-ratelimit-limit-tokens") == "200000"
            and headers.get("x-ratelimit-remaining-tokens") == "0"
            and parse_groq_reset_seconds(headers.get("x-ratelimit-reset-tokens")) > 600.0
        )
    )

    reset_header = headers.get("x-ratelimit-reset-tokens") or headers.get("retry-after")
    m = re.search(r"try again in\s+((?:\d+(?:\.\d+)?(?:ms|s|m|h))+)", err_str, re.IGNORECASE)
    if not m:
        m = re.search(r"try again in\s+([^,;.]+?)(?:\.|\s*$)", err_str, re.IGNORECASE)
    reset_raw = reset_header or (m.group(1).strip() if m else "daily reset" if is_tpd else "2s")
    wait_s = parse_groq_reset_seconds(reset_raw)

    if is_tpd:
        reset_dt = datetime.now(timezone.utc) + timedelta(seconds=wait_s)
        time_str = reset_dt.strftime("%H:%M:%S UTC")
        detail = f"Groq daily limit reached; reset at {time_str} ({reset_raw})"
        return "tpd", detail, wait_s

    is_tpm = (
        "429" in err_str
        or "rate limit" in err_str.lower()
        or "rate_limit" in err_str.lower()
        or "tokens per minute" in err_str.lower()
        or "output tokens per minute" in err_str.lower()
        or "(tpm)" in err_str.lower()
        or "(otpm)" in err_str.lower()
        or "(rpm)" in err_str.lower()
    )
    if is_tpm:
        detail = f"Groq per-minute limit reached; retry after {wait_s:.2f}s"
        return "tpm", detail, wait_s

    return "other", f"AI evaluation error: {err_str}", 0.0


class GroqFreeTierRateLimiter:
    """Token & Request rate limiter tracking live response headers with 429 exponential jitter backoff."""
    def __init__(
        self,
        tpm_limit: int = 8000,
        target_tpm_budget: int = 6000,
        rpm_limit: int = 30,
    ):
        self.tpm_limit = tpm_limit
        self.target_tpm_budget = target_tpm_budget
        self.rpm_limit = rpm_limit
        self.remaining_tokens = tpm_limit
        self.remaining_requests = rpm_limit
        self.reset_tokens_time = time.time() + 60.0
        self.reset_requests_time = time.time() + 60.0
        self.backoff_count = 0
        self.daily_exhausted = False
        self.daily_reset_detail = ""
        self._window: list[tuple[float, int]] = []
        self._lock = asyncio.Lock()

    def update_from_headers(self, headers: dict[str, Any] | Any):
        if not headers:
            return
        try:
            h = {k.lower(): str(v) for k, v in getattr(headers, "items", lambda: [])()}
            if "x-ratelimit-remaining-tokens" in h:
                self.remaining_tokens = int(h["x-ratelimit-remaining-tokens"])
            if "x-ratelimit-remaining-requests" in h:
                self.remaining_requests = int(h["x-ratelimit-remaining-requests"])
            if "x-ratelimit-reset-tokens" in h:
                reset_sec = parse_groq_reset_seconds(h["x-ratelimit-reset-tokens"])
                self.reset_tokens_time = time.time() + reset_sec
        except Exception:
            pass

    async def acquire_slot(self, estimated_tokens: int = 400):
        """Token-budget pacing: spreads requests across minutes to respect Groq's 8,000 TPM limit."""
        if self.daily_exhausted:
            raise DailyQuotaExhaustedError(
                self.daily_reset_detail or "Groq daily limit reached; reset at daily reset"
            )

        async with self._lock:
            now = time.time()
            # Clean window older than 60 seconds
            self._window = [(ts, tok) for ts, tok in self._window if now - ts < 60.0]
            current_tokens = sum(tok for _, tok in self._window)

            # Check if this item would exceed our target per-minute budget
            if current_tokens + estimated_tokens > self.target_tpm_budget and self._window:
                oldest_ts = self._window[0][0]
                wait_s = max(0.5, (oldest_ts + 60.0) - now + random.uniform(0.1, 0.4))
                log.info(
                    "Rate limiter token window pacing: %d/%d TPM tokens used. Spreading job, waiting %.2fs",
                    current_tokens, self.target_tpm_budget, wait_s
                )
                await asyncio.sleep(wait_s)
                now = time.time()
                self._window = [(ts, tok) for ts, tok in self._window if now - ts < 60.0]

            self._window.append((now, estimated_tokens))

    async def handle_429(self, err: Exception | None = None, attempt: int = 1):
        """Paces and retries for per-minute 429; stops immediately for true daily 429."""
        if err:
            kind, detail, wait_s = classify_groq_rate_limit(err)
            if kind == "tpd":
                self.daily_exhausted = True
                self.daily_reset_detail = detail
                log.error("ABORTING BATCH: %s", detail)
                raise DailyQuotaExhaustedError(detail)
            delay = max(wait_s, (1.8 ** attempt) + random.uniform(0.2, 0.6))
        else:
            delay = (2.0 ** attempt) + random.uniform(0.2, 0.6)

        self.backoff_count += 1
        log.warning(
            "Groq TPM/429 rate limit encountered. Pacing & retrying after %.2fs (attempt %d)",
            delay, attempt
        )
        await asyncio.sleep(delay)


_GROQ_LIMITER = GroqFreeTierRateLimiter()
