"""Typer CLI interface for LeadSweep Studio commands."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.table import Table

from leadsweep.config import get_settings
from leadsweep.pipeline.store import Store
from leadsweep.services.followers import FollowersService
from leadsweep.services.jobs import JobWorker
from leadsweep.services.quality import QualityService
from leadsweep.services.workflow import WorkflowService

app = typer.Typer(name="leadsweep", help="LeadSweep Studio CLI — Leads, Actors, Runs & Datasets Intelligence")
followers_app = typer.Typer(name="followers", help="Follower intelligence commands")
jobs_app = typer.Typer(name="jobs", help="Job management commands")
leads_app = typer.Typer(name="leads", help="Lead workflow and triage commands")
actors_app = typer.Typer(name="actors", help="Apify-class Actor catalog commands")
runs_app = typer.Typer(name="runs", help="Actor run and execution commands")
agent_app = typer.Typer(name="agent", help="Autonomous Chatbot Agent execution")
datasets_app = typer.Typer(name="datasets", help="Dataset export and search commands")

app.add_typer(followers_app)
app.add_typer(jobs_app)
app.add_typer(leads_app)
app.add_typer(actors_app)
app.add_typer(runs_app)
app.add_typer(agent_app)
app.add_typer(datasets_app)


@app.command("eval")
def eval_cmd(
    k: int = typer.Option(10, "-k", help="Evaluate precision at Top-K scored items"),
    min_score: int = typer.Option(70, "--min-score", "-s", help="Only consider items scoring at or above this"),
) -> None:
    """Evaluate lead quality metrics (Precision@K) based on labeled feedback.

    ``--min-score`` genuinely filters the evaluation set (PHASE 7); use 0 to score every
    labeled row regardless of its stored score.
    """
    svc = QualityService()
    res = svc.evaluate_precision_at_k(k=k, min_score=min_score)

    table = Table(title=f"Evaluation Report (Precision@{k}, min_score>={min_score})")
    table.add_column("Entity Type", style="cyan")
    table.add_column("Labeled Count", justify="right")
    table.add_column("Good", justify="right", style="green")
    table.add_column("Bad", justify="right", style="red")
    table.add_column("Precision@K", justify="right", style="magenta")

    t_data = res["tweets"]
    u_data = res["users"]
    table.add_row("Tweets", str(t_data["count"]), str(t_data["good"]), str(t_data["bad"]), f"{t_data['precision']}%")
    table.add_row("Follower Profiles", str(u_data["count"]), str(u_data["good"]), str(u_data["bad"]), f"{u_data['precision']}%")

    if t_data["count"] == 0 and u_data["count"] == 0:
        rprint(f"[yellow]No labeled feedback at or above score {min_score}. "
               f"Record some with `leadsweep leads feedback <id> <good|bad>`.[/yellow]")

    rprint(table)


# ------------------------------------------------------------------ Followers Commands
@followers_app.command("pull")
def followers_pull(
    handle: str = typer.Argument(..., help="Target X handle (e.g. github or @stripe)"),
    limit: int = typer.Option(20, "--limit", "-l", help="Number of follower profiles to extract"),
) -> None:
    """Pull recent followers for a target handle and persist to SQLite."""
    handle = handle.lstrip("@")
    rprint(f"[bold cyan]Initiating follower extraction for @{handle} (limit={limit})...[/bold cyan]")
    svc = FollowersService()

    async def _run() -> dict:
        async def _prog(pct: int, msg: str) -> None:
            rprint(f"  [dim][{pct}%][/dim] {msg}")
        return await svc.pull_followers(handle, limit=limit, progress_cb=_prog)

    try:
        res = asyncio.run(_run())
        rprint(f"[bold green]✓ Succeeded:[/bold green] Pulled {res['pulled_count']} followers ({res['new_count']} new)")
    except Exception as e:
        rprint(f"[bold red]✗ Failed:[/bold red] {type(e).__name__}: {e}")
        raise typer.Exit(code=1)


@followers_app.command("list")
def followers_list(
    target: Optional[str] = typer.Option(None, "--target", "-t", help="Filter by target handle"),
    min_score: Optional[int] = typer.Option(None, "--min-score", "-s", help="Filter by minimum ICP score"),
    overlap: bool = typer.Option(False, "--overlap", help="Show only profiles following multiple targets"),
    limit: int = typer.Option(25, "--limit", "-l", help="Max profiles to display"),
) -> None:
    """List extracted follower profiles with ICP fit and target overlap."""
    svc = FollowersService()
    rows = svc.list_followers(target_handle=target, min_score=min_score, overlap_only=overlap, limit=limit)
    if not rows:
        rprint("[yellow]No follower profiles found matching criteria.[/yellow]")
        return

    table = Table(title=f"Followers Intelligence ({len(rows)} profiles)")
    table.add_column("Handle", style="cyan", no_wrap=True)
    table.add_column("Name", style="white")
    table.add_column("Followers", justify="right", style="green")
    table.add_column("ICP Score", justify="right", style="magenta")
    table.add_column("Overlap", justify="center", style="yellow")
    table.add_column("Status", style="blue")
    table.add_column("Bio", style="dim", max_width=40)

    for r in rows:
        handle = f"@{r['handle']}"
        name = r.get("name") or ""
        f_cnt = str(r.get("followers_count") or 0)
        icp = str(r["icp_score"]) if r.get("icp_score") is not None else "-"
        ov = str(r.get("overlap_targets") or 1)
        st = r.get("workflow_status") or "new"
        bio = (r.get("bio") or "").replace("\n", " ")[:38]
        table.add_row(handle, name, f_cnt, icp, ov, st, bio)

    rprint(table)


@followers_app.command("rescore")
def followers_rescore(
    limit: int = typer.Option(100, "--limit", "-l", help="Max profiles to re-score"),
    use_llm: bool = typer.Option(False, "--llm", help="Use Groq LLM instead of rules only"),
) -> None:
    """Run ICP scoring on all unscored follower profiles."""
    from leadsweep.services.icp_scoring import ICPScoringService
    svc = ICPScoringService()
    if use_llm:
        rprint("[bold cyan]Re-scoring profiles with Groq LLM...[/bold cyan]")
        from leadsweep.models import XUser
        rows = svc.store.db.execute("SELECT * FROM x_users LIMIT ?", (limit,)).fetchall()
        users = [
            XUser(
                rest_id=r["rest_id"],
                handle=r["handle"],
                name=r["name"],
                bio=r["bio"],
                location=r["location"],
                followers_count=r["followers_count"],
                following_count=r["following_count"],
                is_blue_verified=bool(r["is_blue_verified"]),
            )
            for r in rows
        ]
        res = asyncio.run(svc.score_with_llm(users))
        rprint(f"[bold green]✓ Scored {len(res)} profiles with LLM[/bold green]")
    else:
        rprint("[bold cyan]Scoring unscored profiles with heuristic rules...[/bold cyan]")
        res = svc.score_all_unscored(limit=limit)
        rprint(f"[bold green]✓ Scored {len(res)} profiles with rules[/bold green]")


# ------------------------------------------------------------------ Jobs Commands
@jobs_app.command("list")
def jobs_list(limit: int = typer.Option(15, "--limit", "-l", help="Number of jobs to list")) -> None:
    """List recent background jobs and statuses."""
    worker = JobWorker.get_instance()
    jobs = worker.list_jobs(limit=limit)
    if not jobs:
        rprint("[yellow]No background jobs registered yet.[/yellow]")
        return

    table = Table(title=f"Background Jobs ({len(jobs)})")
    table.add_column("Job ID", style="cyan", no_wrap=True)
    table.add_column("Kind", style="white")
    table.add_column("Status", style="magenta")
    table.add_column("Progress", justify="right")
    table.add_column("Current Step", style="dim")
    table.add_column("Created", style="dim")

    for j in jobs:
        st_style = "green" if j["status"] == "succeeded" else ("red" if j["status"] == "failed" else "yellow")
        status_str = f"[{st_style}]{j['status']}[/{st_style}]"
        table.add_row(
            j["id"],
            j["kind"],
            status_str,
            f"{j['progress_percent']}%",
            j.get("current_step") or "",
            (j.get("created_at") or "")[:19],
        )

    rprint(table)


# ------------------------------------------------------------------ Lead Workflow Commands
@leads_app.command("status")
def lead_status(
    entity_id: str = typer.Argument(..., help="Tweet ID or user rest_id"),
    status: str = typer.Argument(..., help="new | reviewing | contacted | replied | won | lost | ignored"),
    entity_type: str = typer.Option("tweet", "--type", help="tweet or user"),
    notes: Optional[str] = typer.Option(None, "--notes", help="Optional triage notes"),
) -> None:
    """Update triage workflow status of a lead."""
    wf = WorkflowService()
    try:
        res = wf.update_status(entity_id=entity_id, entity_type=entity_type, status=status, notes=notes)
        rprint(f"[bold green]✓ Updated {entity_type} {entity_id}:[/bold green] status={res['status']}")
    except Exception as e:
        rprint(f"[bold red]✗ Failed:[/bold red] {e}")
        raise typer.Exit(code=1)


@leads_app.command("feedback")
def lead_feedback(
    entity_id: str = typer.Argument(..., help="Tweet ID or user rest_id"),
    label: str = typer.Argument(..., help="good | bad"),
    entity_type: str = typer.Option("tweet", "--type", help="tweet or user"),
    reason: Optional[str] = typer.Option(None, "--reason", "-r", help="Reason code (e.g. not_decision_maker, competitor)"),
    note: Optional[str] = typer.Option(None, "--note", "-n", help="Optional detailed note"),
) -> None:
    """Record human feedback on lead quality for precision metrics."""
    qs = QualityService()
    try:
        res = qs.record_feedback(entity_id=entity_id, entity_type=entity_type, label=label, reason_code=reason, note=note)
        rprint(f"[bold green]✓ Recorded {label} feedback for {entity_type} {entity_id}[/bold green]")
    except Exception as e:
        rprint(f"[bold red]✗ Failed:[/bold red] {e}")
        raise typer.Exit(code=1)


# ------------------------------------------------------------------ Actor Catalog Commands
@actors_app.command("list")
def actors_list() -> None:
    """List all registered Apify-class scraping actors."""
    from leadsweep.actors.base import ActorRegistry
    import leadsweep.actors  # triggers registration
    actors = ActorRegistry.list_all()

    table = Table(title=f"Actor Catalog ({len(actors)} Native Actors)")
    table.add_column("Actor ID", style="cyan", no_wrap=True)
    table.add_column("Version", style="dim")
    table.add_column("Risk Multiplier", justify="center")
    table.add_column("Required Inputs", style="magenta")

    for a in actors:
        r_style = "green" if a["risk_level"] == "low" else "yellow"
        props = list(a["input_schema"].get("properties", {}).keys())
        table.add_row(
            a["name"],
            f"v{a['version']}",
            f"[{r_style}]{a['risk_level']}[/{r_style}]",
            ", ".join(props) if props else "none",
        )
    rprint(table)


# ------------------------------------------------------------------ Runs & Execution Commands
@runs_app.command("list")
def runs_list(limit: int = typer.Option(20, "--limit", "-l", help="Number of runs to display")) -> None:
    """List recent Actor runs and their statuses."""
    from leadsweep.core.datasets import DatasetEngine
    engine = DatasetEngine()
    runs = engine.list_runs(limit=limit)

    if not runs:
        rprint("[yellow]No Actor runs found.[/yellow]")
        return

    table = Table(title=f"Actor Runs ({len(runs)})")
    table.add_column("Run ID", style="cyan", no_wrap=True)
    table.add_column("Actor", style="white")
    table.add_column("Status", style="magenta")
    table.add_column("Items Scraped", justify="right", style="green")
    table.add_column("Started At", style="dim")

    for r in runs:
        st = r["status"]
        st_style = "green" if st == "completed" or st == "running" else ("yellow" if st == "hitl_pending" else "red")
        table.add_row(
            r["run_id"],
            r["actor_name"],
            f"[{st_style}]{st}[/{st_style}]",
            str(r.get("items_count") or 0),
            (r.get("started_at") or "")[:19],
        )
    rprint(table)


@runs_app.command("approve")
def run_approve(
    run_id: str = typer.Argument(..., help="Run ID to approve"),
    operator: str = typer.Option("admin", "--operator", "-o", help="Approving operator username"),
) -> None:
    """Approve a paused (hitl_pending) run and resume any agent waiting on it.

    Uses the same decide_run() path as the REST endpoint, so a CLI approval wakes the same
    waiting coroutine a UI approval would. If the run belongs to another process, the durable
    state is still updated and the output says no live task was resumed.
    """
    from leadsweep.services.agent import decide_run

    try:
        res = decide_run(run_id, action="approve", operator=operator,
                         note="Approved via CLI", source="cli")
        rprint(f"[bold green]OK: approved run {run_id}[/bold green] status={res['status']}")
        if not res.get("resumed_live_task"):
            rprint("[yellow]   note: no in-process agent is attached to this run; "
                   "durable state updated only.[/yellow]")
    except ValueError as e:
        rprint(f"[bold red]Failed:[/bold red] {e}")
        raise typer.Exit(code=1)


@runs_app.command("reject")
def run_reject(
    run_id: str = typer.Argument(..., help="Run ID to reject"),
    operator: str = typer.Option("admin", "--operator", "-o", help="Rejecting operator username"),
    reason: str = typer.Option("Rejected via CLI", "--reason", "-r", help="Reason for cancellation"),
) -> None:
    """Reject and abort a paused (hitl_pending) run, terminating any waiting agent."""
    from leadsweep.services.agent import decide_run

    try:
        res = decide_run(run_id, action="reject", operator=operator, note=reason, source="cli")
        rprint(f"[bold yellow]OK: rejected run {run_id}[/bold yellow] status={res['status']}")
    except ValueError as e:
        rprint(f"[bold red]Failed:[/bold red] {e}")
        raise typer.Exit(code=1)


# ------------------------------------------------------------------ Autonomous Agent Commands
@agent_app.command("run")
def agent_run(
    prompt: str = typer.Argument(..., help="Natural language instruction (e.g. 'Scrape hiring AI developers in SF')"),
    operator: str = typer.Option("cli_user", "--operator", "-o", help="Operator identifier"),
    auto_approve: bool = typer.Option(False, "--auto-approve", help="Auto-approve a HITL gate instead of pausing"),
) -> None:
    """Execute a natural-language scraping task via the autonomous agent.

    Uses leadsweep.services.agent.HITLAutonomousAgent - the same implementation the REST API
    serves - so CLI and API behaviour cannot drift. When the HITL gate trips, the run id is
    printed; resolve it from another shell with `leadsweep runs approve|reject <run_id>`.
    """
    from leadsweep.services.agent import HITLAutonomousAgent, decide_run

    rprint(f"[bold cyan]Dispatching prompt to Autonomous Agent:[/bold cyan] '{prompt}'")
    agent = HITLAutonomousAgent()
    operator_id = operator

    async def _exec() -> None:
        async for event in agent.execute_stream(prompt):
            step = event.get("step", "")
            msg = event.get("message", "")
            if step == "planning":
                rprint(f"  [dim][PLANNING][/dim] {msg}")
            elif step == "intent_resolved":
                rprint(f"  [cyan][INTENT][/cyan] Actor [bold]{event.get('actor')}[/bold] - {event.get('explanation')}")
                rprint(f"               input={event.get('input')}")
            elif step == "preflight_estimate":
                rprint(f"  [magenta][PRE-FLIGHT][/magenta] items={event.get('estimated_items')} "
                       f"risk={event.get('risk_level')} cost={event.get('cost')}")
            elif step == "hitl_paused":
                rprint(f"  [bold yellow][HITL PAUSE][/bold yellow] run={event.get('run_id')} task={event.get('task_id')}")
                rprint(f"                 reasons: {event.get('reasons')}")
                if auto_approve:
                    rprint("                 --auto-approve set: approving now.")
                    try:
                        decide_run(str(event.get("run_id") or event.get("task_id")), action="approve",
                                   operator=operator_id, note="auto-approved from CLI", source="cli")
                    except ValueError as exc:
                        rprint(f"  [bold red]Auto-approve failed:[/bold red] {exc}")
                else:
                    rprint(f"                 Approve: [bold]leadsweep runs approve {event.get('run_id')}[/bold]")
                    rprint(f"                 Reject:  [bold]leadsweep runs reject {event.get('run_id')}[/bold]")
            elif step == "hitl_resumed":
                rprint(f"  [green][HITL RESUMED][/green] {msg}")
            elif step == "execution_started":
                rprint(f"  [green][STARTED][/green] {msg}")
            elif step == "scraping_progress":
                rprint(f"  [cyan][PROGRESS][/cyan] {msg}")
            elif step == "execution_completed":
                rprint(f"  [bold green][DONE][/bold green] {msg}")
            elif step == "execution_failed":
                rprint(f"  [bold red][FAILED][/bold red] {event.get('error')}")
            elif step in ("hitl_rejected", "hitl_timeout"):
                rprint(f"  [bold yellow][{step.upper()}][/bold yellow] {msg}")
            elif step == "error":
                rprint(f"  [bold red][ERROR][/bold red] {msg}")

    asyncio.run(_exec())


# ------------------------------------------------------------------ Dataset Export Commands
@datasets_app.command("export")
def datasets_export(
    dataset_id: str = typer.Argument(..., help="Dataset ID (e.g. ds_xyz)"),
    format: str = typer.Option("json", "--format", "-f", help="json | jsonl | csv | xml"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path (default: stdout)"),
    limit: int = typer.Option(1000, "--limit", "-l", min=1, max=5000, help="Maximum items to export"),
) -> None:
    """Export dataset items to JSON, JSONL, CSV, or XML.

    Uses DatasetExporter.export(), the same dispatcher the REST endpoint uses, so both
    interfaces cannot produce different bytes for the same dataset.
    """
    from leadsweep.config import get_settings
    from leadsweep.core.datasets import DatasetEngine
    from leadsweep.core.exporter import DatasetExporter

    engine = DatasetEngine(get_settings().db_path)
    items = engine.get_dataset_items(dataset_id=dataset_id, limit=limit)
    if not items:
        rprint(f"[yellow]Dataset '{dataset_id}' has no items to export.[/yellow]")
        raise typer.Exit(code=1)

    try:
        content, _media_type = DatasetExporter.export(dataset_id, items, format)
    except ValueError as exc:
        rprint(f"[bold red]X {exc}[/bold red]")
        raise typer.Exit(code=2)

    if output:
        out_path = Path(output)
        if str(out_path.parent) not in ("", "."):
            out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        rprint(f"[bold green]OK: exported {len(items)} item(s) from {dataset_id} "
               f"to {out_path} ({format.upper()})[/bold green]")
    else:
        print(content)




def main() -> None:
    app()


if __name__ == "__main__":
    main()

