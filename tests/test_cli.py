"""CLI regression tests (PHASE 2).

`xs agent run` and `xs datasets export` previously called methods that did not exist
(`AutonomousAgent.stream()` and `DatasetExporter.export()`), so both commands raised
AttributeError on every invocation. These tests invoke the real Typer command functions, so a
regression to a missing method fails the suite instead of shipping.

No live X request is made: the agent tests use a HITL-gated prompt, which stops at the gate
before any browser is launched.
"""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from leadsweep.cli import app
from leadsweep.core.datasets import DatasetEngine
from leadsweep.core.exporter import DatasetExporter
from leadsweep.core.hitl import HITLGuard
from leadsweep.pipeline.store import Store

runner = CliRunner()


@pytest.fixture
def seeded_db(tmp_db):
    """A migrated database containing a small dataset."""
    engine = DatasetEngine(tmp_db)
    engine.append_item("ds_cli", "t1", "tweet", {"id": "t1", "text": "need an AI developer"})
    engine.append_item("ds_cli", "t2", "tweet", {"id": "t2", "text": "hiring automation engineers"})
    return engine


# --------------------------------------------------------------------------- datasets export
@pytest.mark.parametrize("fmt", ["json", "jsonl", "csv", "xml"])
def test_datasets_export_all_formats(seeded_db, fmt):
    result = runner.invoke(app, ["datasets", "export", "ds_cli", "--format", fmt])
    assert result.exit_code == 0, result.output
    assert "need an AI developer" in result.output


def test_datasets_export_to_file(seeded_db, tmp_path):
    out = tmp_path / "nested" / "ds.json"
    result = runner.invoke(app, ["datasets", "export", "ds_cli", "--output", str(out)])
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "need an AI developer" in out.read_text(encoding="utf-8")


def test_datasets_export_rejects_unknown_format(seeded_db):
    """A typo must fail loudly rather than silently emitting JSON."""
    result = runner.invoke(app, ["datasets", "export", "ds_cli", "--format", "parquet"])
    assert result.exit_code == 2
    assert "Unsupported export format" in result.output


def test_datasets_export_empty_dataset_exits_nonzero(tmp_db):
    result = runner.invoke(app, ["datasets", "export", "ds_missing"])
    assert result.exit_code == 1
    assert "no items" in result.output.lower()


# --------------------------------------------------------------------------- exporter contract
def test_exporter_export_returns_content_and_media_type():
    items = [{"id": "a", "text": "hello"}]
    for fmt, expected in (("json", "application/json"), ("jsonl", "application/x-ndjson"),
                          ("csv", "text/csv"), ("xml", "application/xml")):
        content, media = DatasetExporter.export("ds", items, fmt)
        assert media.startswith(expected), f"{fmt} -> {media}"
        assert "hello" in content


def test_exporter_export_rejects_bad_format():
    with pytest.raises(ValueError, match="Unsupported export format"):
        DatasetExporter.export("ds", [], "yaml")


def test_exporter_handles_empty_dataset():
    for fmt in ("json", "jsonl", "csv", "xml"):
        content, _ = DatasetExporter.export("ds", [], fmt)
        assert isinstance(content, str)


def test_exporter_preserves_unicode():
    items = [{"text": "café ünïcode 日本語 🎯"}]
    content, _ = DatasetExporter.export("ds", items, "json")
    assert "日本語" in content


# --------------------------------------------------------------------------- runs approve/reject
def test_runs_approve_flips_paused_run(tmp_db, seeded_db):
    guard = HITLGuard(engine=seeded_db)
    run_id, _ = seeded_db.create_run("followers", {"handle": "github", "max_results": 300})
    guard.trigger_guard(run_id, "followers", ["over ceiling"], {})

    result = runner.invoke(app, ["runs", "approve", run_id, "--operator", "tester"])
    assert result.exit_code == 0, result.output
    assert seeded_db.get_run(run_id)["status"] == "running"


def test_runs_reject_aborts_paused_run(tmp_db, seeded_db):
    guard = HITLGuard(engine=seeded_db)
    run_id, _ = seeded_db.create_run("followers", {"handle": "github", "max_results": 400})
    guard.trigger_guard(run_id, "followers", ["high risk"], {})

    result = runner.invoke(app, ["runs", "reject", run_id, "--reason", "not now"])
    assert result.exit_code == 0, result.output
    assert seeded_db.get_run(run_id)["status"] == "aborted"


def test_runs_approve_unknown_run_fails_cleanly(tmp_db, seeded_db):
    result = runner.invoke(app, ["runs", "approve", "run_does_not_exist"])
    assert result.exit_code == 1
    assert "Failed" in result.output


# --------------------------------------------------------------------------- agent run
def test_agent_run_reaches_hitl_gate_without_attribute_error(tmp_db):
    """Previously raised AttributeError: AutonomousAgent has no attribute 'stream'."""
    result = runner.invoke(app, ["agent", "run", "scrape 400 followers from @github"])
    combined = result.output
    assert "AttributeError" not in combined
    assert "HITL PAUSE" in combined
    assert "PRE-FLIGHT" in combined


def test_agent_run_help_documents_auto_approve(tmp_db):
    result = runner.invoke(app, ["agent", "run", "--help"])
    assert result.exit_code == 0
    assert "--auto-approve" in result.output


# --------------------------------------------------------------------------- other commands
def test_actors_list_runs(tmp_db):
    for args in (["actors", "list"], ["runs", "list"], ["eval"], ["jobs", "list"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, f"{args} -> {result.output}"


def test_leads_feedback_records_label(tmp_db):
    result = runner.invoke(app, ["leads", "feedback", "tw_x1", "good", "--type", "tweet"])
    assert result.exit_code == 0, result.output