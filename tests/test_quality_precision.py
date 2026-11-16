"""Quality / evaluation service tests (PHASE 7).

Focus: `evaluate_precision_at_k` now honours `min_score`. It previously accepted the
parameter and ignored it, which made `xs eval --min-score` a silent no-op.
"""
from __future__ import annotations

import json

import pytest

from leadsweep.pipeline.store import Store
from leadsweep.services.quality import QualityService


@pytest.fixture
def svc(tmp_path):
    store = Store(tmp_path / "q.db")
    yield QualityService(store)
    store.close()


def _seed_tweet(store: Store, tweet_id: str, score: int, label: str) -> None:
    store.db.execute(
        "INSERT OR REPLACE INTO tweets (id, url, text, author_username, scraped_at, first_run_id) "
        "VALUES (?,?,?,?,?,?)",
        (tweet_id, f"https://x.com/i/status/{tweet_id}", f"text {tweet_id}", "u", "now", "run1"),
    )
    store.db.execute(
        "INSERT OR REPLACE INTO scores VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (tweet_id, "run1", "q", "lead", score, "lead", "[]", "reason", "action", "rules", score, "now"),
    )
    store.db.execute(
        "INSERT INTO feedback (id, entity_id, entity_type, label, created_at) VALUES (?,?,?,?,?)",
        (f"fb_{tweet_id}", tweet_id, "tweet", label, "now"),
    )
    store.db.commit()


def test_min_score_filters_out_low_scored_items(svc):
    """A high-precision low-score item must not be counted when min_score excludes it."""
    s = svc.store
    _seed_tweet(s, "low_good", 20, "good")
    _seed_tweet(s, "high_bad", 90, "bad")

    # Without a threshold, precision = 1 good / 2 = 50%.
    assert svc.evaluate_precision_at_k(k=10, min_score=0)["tweets"]["precision"] == 50.0
    # Requiring score >= 50 excludes the low-scored "good" item, leaving only the bad one.
    strict = svc.evaluate_precision_at_k(k=10, min_score=50)["tweets"]
    assert strict["count"] == 1
    assert strict["precision"] == 0.0


def test_min_score_is_echoed_in_the_result(svc):
    svc.store  # ensure db exists
    out = svc.evaluate_precision_at_k(k=5, min_score=42)
    assert out["min_score"] == 42
    assert out["k"] == 5


def test_k_limits_the_ranking(svc):
    s = svc.store
    for i in range(10):
        _seed_tweet(s, f"t{i}", 50 + i, "good" if i % 2 == 0 else "bad")
    out = svc.evaluate_precision_at_k(k=4, min_score=0)["tweets"]
    assert out["count"] == 4  # only the 4 highest-scored labeled items are evaluated


def test_precision_is_correct_when_all_good(svc):
    s = svc.store
    _seed_tweet(s, "a", 90, "good")
    _seed_tweet(s, "b", 85, "good")
    out = svc.evaluate_precision_at_k(k=10, min_score=0)["tweets"]
    assert out["precision"] == 100.0
    assert out["false_positives"] == 0


def test_precision_is_zero_when_all_bad(svc):
    s = svc.store
    _seed_tweet(s, "a", 90, "bad")
    out = svc.evaluate_precision_at_k(k=10, min_score=0)["tweets"]
    assert out["precision"] == 0.0
    assert out["bad"] == 1


def test_empty_result_is_reported_cleanly(svc):
    out = svc.evaluate_precision_at_k(k=10, min_score=99)["tweets"]
    assert out["count"] == 0
    assert out["precision"] == 0.0


def test_feedback_validation_rejects_bad_labels(svc):
    with pytest.raises(ValueError, match="good"):
        svc.record_feedback("x", "tweet", "excellent")
    with pytest.raises(ValueError, match="entity_type"):
        svc.record_feedback("x", "post", "good")


def test_user_feedback_is_evaluated_separately(svc):
    s = svc.store
    s.db.execute(
        "INSERT OR REPLACE INTO x_users (rest_id, handle, first_seen_at, last_seen_at) VALUES (?,?,?,?)",
        ("u1", "gh", "now", "now"),
    )
    s.db.execute(
        "INSERT OR REPLACE INTO user_scores VALUES (?,?,?,?,?,?,?,?)",
        ("u1", 88, "Founder", "fit", "angle", "rules", "now", 88),
    )
    s.db.execute(
        "INSERT INTO feedback (id, entity_id, entity_type, label, created_at) VALUES (?,?,?,?,?)",
        ("fb_u1", "u1", "user", "good", "now"),
    )
    s.db.commit()

    out = svc.evaluate_precision_at_k(k=10, min_score=50)
    assert out["users"]["precision"] == 100.0
    assert out["tweets"]["count"] == 0


def test_list_feedback_round_trips(svc):
    svc.record_feedback("e1", "tweet", "good", reason_code="high_value", note="n")
    svc.record_feedback("e2", "tweet", "bad")
    rows = svc.list_feedback(entity_type="tweet")
    assert len(rows) == 2
    assert {r["entity_id"] for r in rows} == {"e1", "e2"}