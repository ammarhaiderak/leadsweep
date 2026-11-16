"""LangGraph workflow.

  start_run -> fetch_next (loops per query) -> prefilter -> score -> select -> export -> finish
                   |  abort codes (expired/rate-limit/drift) stop fetching but the run still finishes cleanly
                   +-> prefilter -> (no candidates) -> finish
"""
from __future__ import annotations

import asyncio
import logging
import operator
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, TypedDict

try:  # UPDATED LOGIC: friendly dependency hint instead of a raw traceback
    from langgraph.graph import END, START, StateGraph
except ImportError:
    raise SystemExit("Missing dependency 'langgraph'. Run:  python -m scripts.doctor --install   (or: pip install -r requirements.txt)")

from ..config import Settings
from .checkpoint import SQLiteSaver  # UPDATED LOGIC: Import SQLiteSaver
from .mcp_client import ScrapeClient
from .models import Candidate, Fetched, PipelineConfig, ScoredTweet
from .scoring import Scorer, heuristic_score, prefilter_reason
from .sinks import export_csv, export_json, post_webhook
from .store import Store

log = logging.getLogger("leadsweep.graph")

# a failure of these affects every later query too -> stop fetching, keep what we have
ABORT_CODES = {"SESSION_EXPIRED", "NO_SESSION_AVAILABLE", "RATE_LIMITED", "ENDPOINT_CHANGED", "INTERNAL"}


def _merge(a: dict | None, b: dict | None) -> dict:
    return {**(a or {}), **(b or {})}


class PipelineState(TypedDict, total=False):
    run_id: str
    idx: int
    aborted: str | None
    fetched: Annotated[list[Fetched], operator.add]
    errors: Annotated[list[str], operator.add]
    candidates: list[Candidate]
    scored: list[ScoredTweet]
    selected: list[ScoredTweet]
    stats: Annotated[dict[str, Any], _merge]
    exports: list[str]
    status: str
    # PHASE 4: names of queries already attempted. Persisted in the checkpoint so a resumed
    # run restarts at the next query instead of re-scraping X for work already done.
    done_queries: Annotated[list[str], operator.add]


@dataclass
class Deps:
    client: ScrapeClient
    store: Store
    cfg: PipelineConfig
    settings: Settings
    scorer: Scorer | None = None  # None => heuristic only
    scorer_label: str = "heuristic"
    out_dir: Path = Path("data/out")
    webhook_url: str | None = None
    rescore: bool = False  # NEW FEATURE (P3.1): ignore the 'already seen' filter and re-score stored tweets


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]


def _llm_err(e: Exception) -> str:
    """UPDATED LOGIC (P3.1): short, readable LLM error (Ollama's raw errors are very long)."""
    first = (str(e).splitlines() or [""])[0]
    if "llama-server" in first:
        first = "Ollama model runner missing (broken install) - reinstall Ollama"
    return f"{type(e).__name__}: {first[:140]}"


def build_graph(d: Deps, checkpointer: Any | None = None):
    """Compile the pipeline graph.

    ``checkpointer`` (PHASE 4) enables durable resume. When supplied, the graph is compiled
    with it and every run must pass a stable ``thread_id``; omitting the thread_id while a
    checkpointer is attached raises inside LangGraph, which is the correct failure mode -
    silently running unresumable would defeat the point of checkpointing.
    """
    queries = [q for q in d.cfg.queries if q.enabled]
    profile = d.cfg.agency
    min_score = d.settings.min_score if d.settings.min_score is not None else d.cfg.min_score

    async def start_run(state: PipelineState) -> dict:
        # PHASE 4 resume safety: if a previous attempt already fetched some queries, start at
        # the next one instead of re-scraping X. `done_queries` is checkpointed with the rest
        # of the state, so a resumed run skips exactly the work already completed.
        done = list(state.get("done_queries") or [])
        start_idx = len(done)
        if start_idx > len(queries):
            start_idx = len(queries)
        d.store.start_run(state["run_id"], d.scorer_label, len(queries))
        log.info("[start_run] %s queries=%d scorer=%s min_score=%d resuming_at=%d",
                 state["run_id"], len(queries), d.scorer_label, min_score, start_idx)
        return {"idx": start_idx, "aborted": None,
                "stats": {"queries_total": len(queries), "min_score": min_score,
                          "resumed_at_query": start_idx}}

    async def fetch_next(state: PipelineState) -> dict:
        i = state["idx"]
        spec = queries[i]
        n = spec.max_results or d.cfg.max_results_per_query
        log.info("[fetch_next] (%d/%d) %s [%s]", i + 1, len(queries), spec.name, spec.type)
        try:
            resp = await d.client.search(spec.q, n)
        except Exception as e:  # noqa: BLE001 - MCP transport problem
            return {"idx": i + 1, "aborted": "MCP_TRANSPORT", "errors": [f"{spec.name}: MCP transport failure {e!r}"]}
        if resp.ok:
            items = [Fetched(tweet=t, query_name=spec.name, query_type=spec.type) for t in resp.tweets]
            return {"idx": i + 1, "fetched": items, "done_queries": [spec.name],
                    "stats": {f"fetched[{spec.name}]": len(items)}}
        err = resp.error
        msg = f"{spec.name}: {err.code} - {err.message}" + (f" (hint: {err.hint})" if err.hint else "")
        log.warning("[fetch_next] %s", msg)
        # A failed query is still "done" - resume must not retry an endpoint that just 429'd
        # or a session that just expired. The error is recorded and the run finishes cleanly.
        out: dict[str, Any] = {"idx": i + 1, "errors": [msg], "done_queries": [spec.name]}
        if err.code in ABORT_CODES:
            out["aborted"] = err.code
        return out

    def route_fetch(state: PipelineState) -> str:
        return "prefilter" if state.get("aborted") or state["idx"] >= len(queries) else "fetch_next"

    async def prefilter(state: PipelineState) -> dict:
        by_id: dict[str, Candidate] = {}
        dropped: Counter[str] = Counter()
        for f in state.get("fetched", []):
            t = f.tweet
            if t.id in by_id:
                dropped["duplicate"] += 1
                if f.query_name not in by_id[t.id].queries:
                    by_id[t.id].queries.append(f.query_name)
                continue
            reason = prefilter_reason(t, f.query_type)
            if reason:
                dropped[reason] += 1
                continue
            by_id[t.id] = Candidate(tweet=t, queries=[f.query_name], query_type=f.query_type)
        known = set() if d.rescore else d.store.known_ids(list(by_id))  # UPDATED LOGIC (P3.1)
        for tid in known:
            del by_id[tid]
        dropped["already_seen"] += len(known)
        cands = list(by_id.values())
        log.info("[prefilter] fetched=%d candidates=%d dropped=%s", len(state.get("fetched", [])), len(cands), dict(dropped))
        return {"candidates": cands, "stats": {"fetched_total": len(state.get("fetched", [])), "candidates": len(cands),
                                               "dropped": dict(dropped),
                                               "followers_known": sum(1 for c in cands if c.tweet.author_followers is not None)}}

    def route_prefilter(state: PipelineState) -> str:
        return "score" if state.get("candidates") else "finish"

    async def score(state: PipelineState) -> dict:
        cands = state["candidates"]
        heur = {c.tweet.id: heuristic_score(c, profile) for c in cands}
        order = sorted(cands, key=lambda c: heur[c.tweet.id].score, reverse=True)
        llm_ids = {c.tweet.id for c in order[: d.settings.llm_top_n]} if d.scorer else set()
        scored: list[ScoredTweet] = []
        errors: list[str] = []
        fails, llm_off, llm_n = 0, d.scorer is None, 0
        for c in order:
            h = heur[c.tweet.id]
            result, by = h, "heuristic"
            if c.tweet.id in llm_ids and not llm_off:
                try:
                    result = await asyncio.wait_for(d.scorer.score(c, profile), timeout=d.settings.llm_timeout_s)  # type: ignore[union-attr]
                    by, fails, llm_n = d.scorer.label, 0, llm_n + 1  # type: ignore[union-attr]
                except Exception as e:  # noqa: BLE001 - per-tweet fallback to heuristic
                    fails += 1
                    by = "heuristic(llm_failed)"
                    errors.append(f"LLM failed on {c.tweet.id}: {_llm_err(e)}")
                    if fails >= 3:
                        llm_off = True
                        errors.append("LLM disabled after 3 consecutive failures; remaining tweets use heuristic")
            scored.append(ScoredTweet(tweet=c.tweet, queries=c.queries, query_type=c.query_type, score=result,
                                      heuristic_score=h.score, scored_by=by))
            log.info("[score] %s -> %3d %-5s by %s", c.tweet.id, result.score, result.category, by)
        return {"scored": scored, "errors": errors, "stats": {"llm_scored": llm_n, "heuristic_scored": len(scored) - llm_n}}

    async def select(state: PipelineState) -> dict:
        # UPDATED LOGIC (P3.1): rule-only scores must clear a stricter bar than LLM-judged scores
        heur_min = max(min_score, d.cfg.heuristic_min_score)
        sel = sorted((s for s in state["scored"]
                      if s.score.category != "noise"
                      and s.score.score >= (heur_min if s.scored_by.startswith("heuristic") else min_score)),
                     key=lambda s: s.score.score, reverse=True)
        log.info("[select] %d of %d scored (>= %d LLM / >= %d heuristic)", len(sel), len(state["scored"]), min_score, heur_min)
        return {"selected": sel, "stats": {"selected": len(sel), "thr_llm": min_score, "thr_heuristic": heur_min}}

    async def export(state: PipelineState) -> dict:
        run_id, sel = state["run_id"], state.get("selected", [])
        d.store.save_scored(run_id, state["scored"])  # persist ALL scored -> never re-scored
        exports: list[str] = []
        errors: list[str] = []
        if sel:
            exports.append(str(export_csv(sel, d.out_dir / f"leads_{run_id}.csv")))
            exports.append(str(export_json(sel, run_id, d.out_dir / f"leads_{run_id}.json")))
            if d.webhook_url:
                try:
                    status = await asyncio.to_thread(post_webhook, d.webhook_url, sel, run_id)
                    exports.append(f"webhook:{status}")
                except Exception as e:  # noqa: BLE001 - sink failure must not lose the run
                    errors.append(f"webhook failed: {type(e).__name__}: {e}"[:200])
        log.info("[export] db=saved %d, files/webhook=%s", len(state["scored"]), exports)
        return {"exports": exports, "errors": errors}

    async def finish(state: PipelineState) -> dict:
        errors = state.get("errors", [])
        status = "aborted" if state.get("aborted") else ("partial" if errors else "ok")
        stats = {**state.get("stats", {}), "status": status, "aborted": state.get("aborted")}
        d.store.finish_run(state["run_id"], status, stats, errors)
        log.info("[finish] status=%s errors=%d", status, len(errors))
        return {"status": status}

    def route_start(state: PipelineState) -> str:
        """PHASE 4: a resumed run whose queries are all done must skip straight to prefilter.

        Routing unconditionally to fetch_next would index past the end of the query list.
        """
        return "fetch_next" if state.get("idx", 0) < len(queries) else "prefilter"

    g = StateGraph(PipelineState)
    for name, fn in [("start_run", start_run), ("fetch_next", fetch_next), ("prefilter", prefilter), ("score", score),
                     ("select", select), ("export", export), ("finish", finish)]:
        g.add_node(name, fn)
    g.add_edge(START, "start_run")
    g.add_conditional_edges("start_run", route_start, {"fetch_next": "fetch_next", "prefilter": "prefilter"})
    g.add_conditional_edges("fetch_next", route_fetch, {"fetch_next": "fetch_next", "prefilter": "prefilter"})
    g.add_conditional_edges("prefilter", route_prefilter, {"score": "score", "finish": "finish"})
    g.add_edge("score", "select")
    g.add_edge("select", "export")
    g.add_edge("export", "finish")
    g.add_edge("finish", END)
    return g.compile(checkpointer=checkpointer)


def make_checkpointer(db_path: Path | str) -> "SQLiteSaver":
    """Build the SQLite checkpointer used for durable pipeline resume (PHASE 4)."""
    from .checkpoint import SQLiteSaver

    return SQLiteSaver(Path(db_path))


async def run_graph(
    d: Deps,
    on_update=None,
    thread_id: str | None = None,
    checkpointer: Any | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """Run the graph, streaming per-node updates to ``on_update(node, update)``.

    Returns the merged final view.

    Durable resume (PHASE 4): pass ``checkpointer`` and a stable ``thread_id``. With
    ``resume=True`` the saved state is restored instead of starting from scratch, so a run
    interrupted after fetching can continue from its checkpoint. ``Store.save_scored`` uses
    ``INSERT OR IGNORE`` for tweets and ``INSERT OR REPLACE`` for scores, which are keyed on
    ``tweet_id``, so a resumed run cannot duplicate rows.
    """
    graph = build_graph(d, checkpointer=checkpointer)

    config: dict[str, Any] = {"recursion_limit": 200}
    init: PipelineState = {}
    merged: dict[str, Any] = {"errors": []}

    if checkpointer is not None:
        config["configurable"] = {"thread_id": thread_id or new_run_id()}
        if resume:
            saved = checkpointer.get_tuple(config)
            if saved is not None:
                log.info("Resuming thread %s from checkpoint %s",
                         config["configurable"]["thread_id"], saved.checkpoint.get("id"))
                init = {**saved.checkpoint.get("channel_values", {}), "run_id": new_run_id()}
            else:
                log.info("No checkpoint for thread %s; starting fresh",
                         config["configurable"]["thread_id"])
        if not init:
            init = {"run_id": new_run_id()}
    else:
        init = {"run_id": new_run_id()}

    merged["run_id"] = init["run_id"]

    async for chunk in graph.astream(init, config=config, stream_mode="updates"):
        for node, upd in chunk.items():
            if on_update:
                on_update(node, upd)
            for k, v in (upd or {}).items():
                if k == "errors":
                    merged["errors"] += v
                elif k == "stats":
                    merged.setdefault("stats", {}).update(v)  # UPDATED LOGIC: merge, don't overwrite
                else:
                    merged[k] = v
    return merged


def describe(node: str, upd: dict | None) -> str:
    """One human-readable line per graph step (used by the CLI scripts)."""
    upd = upd or {}
    st, errs = upd.get("stats", {}), upd.get("errors") or []
    if node == "start_run":
        return f"run started ({st.get('queries_total')} queries, min_score {st.get('min_score')})"
    if node == "fetch_next":
        got = ", ".join(f"{k[8:-1]}={v}" for k, v in st.items() if k.startswith("fetched["))
        return (f"fetched {got or '0'}" + (f" | ERROR: {errs[0]}" if errs else "")
                + (f" -> ABORT({upd['aborted']})" if upd.get("aborted") else ""))
    if node == "prefilter":
        return (f"{st.get('candidates')} new candidates from {st.get('fetched_total')} fetched; dropped {st.get('dropped')}; "
                f"author followers parsed for {st.get('followers_known')}/{st.get('candidates')}")
    if node == "score":
        return f"scored: llm={st.get('llm_scored')} heuristic={st.get('heuristic_scored')}" + (f" | {len(errs)} LLM issue(s): {errs[0]}" if errs else "")
    if node == "select":
        return f"{st.get('selected')} leads (threshold {st.get('thr_llm')} LLM-scored / {st.get('thr_heuristic')} rule-scored)"
    if node == "export":
        return f"saved to DB; outputs: {upd.get('exports') or 'none'}" + (f" | ERROR: {errs[0]}" if errs else "")
    if node == "finish":
        return f"status={upd.get('status')}"
    return str(upd)[:120]
