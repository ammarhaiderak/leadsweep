"""Unit and integration tests for FastAPI Backend (Stage 5).

These run against a throwaway SQLite database (see the ``tmp_db`` fixture) so the
repository's real data/leadsweep.db is never modified by the test suite.
"""
import pytest
from fastapi.testclient import TestClient

from leadsweep.api import app
from leadsweep.auth import API_KEY_HEADER


@pytest.fixture(autouse=True)
def _isolated_db(tmp_db):
    """Force every endpoint in this module onto a fresh, fully migrated database."""
    return tmp_db


@pytest.fixture
def c(auth_headers) -> TestClient:
    """Authenticated test client."""
    with TestClient(app, headers=auth_headers) as client:
        yield client


def test_health_endpoint(c):
    res = c.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["db_version"] >= 2
    assert "tweets_count" in data


def test_health_is_public_but_exposes_no_secrets(anon_client):
    """Health must stay reachable without a key (container healthchecks) but leak nothing."""
    res = anon_client.get("/api/health")
    assert res.status_code == 200
    body = res.text.lower()
    for secret_marker in ("auth_token", "ct0", "api_key", "apikey", "password"):
        assert secret_marker not in body


def test_leads_and_workflow_endpoints(c):
    res = c.get("/api/leads?limit=5")
    assert res.status_code == 200
    assert isinstance(res.json(), list)

    # Test workflow patch
    patch_res = c.patch(
        "/api/workflow/tweet/demo_tweet_100",
        json={"status": "contacted", "owner": "lead_rep", "tags": ["inbound"]},
    )
    assert patch_res.status_code == 200
    data = patch_res.json()
    assert data["status"] == "contacted"
    assert data["owner"] == "lead_rep"


def test_targets_and_followers_endpoints(c):
    res = c.post("/api/targets", json={"handle": "test_competitor", "kind": "competitor"})
    assert res.status_code == 200
    assert res.json()["handle"] == "test_competitor"

    targets = c.get("/api/targets")
    assert targets.status_code == 200
    assert any(t["handle"] == "test_competitor" for t in targets.json())

    followers = c.get("/api/followers?limit=10")
    assert followers.status_code == 200
    assert isinstance(followers.json(), list)


def test_jobs_and_feedback_endpoints(c):
    jobs = c.get("/api/jobs")
    assert jobs.status_code == 200
    assert isinstance(jobs.json(), list)

    fb = c.post(
        "/api/feedback",
        json={"entity_id": "test_e1", "entity_type": "tweet", "label": "good", "note": "High value"},
    )
    assert fb.status_code == 200
    assert fb.json()["label"] == "good"

    ev = c.get("/api/eval?k=10")
    assert ev.status_code == 200
    assert "tweets" in ev.json()