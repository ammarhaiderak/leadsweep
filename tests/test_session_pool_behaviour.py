"""Session pool behaviour and deprecation coverage (PHASE 6).

The canonical implementation is leadsweep.session_pool.SessionPool. This module also pins the
resolution of the session_pool / session_pool_v2 duplication so it cannot drift again.
"""
from __future__ import annotations

import json

import pytest

from leadsweep.exceptions import NoSessionAvailableError
from leadsweep.session_pool import SessionPool
from leadsweep.session_pool_v2 import SessionPoolV2


@pytest.fixture
def sessions(tmp_path):
    f = tmp_path / "sessions.json"
    state = tmp_path / "state.json"
    f.write_text(json.dumps({"sessions": [
        {"id": "acct-1", "auth_token": "t1", "ct0": "c1"},
        {"id": "acct-2", "auth_token": "t2", "ct0": "c2"},
    ]}))
    return f, state


# --------------------------------------------------------------------------- deprecation contract
def test_session_pool_v2_is_an_alias_not_a_second_implementation():
    """Both spellings must resolve to ONE class, so behaviour cannot diverge."""
    assert SessionPoolV2 is SessionPool


def test_deprecated_module_still_importable(sessions):
    f, state = sessions
    pool = SessionPoolV2(f, state)
    assert isinstance(pool, SessionPool)
    assert pool.acquire().id in ("acct-1", "acct-2")


# --------------------------------------------------------------------------- core behaviour
def test_all_dead_raises_and_alerts(sessions):
    f, state = sessions
    pool = SessionPool(f, state)
    pool.mark_dead("acct-1", "expired")
    pool.mark_dead("acct-2", "expired")
    with pytest.raises(NoSessionAvailableError):
        pool.acquire()


def test_hourly_budget_is_enforced(sessions):
    f, state = sessions
    pool = SessionPool(f, state, hourly_budget=1)
    s1 = pool.acquire()
    pool.mark_used(s1.id)
    s2 = pool.acquire()
    assert s2.id != s1.id
    pool.mark_used(s2.id)
    with pytest.raises(NoSessionAvailableError):
        pool.acquire()


def test_daily_warmup_quota_blocks_acquisition(sessions):
    f, state = sessions
    pool = SessionPool(f, state, base_daily_quota=1, max_daily_quota=1)
    s1 = pool.acquire()
    pool.mark_used(s1.id)
    s2 = pool.acquire()
    pool.mark_used(s2.id)
    with pytest.raises(NoSessionAvailableError):
        pool.acquire()


def test_cooldown_grows_exponentially_and_is_capped(sessions):
    f, state = sessions
    pool = SessionPool(f, state)
    pool.mark_cooldown("acct-1", seconds=900)
    first = next(s for s in pool.summary() if s["id"] == "acct-1")["cooldown_s"]

    pool.state["acct-1"].cooldown_until = 0.0  # let it be acquirable again
    pool.mark_cooldown("acct-1", seconds=900)
    second = next(s for s in pool.summary() if s["id"] == "acct-1")["cooldown_s"]
    assert second > first, "second cooldown must back off further"

    # Never unbounded.
    for _ in range(10):
        pool.state["acct-1"].cooldown_until = 0.0
        pool.mark_cooldown("acct-1", seconds=900)
    assert next(s for s in pool.summary() if s["id"] == "acct-1")["cooldown_s"] <= 7200 + 30


def test_summary_never_exposes_credentials(sessions):
    f, state = sessions
    pool = SessionPool(f, state)
    pool.acquire()
    pool.mark_used("acct-1")
    blob = json.dumps(pool.summary()).lower()
    for secret in ("auth_token", "ct0", "t1", "c1"):
        assert secret not in blob


def test_state_persists_across_instances(sessions):
    f, state = sessions
    pool = SessionPool(f, state)
    pool.mark_dead("acct-1", "manual")

    reloaded = SessionPool(f, state)
    assert any(s["id"] == "acct-1" and s["dead"] for s in reloaded.summary())


def test_empty_sessions_file_is_rejected(tmp_path):
    f = tmp_path / "empty.json"
    f.write_text(json.dumps({"sessions": []}))
    with pytest.raises(ValueError, match="no sessions"):
        SessionPool(f, tmp_path / "state.json")


def test_corrupt_state_file_does_not_crash(sessions):
    f, state = sessions
    state.write_text("{ not valid json", encoding="utf-8")
    pool = SessionPool(f, state)  # must recover with fresh metrics
    assert len(pool.summary()) == 2