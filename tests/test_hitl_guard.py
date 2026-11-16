"""Unit and API integration tests for Phase E Human-in-the-Loop (HITL) Guard."""
import pytest
from fastapi.testclient import TestClient

from leadsweep.actors import ActorRegistry
from leadsweep.actors.followers import FollowersActorInput
from leadsweep.actors.search import SearchActorInput
from leadsweep.api import app
from leadsweep.core.datasets import DatasetEngine
from leadsweep.core.hitl import HITLGuard


@pytest.fixture
def hitl_setup(tmp_path):
    db_file = tmp_path / "test_hitl.db"
    from leadsweep.pipeline.store import Store
    Store(db_file)  # initialize v4 tables
    engine = DatasetEngine(db_file)
    guard = HITLGuard(engine=engine, max_auto_items=50, risk_threshold="medium")
    return engine, guard


def test_hitl_guard_policy_evaluation(hitl_setup):
    _, guard = hitl_setup

    # 1. Low risk small volume -> Auto allowed
    search = ActorRegistry.get("search")
    eval_safe = guard.evaluate_request(search, SearchActorInput(query="LangChain", max_results=20))
    assert not eval_safe.requires_approval
    assert len(eval_safe.reasons) == 0

    # 2. Large volume exceeding ceiling -> Approval required
    eval_large = guard.evaluate_request(search, SearchActorInput(query="LangChain", max_results=150))
    assert eval_large.requires_approval
    assert any("exceed safety ceiling" in r for r in eval_large.reasons)

    # 3. Medium/High risk actor (followers) -> Approval required
    followers = ActorRegistry.get("followers")
    eval_risk = guard.evaluate_request(followers, FollowersActorInput(handle="elonmusk", max_results=30))
    assert eval_risk.requires_approval
    assert any("MEDIUM" in r or "HIGH" in r for r in eval_risk.reasons)


def test_hitl_guard_pause_approve_reject(hitl_setup):
    engine, guard = hitl_setup

    run_id, _ = engine.create_run("followers", {"handle": "karpathy", "max_results": 100})
    
    # Trigger guard pause
    guard.trigger_guard(run_id, "followers", ["Exceeds safety limit"], {"handle": "karpathy"})
    run = engine.get_run(run_id)
    assert run["status"] == "hitl_pending"

    # Operator approves run
    appr = guard.approve_run(run_id, operator="senior_ops")
    assert appr["status"] == "running"
    run_after = engine.get_run(run_id)
    assert run_after["status"] == "running"

    # Create second run and reject it
    run_id_2, _ = engine.create_run("followers", {"handle": "sama", "max_results": 200})
    guard.trigger_guard(run_id_2, "followers", ["High risk network extraction"], {"handle": "sama"})
    rej = guard.reject_run(run_id_2, operator="security_lead", reason="Rate limit precaution")
    assert rej["status"] == "aborted"
    run_2_after = engine.get_run(run_id_2)
    assert run_2_after["status"] == "aborted"


def test_hitl_api_endpoints(auth_headers):
    client = TestClient(app, headers=auth_headers)

    # Test list runs
    res = client.get("/api/runs")
    assert res.status_code == 200
    assert isinstance(res.json(), list)
