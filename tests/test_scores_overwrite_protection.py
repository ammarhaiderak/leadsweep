"""Test G1: Scores Table Overwrite Protection.
Verifies that:
(1) an existing llm score is NOT replaced by unevaluated or rule rows;
(2) a newer llm score replaces an older llm score;
(3) a legacy row (scored_by not llm) is replaced by a new llm score;
(4) re-running a job while the quota is exhausted leaves previous llm scores intact;
(5) X rows written by the store path are unaffected for new inserts and update semantics.
Runs purely on an isolated temporary sqlite database.
"""
import json
import sqlite3
import pytest


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_scores_protection.db"
    con = sqlite3.connect(db_file)
    con.row_factory = sqlite3.Row
    con.execute("""
    CREATE TABLE scores(
        tweet_id TEXT PRIMARY KEY,
        run_id TEXT,
        queries TEXT,
        query_type TEXT,
        score INTEGER,
        category TEXT,
        signals TEXT,
        reason TEXT,
        action TEXT,
        scored_by TEXT,
        heuristic_score INTEGER,
        scored_at TEXT
    )
    """)
    con.commit()
    yield con
    con.close()


def upsert_score(con: sqlite3.Connection, tweet_id: str, run_id: str, score: int | None,
                 category: str, scored_by: str, reason: str = "", signals: dict | None = None):
    sig_str = json.dumps(signals or {})
    con.execute("""
    INSERT INTO scores(
        tweet_id, run_id, queries, query_type, score, category,
        signals, reason, action, scored_by, heuristic_score, scored_at
    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(tweet_id) DO UPDATE SET
        run_id=excluded.run_id,
        queries=excluded.queries,
        query_type=excluded.query_type,
        score=excluded.score,
        category=excluded.category,
        signals=excluded.signals,
        reason=excluded.reason,
        action=excluded.action,
        scored_by=excluded.scored_by,
        heuristic_score=excluded.heuristic_score,
        scored_at=excluded.scored_at
    WHERE excluded.scored_by = 'llm' OR scores.scored_by != 'llm'
    """, (tweet_id, run_id, "query", "search", score, category,
          sig_str, reason, "action", scored_by, score, "2026-10-17T20:00:00Z"))
    con.commit()


def test_1_llm_score_not_replaced_by_unevaluated_or_rule(temp_db):
    # Initial LLM score
    upsert_score(temp_db, "item_01", "run_real_01", 90, "lead", "llm", "Strong buying intent", {"model_version": "qwen"})
    row = temp_db.execute("SELECT * FROM scores WHERE tweet_id='item_01'").fetchone()
    assert row["score"] == 90
    assert row["scored_by"] == "llm"
    assert row["run_id"] == "run_real_01"

    # Attempt to overwrite with rule row
    upsert_score(temp_db, "item_01", "run_rule_02", 10, "noise", "rule", "Heuristic filter match")
    row = temp_db.execute("SELECT * FROM scores WHERE tweet_id='item_01'").fetchone()
    assert row["score"] == 90
    assert row["scored_by"] == "llm"
    assert row["run_id"] == "run_real_01"
    assert row["reason"] == "Strong buying intent"

    # Attempt to overwrite with unevaluated row
    upsert_score(temp_db, "item_01", "run_mock_03", None, "unevaluated", "unevaluated", "Mock run")
    row = temp_db.execute("SELECT * FROM scores WHERE tweet_id='item_01'").fetchone()
    assert row["score"] == 90
    assert row["scored_by"] == "llm"
    assert row["run_id"] == "run_real_01"


def test_2_newer_llm_score_replaces_older_llm_score(temp_db):
    upsert_score(temp_db, "item_02", "run_llm_old", 70, "lead", "llm", "Old LLM verdict")
    row = temp_db.execute("SELECT * FROM scores WHERE tweet_id='item_02'").fetchone()
    assert row["score"] == 70
    assert row["run_id"] == "run_llm_old"

    # Newer LLM score replaces older LLM score
    upsert_score(temp_db, "item_02", "run_llm_new", 95, "lead", "llm", "New refined LLM verdict")
    row = temp_db.execute("SELECT * FROM scores WHERE tweet_id='item_02'").fetchone()
    assert row["score"] == 95
    assert row["run_id"] == "run_llm_new"
    assert row["reason"] == "New refined LLM verdict"


def test_3_legacy_row_replaced_by_new_llm_score(temp_db):
    # Legacy row inserted with scored_by='rule' or legacy 'heuristic'
    upsert_score(temp_db, "item_03", "run_legacy", 50, "noise", "heuristic", "Old keyword match")
    row = temp_db.execute("SELECT * FROM scores WHERE tweet_id='item_03'").fetchone()
    assert row["score"] == 50
    assert row["scored_by"] == "heuristic"

    # New LLM score upgrades legacy row
    upsert_score(temp_db, "item_03", "run_modern", 85, "lead", "llm", "Qualified by AI Agent")
    row = temp_db.execute("SELECT * FROM scores WHERE tweet_id='item_03'").fetchone()
    assert row["score"] == 85
    assert row["scored_by"] == "llm"
    assert row["run_id"] == "run_modern"


def test_4_rerunning_job_when_quota_exhausted_leaves_llm_intact(temp_db):
    upsert_score(temp_db, "item_04", "run_initial", 92, "lead", "llm", "Hiring Solidity Dev")

    # Re-running same job or new job with quota error yields unevaluated
    upsert_score(temp_db, "item_04", "run_retry_exhausted", None, "unevaluated", "unevaluated", "Quota 429 error")
    row = temp_db.execute("SELECT * FROM scores WHERE tweet_id='item_04'").fetchone()
    assert row["score"] == 92
    assert row["scored_by"] == "llm"
    assert row["category"] == "lead"
    assert row["run_id"] == "run_initial"


def test_5_x_rows_written_unaffected(temp_db):
    # Brand new X tweet insert
    upsert_score(temp_db, "x_tweet_101", "run_x_01", 80, "lead", "llm", "Founder hiring frontend")
    row = temp_db.execute("SELECT * FROM scores WHERE tweet_id='x_tweet_101'").fetchone()
    assert row is not None
    assert row["score"] == 80
    assert row["run_id"] == "run_x_01"

    # Re-evaluating via LLM updates properly
    upsert_score(temp_db, "x_tweet_101", "run_x_02", 88, "lead", "llm", "Updated analysis")
    row = temp_db.execute("SELECT * FROM scores WHERE tweet_id='x_tweet_101'").fetchone()
    assert row["score"] == 88
    assert row["run_id"] == "run_x_02"
