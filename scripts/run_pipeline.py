"""Phase 3 runner (real scrape via MCP -> LangGraph -> SQLite/CSV/JSON/webhook).
Run:  python -m scripts.run_pipeline [--scorer auto|ollama|heuristic] [--only name1,name2] [--max-results N] [--headed]"""
from __future__ import annotations

import argparse
import asyncio
import logging

from leadsweep.config import get_settings
from leadsweep.pipeline.graph import Deps, describe, run_graph
from leadsweep.pipeline.mcp_client import McpScrapeClient
from leadsweep.pipeline.models import load_pipeline_config
from leadsweep.pipeline.scoring import pick_scorer
from leadsweep.pipeline.sinks import format_leads
from leadsweep.pipeline.store import Store


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scorer", choices=["auto", "groq", "ollama", "heuristic"], default=None)
    ap.add_argument("--only", help="comma-separated query names from queries.toml")
    ap.add_argument("--max-results", type=int, help="override max results per query")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--rescore", action="store_true", help="re-score tweets already in the DB (use after changing scoring rules)")  # NEW FEATURE
    args = ap.parse_args()

    s = get_settings()
    logging.basicConfig(level="WARNING")
    cfg = load_pipeline_config(s.queries_file)
    cfg.queries = [q for q in cfg.queries if q.enabled]
    if args.only:
        wanted = {n.strip() for n in args.only.split(",")}
        cfg.queries = [q for q in cfg.queries if q.name in wanted]
        if not cfg.queries:
            print(f"No queries match {wanted}. Available: see {s.queries_file}")
            return 1
    if args.max_results:
        cfg.max_results_per_query = args.max_results
        for q in cfg.queries:
            q.max_results = None

    print("Checking scorer (an Ollama test generation can take a minute on first model load)...")
    try:
        scorer, label = await pick_scorer(args.scorer or s.llm_provider, s)
    except RuntimeError as e:
        print(f"Scorer error: {e}")
        return 2
    print(f"Scorer: {label}\nQueries: {[q.name for q in cfg.queries]}\n")

    store = Store(s.db_path)
    try:
        async with McpScrapeClient(headed=args.headed) as client:
            d = Deps(client, store, cfg, s, scorer=scorer, scorer_label=label, out_dir=s.out_dir, webhook_url=s.webhook_url, rescore=args.rescore)
            r = await run_graph(d, on_update=lambda node, upd: print(f"[{node}] {describe(node, upd)}"))
    finally:
        store.close()

    print(f"\n=== {len(r.get('selected', []))} lead(s) selected (run {r['run_id']}, status {r.get('status')}) ===")
    print(format_leads(r.get("selected", [])))
    if r["errors"]:
        print("\nIssues:\n  " + "\n  ".join(r["errors"]))
    print(f"\nDB: {s.db_path}   |   inspect later: python -m scripts.show_leads --min-score 60")
    return 0 if r.get("status") in ("ok", "partial") else 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
