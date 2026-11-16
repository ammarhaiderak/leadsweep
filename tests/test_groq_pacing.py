"""Unit tests for Groq rate limiter, TPM pacing, TPD abort, and reset duration parsing."""
from __future__ import annotations

import asyncio
import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from groq import RateLimitError
from leadsweep.pipeline.groq_limiter import (
    GroqFreeTierRateLimiter,
    DailyQuotaExhaustedError,
    classify_groq_rate_limit,
    parse_groq_reset_seconds,
)


def test_parse_groq_reset_seconds():
    assert parse_groq_reset_seconds("1.85s") == 1.85
    assert parse_groq_reset_seconds("500ms") == 0.5
    assert parse_groq_reset_seconds("1m30s") == 90.0
    assert parse_groq_reset_seconds("4h32m10s") == 4 * 3600 + 32 * 60 + 10
    assert parse_groq_reset_seconds("60") == 60.0
    assert parse_groq_reset_seconds(15) == 15.0
    assert parse_groq_reset_seconds(None) == 2.0


def test_classify_tpm_rate_limit():
    tpm_headers = {
        "x-ratelimit-limit-tokens": "8000",
        "x-ratelimit-remaining-tokens": "0",
        "x-ratelimit-reset-tokens": "1.85s",
        "retry-after": "2",
    }
    resp = httpx.Response(
        status_code=429,
        headers=tpm_headers,
        request=httpx.Request("POST", "https://api.groq.com"),
    )
    err = RateLimitError(
        message="Rate limit reached for model `qwen/qwen3.8-27b` on tokens per minute (TPM): Limit 8000, Used 7800, Requested 600. Please try again in 1.85s.",
        response=resp,
        body={"error": {"message": "TPM limit", "type": "tokens"}},
    )

    kind, detail, wait_s = classify_groq_rate_limit(err)
    assert kind == "tpm"
    assert "retry after 1.85s" in detail
    assert wait_s == 1.85


def test_classify_tpd_rate_limit():
    tpd_headers = {
        "x-ratelimit-limit-tokens": "200000",
        "x-ratelimit-remaining-tokens": "0",
        "x-ratelimit-reset-tokens": "4h32m10s",
        "retry-after": "16330",
    }
    resp = httpx.Response(
        status_code=429,
        headers=tpd_headers,
        request=httpx.Request("POST", "https://api.groq.com"),
    )
    err = RateLimitError(
        message="Rate limit reached for model `qwen/qwen3.8-27b` on tokens per day (TPD): Limit 200000, Used 200000. Please try again in 4h32m10s.",
        response=resp,
        body={"error": {"message": "TPD limit", "type": "tokens"}},
    )

    kind, detail, wait_s = classify_groq_rate_limit(err)
    assert kind == "tpd"
    assert "Groq daily limit reached; reset at" in detail
    assert "4h32m10s" in detail
    assert wait_s == 4 * 3600 + 32 * 60 + 10


@pytest.mark.asyncio
async def test_limiter_tpm_pacing_and_retry():
    limiter = GroqFreeTierRateLimiter(tpm_limit=8000, target_tpm_budget=6000)

    # Slot acquire works normally
    await limiter.acquire_slot(estimated_tokens=400)
    assert not limiter.daily_exhausted

    # Mock TPM 429
    err = Exception("Rate limit reached for model `qwen/qwen3.8-27b` on tokens per minute (TPM). Please try again in 50ms.")
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await limiter.handle_429(err, attempt=1)
        mock_sleep.assert_awaited_once()
        assert not limiter.daily_exhausted


@pytest.mark.asyncio
async def test_limiter_tpd_abort():
    limiter = GroqFreeTierRateLimiter(tpm_limit=8000, target_tpm_budget=6000)

    err = Exception("Rate limit reached for model `qwen/qwen3.8-27b` on tokens per day (TPD): Limit 200000. Please try again in 4h32m10s.")
    with pytest.raises(DailyQuotaExhaustedError) as exc_info:
        await limiter.handle_429(err, attempt=1)

    assert limiter.daily_exhausted
    assert "Groq daily limit reached" in str(exc_info.value)

    # Future acquires should immediately fail fast
    with pytest.raises(DailyQuotaExhaustedError):
        await limiter.acquire_slot(estimated_tokens=100)
