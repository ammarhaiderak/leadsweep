"""Tests for Stage 2: Schema migration, Services, JobWorker, and Typer CLI."""
import asyncio
from leadsweep.pipeline.store import Store
from leadsweep.services.followers import FollowersService
from leadsweep.services.jobs import JobWorker
from leadsweep.services.workflow import WorkflowService
from typer.testing import CliRunner
from leadsweep.cli import app


def test_schema_migration_v2_tables_exist(tmp_path):
    db_file = tmp_path / "test.db"
    store = Store(db_file)
    tables = [r[0] for r in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    expected = [
        "tweets", "scores", "runs", "targets", "x_users",
        "follow_edges", "follower_runs", "user_scores",
        "lead_workflow", "feedback", "jobs"
    ]
    for exp in expected:
        assert exp in tables
    ver = store.db.execute("PRAGMA user_version").fetchone()[0]
    assert ver >= 2
    store.close()


def test_workflow_service(tmp_path):
    store = Store(tmp_path / "test.db")
    wf = WorkflowService(store)
    
    # Check default status
    st = wf.get_status("123", "tweet")
    assert st["status"] == "new"

    # Update status
    updated = wf.update_status("123", "tweet", "reviewing", owner="dev_lead", tags=["high_priority"], notes="Looks promising")
    assert updated["status"] == "reviewing"
    assert updated["owner"] == "dev_lead"
    assert "high_priority" in updated["tags"]

    # Retrieve again
    fetched = wf.get_status("123", "tweet")
    assert fetched["status"] == "reviewing"
    assert fetched["notes"] == "Looks promising"
    store.close()


def test_followers_service_targets(tmp_path):
    store = Store(tmp_path / "test.db")
    svc = FollowersService(store)
    
    t = svc.get_or_create_target("stripe", kind="competitor", notes="Fintech APIs")
    assert t["handle"] == "stripe"
    assert t["kind"] == "competitor"

    targets = svc.list_targets()
    assert len(targets) == 1
    assert targets[0]["handle"] == "stripe"
    store.close()


def test_job_worker_execution(tmp_path):
    store = Store(tmp_path / "test.db")
    worker = JobWorker(store)

    async def dummy_job(progress_cb):
        await progress_cb(50, "halfway")
        return {"done": True, "count": 10}

    async def _test():
        job_id = await worker.enqueue("dummy_task", {"foo": "bar"}, dummy_job)
        await asyncio.sleep(0.1)
        job = worker.get_job(job_id)
        assert job["status"] == "succeeded"
        assert job["result_summary"] == {"done": True, "count": 10}

    asyncio.run(_test())
    store.close()


def test_cli_jobs_and_leads_commands():
    runner = CliRunner()
    res = runner.invoke(app, ["jobs", "list"])
    assert res.exit_code == 0

    res_wf = runner.invoke(app, ["leads", "status", "tweet_999", "reviewing", "--notes", "Good prospect"])
    assert res_wf.exit_code == 0
    assert "Updated tweet tweet_999" in res_wf.stdout
