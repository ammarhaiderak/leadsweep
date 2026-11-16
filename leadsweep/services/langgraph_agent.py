"""LangGraph Autonomous Agent Workflow for LeadSweep ($0 local & API orchestration).

Integrates LangGraph StateGraph with HITL (Human-in-the-Loop) evaluation,
ActorRegistry dispatching, and zero-cost local browser Playwright execution.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, List, Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from leadsweep.actors import ActorRegistry
from leadsweep.actors.base import Actor, ActorEstimate, RunContext
from leadsweep.config import get_settings
from leadsweep.core.datasets import DatasetEngine
from leadsweep.core.hitl import HITLGuard, PolicyEvaluation

log = logging.getLogger("leadsweep.services.langgraph_agent")


class GraphAgentState(TypedDict, total=False):
    task_id: str
    run_id: str
    dataset_id: str
    prompt: str
    actor_name: str
    input_data: Dict[str, Any]
    explanation: str
    requires_review: bool
    estimate: Dict[str, Any]
    status: str  # planning | estimated | hitl_pending | running | completed | failed | rejected
    items_scraped: int
    error: Optional[str]
    events: List[Dict[str, Any]]


def plan_node(state: GraphAgentState) -> Dict[str, Any]:
    """Parse task objective deterministically or via local LLM without external token cost."""
    prompt = state.get("prompt", "")
    p = prompt.lower()
    words = prompt.replace("@", " @").split()

    def find_handle() -> str:
        for w in words:
            if w.startswith("@") and len(w) > 1:
                return w.lstrip("@").strip(",.!?:;\"'")
        return ""

    def find_count(default: int, cap: int) -> int:
        for w in words:
            if w.isdigit():
                try:
                    n = int(w)
                    if 1 <= n <= cap:
                        return n
                except ValueError:
                    pass
        return default

    def find_tweet_id() -> str:
        for w in words:
            if w.isdigit() and len(w) > 9:
                return w
        return ""

    if "follower" in p:
        h = find_handle()
        n = find_count(30, 500)
        return {
            "actor_name": "followers",
            "input_data": {"handle": h, "max_results": n},
            "explanation": f"Scraping followers network of @{h} (Target: {n} users).",
            "requires_review": n > 50,
            "status": "planned",
        }

    if any(k in p for k in ("user", "timeline", "tweets from @", "profile tweets")):
        h = find_handle()
        n = find_count(20, 200)
        return {
            "actor_name": "user_tweets",
            "input_data": {"handle": h, "max_results": n},
            "explanation": f"Harvesting recent author tweets from @{h} (Target: {n} tweets).",
            "requires_review": False,
            "status": "planned",
        }

    if any(k in p for k in ("reply", "replies", "thread")):
        tid = find_tweet_id()
        return {
            "actor_name": "replies",
            "input_data": {"tweet_id": tid, "max_results": 25},
            "explanation": f"Extracting discussion thread replies under Tweet ID {tid or '(none supplied)'}.",
            "requires_review": False,
            "status": "planned",
        }

    if any(k in p for k in ("bio of @", "who is @", "profile of @")):
        h = find_handle()
        return {
            "actor_name": "profile",
            "input_data": {"handle": h},
            "explanation": f"Inspecting profile metadata and audience stats for @{h}.",
            "requires_review": False,
            "status": "planned",
        }

    # Keyword / search fallback
    clean = prompt
    for sw in ("find", "search for", "search", "scrape", "extract", "get me", "get",
               "look for", "show me", "show", "please", "with high intent", "high intent"):
        clean = clean.replace(sw, " ")
    clean = " ".join(clean.split()).strip(" -:,.")
    n = find_count(20, 300)
    return {
        "actor_name": "search",
        "input_data": {"query": clean, "max_results": n, "tab": "live"},
        "explanation": f"Harvesting live X posts matching '{clean}' (Target: {n} items).",
        "requires_review": n > 60,
        "status": "planned",
    }


def estimate_node(state: GraphAgentState) -> Dict[str, Any]:
    """Validate actor input and perform pre-flight cost & risk estimation ($0 cost baseline)."""
    actor_name = state.get("actor_name", "search")
    input_data = state.get("input_data", {})

    try:
        actor = ActorRegistry.get(actor_name)
        validated = actor.input_schema(**input_data)
        est: ActorEstimate = actor.estimate(validated)

        settings = get_settings()
        engine = DatasetEngine(settings.db_path)
        guard = HITLGuard(engine=engine, webhook_url=settings.webhook_url, max_auto_items=50)
        policy: PolicyEvaluation = guard.evaluate_request(actor, validated)

        run_id, dataset_id = engine.create_run(actor_name, input_data)

        return {
            "run_id": run_id,
            "dataset_id": dataset_id,
            "estimate": {
                "items": est.estimated_items,
                "seconds": est.estimated_seconds,
                "risk": est.risk_level,
                "cost": "$0.00 (Local zero-cost engine)",
            },
            "requires_review": bool(policy.requires_approval or state.get("requires_review")),
            "status": "estimated",
        }
    except Exception as exc:
        log.exception("Pre-flight estimation error")
        return {"error": str(exc), "status": "failed"}


def route_after_estimate(state: GraphAgentState) -> Literal["hitl_gate", "execute", "fail"]:
    if state.get("error"):
        return "fail"
    if state.get("requires_review"):
        return "hitl_gate"
    return "execute"


def hitl_gate_node(state: GraphAgentState) -> Dict[str, Any]:
    """Pause workflow for Human-In-The-Loop review if anti-ban ceiling is exceeded."""
    run_id = state.get("run_id", "")
    actor_name = state.get("actor_name", "")
    input_data = state.get("input_data", {})

    settings = get_settings()
    engine = DatasetEngine(settings.db_path)
    guard = HITLGuard(engine=engine, webhook_url=settings.webhook_url)
    reasons = ["Operation exceeds standard automatic ceiling or safety threshold"]
    guard.trigger_guard(run_id, actor_name, reasons, input_data)

    return {"status": "hitl_pending"}


async def execute_node(state: GraphAgentState) -> Dict[str, Any]:
    """Execute scraping pipeline using local browser actor and persist items to dataset."""
    actor_name = state.get("actor_name", "search")
    input_data = state.get("input_data", {})
    run_id = state.get("run_id", "")
    dataset_id = state.get("dataset_id", "")

    settings = get_settings()
    engine = DatasetEngine(settings.db_path)
    actor = ActorRegistry.get(actor_name)
    validated = actor.input_schema(**input_data)

    ctx = RunContext(run_id=run_id, dataset_id=dataset_id)
    count = 0

    try:
        async for item in actor.run(validated, ctx):
            count += 1
            item_id = str(getattr(item, "id", None) or getattr(item, "rest_id", None) or uuid.uuid4())
            engine.append_item(dataset_id=dataset_id, item_id=item_id, item_type=actor_name, item_data=item, dedup=True)
            engine.update_checkpoint(run_id, ctx.checkpoint, count)

        engine.finish_run(run_id, status="succeeded")
        return {"items_scraped": count, "status": "completed"}
    except Exception as exc:
        log.exception("LangGraph actor execution failed")
        engine.finish_run(run_id, status="failed", error_detail=str(exc))
        return {"error": str(exc), "status": "failed"}


def fail_node(state: GraphAgentState) -> Dict[str, Any]:
    return {"status": "failed"}


def build_leadsweep_graph() -> StateGraph:
    """Build and compile the LangGraph StateGraph workflow for LeadSweep."""
    builder = StateGraph(GraphAgentState)

    builder.add_node("plan", plan_node)
    builder.add_node("estimate", estimate_node)
    builder.add_node("hitl_gate", hitl_gate_node)
    builder.add_node("execute", execute_node)
    builder.add_node("fail", fail_node)

    builder.add_edge(START, "plan")
    builder.add_edge("plan", "estimate")
    builder.add_conditional_edges(
        "estimate",
        route_after_estimate,
        {
            "hitl_gate": "hitl_gate",
            "execute": "execute",
            "fail": "fail",
        },
    )
    builder.add_edge("hitl_gate", END)
    builder.add_edge("execute", END)
    builder.add_edge("fail", END)

    return builder.compile()


# Singleton compiled graph
leadsweep_langgraph = build_leadsweep_graph()
