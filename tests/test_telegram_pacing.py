"""Test Telegram pacing with a mocked 10-item job (~1,000 tokens each)."""
from __future__ import annotations

import asyncio
import time
import pytest
from unittest.mock import patch

from leadsweep.pipeline.groq_limiter import GroqFreeTierRateLimiter


@pytest.mark.asyncio
async def test_telegram_pacing_mocked_10_items():
    # Free-tier target TPM budget: 6,000 tokens.
    # 10 items x 1,000 tokens = 10,000 tokens (exceeds single 60s window).
    limiter = GroqFreeTierRateLimiter(tpm_limit=8000, target_tpm_budget=6000)

    sleep_durations = []
    current_fake_time = [1000.0]

    def fake_time():
        return current_fake_time[0]

    async def fake_sleep(duration):
        sleep_durations.append(duration)
        # Advance fake time by duration so tokens in sliding window age out
        current_fake_time[0] += duration

    items_processed = 0
    with patch("time.time", side_effect=fake_time), patch("asyncio.sleep", side_effect=fake_sleep):
        for i in range(10):
            # Each item estimates ~1,000 tokens
            await limiter.acquire_slot(estimated_tokens=1000)
            items_processed += 1

    assert items_processed == 10
    # Because 10 x 1000 > 6000, limiter must have triggered token-budget pacing sleeps!
    assert len(sleep_durations) > 0
    print(f"\nTelegram job pacing: 10 items (1,000 tokens each) paced smoothly with {len(sleep_durations)} pacing delays: {sleep_durations}")
