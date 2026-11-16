"""Tests for Stage 4: QualityService feedback loop and Precision@K evaluation."""
from leadsweep.pipeline.store import Store
from leadsweep.services.quality import QualityService
from typer.testing import CliRunner
from leadsweep.cli import app


def test_quality_service_feedback_and_eval(tmp_path):
    store = Store(tmp_path / "test.db")
    qs = QualityService(store)

    # Insert sample tweet score
    store.db.execute(
        "INSERT INTO tweets (id, text, author_username) VALUES ('t1', 'Need AI developer', 'buyer1')"
    )
    store.db.execute(
        "INSERT INTO scores (tweet_id, score, category, scored_at) VALUES ('t1', 90, 'lead', datetime('now'))"
    )
    store.db.execute(
        "INSERT INTO tweets (id, text, author_username) VALUES ('t2', 'Hire me for Python', 'worker1')"
    )
    store.db.execute(
        "INSERT INTO scores (tweet_id, score, category, scored_at) VALUES ('t2', 80, 'lead', datetime('now'))"
    )
    store.db.commit()

    # Record feedback: t1 is good, t2 is bad
    fb1 = qs.record_feedback("t1", "tweet", "good", note="High intent buyer")
    fb2 = qs.record_feedback("t2", "tweet", "bad", reason_code="candidate_job_seeker", note="Looking for job, not buying")

    assert fb1["label"] == "good"
    assert fb2["label"] == "bad"

    eval_res = qs.evaluate_precision_at_k(k=10)
    assert eval_res["tweets"]["count"] == 2
    assert eval_res["tweets"]["good"] == 1
    assert eval_res["tweets"]["bad"] == 1
    assert eval_res["tweets"]["precision"] == 50.0
    store.close()


def test_cli_feedback_and_eval():
    runner = CliRunner()
    res_fb = runner.invoke(app, ["leads", "feedback", "tweet_demo_1", "good", "--note", "Accurate match"])
    assert res_fb.exit_code == 0
    assert "Recorded good feedback" in res_fb.stdout

    res_eval = runner.invoke(app, ["eval", "-k", "5"])
    assert res_eval.exit_code == 0
    assert "Evaluation Report" in res_eval.stdout
