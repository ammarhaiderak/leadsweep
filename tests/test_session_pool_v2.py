"""Unit tests for SessionPool V2: Anti-ban, sliding window, and warmup schedule (Phase D)."""
import json
import time
import pytest
from leadsweep.exceptions import NoSessionAvailableError
from leadsweep.session_pool import SessionPool


@pytest.fixture
def test_sessions(tmp_path):
    sess_file = tmp_path / "sessions.json"
    state_file = tmp_path / "session_state.json"
    data = {
        "sessions": [
            {"id": "acct-1", "auth_token": "tok1", "ct0": "ct01"},
            {"id": "acct-2", "auth_token": "tok2", "ct0": "ct02"},
        ]
    }
    sess_file.write_text(json.dumps(data))
    return sess_file, state_file


def test_session_acquisition_and_lru(test_sessions):
    sess_file, state_file = test_sessions
    pool = SessionPool(sess_file, state_file)

    s1 = pool.acquire()
    assert s1.id in ("acct-1", "acct-2")
    pool.mark_used(s1.id)

    # Next acquire should pick the other session (LRU)
    s2 = pool.acquire()
    assert s2.id != s1.id
    pool.mark_used(s2.id)


def test_sliding_window_hourly_budget(test_sessions):
    sess_file, state_file = test_sessions
    # Strict hourly budget of 2 requests
    pool = SessionPool(sess_file, state_file, hourly_budget=2)

    s1 = pool.acquire()
    pool.mark_used(s1.id)
    pool.mark_used(s1.id)

    # acct-1 has reached budget of 2; pool must give acct-2
    s2 = pool.acquire()
    assert s2.id != s1.id
    pool.mark_used(s2.id)
    pool.mark_used(s2.id)

    # Both exhausted
    with pytest.raises(NoSessionAvailableError):
        pool.acquire()


def test_exponential_backoff_cooldown(test_sessions):
    sess_file, state_file = test_sessions
    pool = SessionPool(sess_file, state_file)

    s1 = pool.acquire()
    pool.mark_cooldown(s1.id, seconds=10)

    # acct-1 is in cooldown; acquire must return other session
    s2 = pool.acquire()
    assert s2.id != s1.id

    # Check metrics
    summ = {item["id"]: item for item in pool.summary()}
    assert summ[s1.id]["cooldown_s"] > 0
    assert summ[s1.id]["consecutive_429s"] == 1


def test_warmup_schedule_scaling(test_sessions):
    sess_file, state_file = test_sessions
    pool = SessionPool(sess_file, state_file, warmup_days=7, base_daily_quota=50, max_daily_quota=350)
    
    # Brand new session has day 0 quota ~ 50
    q = pool.get_effective_daily_quota("acct-1")
    assert 50 <= q <= 60

    # Simulate aged session (8 days old)
    pool.state["acct-1"].first_seen = time.time() - (8 * 86400)
    assert pool.get_effective_daily_quota("acct-1") == 350
