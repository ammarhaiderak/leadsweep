"""
Lead Intelligence Engine - LangGraph Subgraph Workflow.
Compiles and executes the Lead Intelligence pipeline:
load_profile -> build_brief -> plan_strategies -> compile_queries -> lint_queries
-> probe_and_judge -> enrich_and_rank -> deliver.

Controlled by LEAD_INTEL=on|off.
Zero cost, local execution with Groq free tier / heuristic fallback.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, TypedDict
from langgraph.graph import StateGraph, END

from leadsweep.leadintel.models import (
    LeadBrief,
    QueryVariant,
    DirectionLabel,
    StrategyType,
    ScoreV2,
)
from leadsweep.leadintel.profile import get_user_sales_profile
from leadsweep.leadintel.brief import (
    build_lead_brief_sync,
    calculate_query_ambiguity,
)
from leadsweep.leadintel.strategies import select_strategies_for_brief
from leadsweep.leadintel.compiler import compile_queries
from leadsweep.leadintel.linter import lint_and_repair_variants
from leadsweep.leadintel.judge import judge_candidate
from leadsweep.leadintel.probe import (
    allocate_bandit_winners,
    extract_learned_negatives_from_noise,
)
from leadsweep.leadintel.enrichment import (
    enrich_author_profile,
    deduplicate_near_duplicates,
    calculate_lookalike_boost,
    aggregate_account_leads,
)
from leadsweep.leadintel.memory import (
    generate_lookalike_queries,
    get_feedback_history,
)


class LeadIntelState(TypedDict, total=False):
    # Inputs
    raw_query: str
    max_budget: int
    existing_candidates: List[Dict[str, Any]]
    clarification_response: Optional[str]

    # Pipeline artifacts
    profile: Optional[Dict[str, Any]]
    brief: Optional[LeadBrief]
    ambiguity_score: float
    needs_clarification: bool
    clarification_options: List[str]

    portfolio: List[StrategyType]
    compiled_variants: List[QueryVariant]
    linted_variants: List[QueryVariant]
    winning_variants: List[QueryVariant]
    learned_negatives: List[str]

    # Evaluated candidates & leads
    probed_candidates: List[Dict[str, Any]]
    scored_candidates: List[Dict[str, Any]]
    enriched_candidates: List[Dict[str, Any]]
    final_leads: List[Dict[str, Any]]

    # Audit & Status
    error: Optional[str]
    status: str


def is_lead_intel_enabled() -> bool:
    """Checks whether LEAD_INTEL is enabled via environment."""
    return os.environ.get("LEAD_INTEL", "on").strip().lower() in ("on", "1", "true", "yes")


# ================= Node Implementations =================

def load_profile_node(state: LeadIntelState) -> Dict[str, Any]:
    """Loads seller profile from database."""
    profile = get_user_sales_profile()
    return {"profile": profile}


def build_brief_node(state: LeadIntelState) -> Dict[str, Any]:
    """Builds LeadBrief and evaluates ambiguity."""
    raw_query = state.get("raw_query", "")
    profile = state.get("profile")

    ambiguity = calculate_query_ambiguity(raw_query, offer_known=bool(profile))

    # If ambiguity is high (> 0.65) and no profile exists, flag clarification
    if ambiguity > 0.65 and not profile and not state.get("clarification_response"):
        return {
            "ambiguity_score": ambiguity,
            "needs_clarification": True,
            "clarification_options": [
                f'Looking for founders hiring or buying: "{raw_query}" "looking for"',
                f'Looking for pain points and tool requests: "{raw_query}" "recommendations"',
                f'Looking for active complaints about competitors: "{raw_query}" "alternatives"',
            ],
            "status": "awaiting_clarification",
        }

    brief = build_lead_brief_sync(raw_query=raw_query, user_profile=profile)
    return {
        "brief": brief,
        "ambiguity_score": ambiguity,
        "needs_clarification": False,
        "status": "brief_created",
    }


def plan_strategies_node(state: LeadIntelState) -> Dict[str, Any]:
    """Selects strategy portfolio from brief."""
    brief = state.get("brief")
    if not brief:
        return {"portfolio": [StrategyType.S1_NEED_SIGNAL, StrategyType.S2_PAIN_POINT]}

    portfolio = select_strategies_for_brief(brief)
    return {"portfolio": portfolio, "status": "strategies_planned"}


def compile_queries_node(state: LeadIntelState) -> Dict[str, Any]:
    """Compiles query variants across selected strategies."""
    brief = state.get("brief")
    portfolio = state.get("portfolio", [])

    if not brief:
        v = QueryVariant(
            strategy=StrategyType.S1_NEED_SIGNAL,
            query_string=f'"{state.get("raw_query", "web3")}" "looking for" -airdrop -rt',
            rationale="Fallback search",
            expected_precision=0.7,
        )
        return {"compiled_variants": [v], "status": "queries_compiled"}

    variants = compile_queries(brief, portfolio, target_count=8)

    # Blend lookalike queries from past approved leads
    core_terms = brief.icp_domains or [brief.offer.split()[0]]
    lookalikes = generate_lookalike_queries(core_terms, max_variants=2)
    variants.extend(lookalikes)

    return {"compiled_variants": variants, "status": "queries_compiled"}


def lint_queries_node(state: LeadIntelState) -> Dict[str, Any]:
    """Lints and validates all generated query variants."""
    variants = state.get("compiled_variants", [])
    brief = state.get("brief")
    core_terms = (brief.icp_domains + brief.icp_roles) if brief else []

    linted = lint_and_repair_variants(variants, core_topics=core_terms)
    return {"linted_variants": linted, "status": "queries_linted"}


def probe_and_judge_node(state: LeadIntelState) -> Dict[str, Any]:
    """
    Evaluates candidate posts against direction heuristics and scoring v2.
    """
    candidates = state.get("existing_candidates", [])
    brief = state.get("brief")
    variants = state.get("linted_variants", [])

    scored_candidates: List[Dict[str, Any]] = []

    for c in candidates:
        text = c.get("text", "")
        author_bio = c.get("author_bio", "") or c.get("author", {}).get("description", "")
        followers = int(c.get("author_followers", 0) or c.get("author", {}).get("followers_count", 0) or 0)
        rule_score = int(float(c.get("rule_score", 50.0)))

        score_res: ScoreV2 = judge_candidate(
            post_text=text,
            author_bio=author_bio,
            author_followers=followers,
            topic_rel_score=rule_score,
            brief=brief,
        )

        c_copy = dict(c)
        c_copy["score_v2"] = score_res.final_score
        c_copy["final_score"] = score_res.final_score
        c_copy["direction_label"] = score_res.direction.value
        c_copy["direction_cap"] = score_res.direction_cap
        c_copy["verbatim_quote_verified"] = score_res.quote_verified
        c_copy["why_text"] = score_res.why_text

        scored_candidates.append(c_copy)

    # Bandit winner allocation & noise learning
    rejected_texts = [c.get("text", "") for c in scored_candidates if c.get("score_v2", 0) <= 25]
    learned_negatives = extract_learned_negatives_from_noise(rejected_texts, brief) if brief else []
    winning_variants = allocate_bandit_winners(variants)

    return {
        "scored_candidates": scored_candidates,
        "winning_variants": winning_variants,
        "learned_negatives": learned_negatives,
        "status": "probed_and_judged",
    }


def enrich_and_rank_node(state: LeadIntelState) -> Dict[str, Any]:
    """Enriches authors, eliminates near-duplicates, applies lookalike boosts, and aggregates leads."""
    scored = state.get("scored_candidates", [])

    # Filter out posts hard-capped below viable threshold (< 20)
    viable = [c for c in scored if c.get("score_v2", 0) >= 20]

    # Deduplicate near-duplicates
    deduped = deduplicate_near_duplicates(viable, similarity_threshold=0.82)

    # Enrich author profiles
    enriched: List[Dict[str, Any]] = []
    for c in deduped:
        author_data = {
            "username": c.get("author_username", ""),
            "description": c.get("author_bio", ""),
            "followers_count": c.get("author_followers", 0),
        }
        c["enrichment"] = enrich_author_profile(author_data)
        enriched.append(c)

    # Retrieve feedback history to compute lookalike boost
    feedback = get_feedback_history(limit=50)
    approved_texts = [f["post_text"] for f in feedback if f["action"] == "approved" and f["post_text"]]
    rejected_texts = [f["post_text"] for f in feedback if f["action"] == "rejected" and f["post_text"]]

    for c in enriched:
        boost = calculate_lookalike_boost(c.get("text", ""), approved_texts, rejected_texts)
        if boost != 0.0:
            c["score_v2"] = min(100, max(0, int(c["score_v2"] * (1.0 + boost))))
            c["final_score"] = c["score_v2"]
            c["lookalike_boost"] = boost

    # Account-level lead aggregation
    aggregated = aggregate_account_leads(enriched)

    # Sort descending by score_v2
    aggregated.sort(key=lambda x: x.get("score_v2", 0), reverse=True)

    return {
        "enriched_candidates": enriched,
        "final_leads": aggregated,
        "status": "completed",
    }


# ================= Routing Logic =================

def check_clarification_route(state: LeadIntelState) -> str:
    """Decides if graph pauses for clarification or continues."""
    if state.get("needs_clarification", False):
        return END
    return "plan_strategies"


# ================= Graph Construction =================

def build_lead_intel_graph() -> StateGraph:
    """Builds and compiles the Lead Intelligence LangGraph workflow."""
    workflow = StateGraph(LeadIntelState)

    workflow.add_node("load_profile", load_profile_node)
    workflow.add_node("build_brief", build_brief_node)
    workflow.add_node("plan_strategies", plan_strategies_node)
    workflow.add_node("compile_queries", compile_queries_node)
    workflow.add_node("lint_queries", lint_queries_node)
    workflow.add_node("probe_and_judge", probe_and_judge_node)
    workflow.add_node("enrich_and_rank", enrich_and_rank_node)

    workflow.set_entry_point("load_profile")
    workflow.add_edge("load_profile", "build_brief")

    workflow.add_conditional_edges(
        "build_brief",
        check_clarification_route,
        {
            END: END,
            "plan_strategies": "plan_strategies",
        },
    )

    workflow.add_edge("plan_strategies", "compile_queries")
    workflow.add_edge("compile_queries", "lint_queries")
    workflow.add_edge("lint_queries", "probe_and_judge")
    workflow.add_edge("probe_and_judge", "enrich_and_rank")
    workflow.add_edge("enrich_and_rank", END)

    return workflow.compile()


# Compiled singleton graph
lead_intel_graph = build_lead_intel_graph()


def run_lead_intelligence(
    raw_query: str,
    candidates: Optional[List[Dict[str, Any]]] = None,
    max_budget: int = 60,
    clarification_response: Optional[str] = None,
) -> LeadIntelState:
    """
    Synchronous entry point to execute the Lead Intelligence Engine.
    Respects LEAD_INTEL=on|off.
    """
    if not is_lead_intel_enabled():
        return {
            "raw_query": raw_query,
            "status": "bypassed_lead_intel_off",
            "final_leads": candidates or [],
        }

    initial_state: LeadIntelState = {
        "raw_query": raw_query,
        "max_budget": max_budget,
        "existing_candidates": candidates or [],
        "clarification_response": clarification_response,
        "status": "starting",
    }

    result = lead_intel_graph.invoke(initial_state)
    return result
