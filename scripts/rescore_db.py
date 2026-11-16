"""Re-score all tweets stored in SQLite using current scoring rules/LLM without re-scraping.

Usage:
  python -m scripts.rescore_db [--scorer auto|groq|ollama|heuristic] [--min-score 70]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import logging
from typing import Any

from leadsweep.config import get_settings
from leadsweep.models import Tweet
from leadsweep.pipeline.models import AgencyProfile, Candidate, QueryType, load_pipeline_config
from leadsweep.pipeline.scoring import heuristic_score, pick_scorer
from leadsweep.pipeline.store import Store, _now


async def main() -> int:
    ap = argparse.ArgumentParser(description="Re-score stored tweets in SQLite")
    ap.add_argument("--scorer", choices=["auto", "groq", "ollama", "heuristic"], default=None)
    ap.add_argument("--min-score", type=int, default=70)
    args = ap.parse_args()

    s = get_settings()
    logging.basicConfig(level="WARNING")
    cfg = load_pipeline_config(s.queries_file)

    scorer, label = await pick_scorer(args.scorer or s.llm_provider, s)
    print(f"Scorer: {label}")
    store = Store(s.db_path)

    # Fetch all stored tweets with their existing query info
    rows = list(store.db.execute("""
        SELECT t.id, t.url, t.text, t.author_username, t.author_name, t.author_followers,
               t.created_at, t.lang, t.like_count, t.retweet_count, t.reply_count,
               t.quote_count, t.view_count, t.is_reply, t.scraped_at,
               s.queries, s.query_type
        FROM tweets t
        LEFT JOIN scores s ON s.tweet_id = t.id
    """))

    total = len(rows)
    print(f"Loaded {total} stored tweets from {s.db_path}")
    if total == 0:
        store.close()
        return 0

    re_scored = 0
    selected = 0
    run_id = f"rescore-{_now().replace(':', '').replace('-', '')}"

    for r in rows:
        t = Tweet(
            id=r["id"],
            url=r["url"],
            text=r["text"],
            author_username=r["author_username"],
            author_name=r["author_name"],
            author_followers=r["author_followers"],
            created_at=datetime.datetime.fromisoformat(r["created_at"]) if r["created_at"] else None,
            lang=r["lang"],
            like_count=r["like_count"] or 0,
            retweet_count=r["retweet_count"] or 0,
            reply_count=r["reply_count"] or 0,
            quote_count=r["quote_count"] or 0,
            view_count=r["view_count"],
            is_reply=bool(r["is_reply"]),
            scraped_at=datetime.datetime.fromisoformat(r["scraped_at"]) if r["scraped_at"] else datetime.datetime.now(datetime.timezone.utc),
        )
        queries = (r["queries"] or "unknown").split(",")
        qtype: QueryType = r["query_type"] or "lead"
        cand = Candidate(tweet=t, queries=queries, query_type=qtype)

        # 1. Rule score
        h = heuristic_score(cand, cfg.agency)
        score_res = h
        scored_by = "heuristic"

        # 2. LLM score if eligible (e.g. top signal or forced)
        if scorer is not None and h.score >= 50:
            try:
                score_res = await asyncio.wait_for(scorer.score(cand, cfg.agency), timeout=30.0)
                scored_by = scorer.label
            except Exception:  # noqa: BLE001
                scored_by = "heuristic(llm_failed)"

        # Update in database
        store.db.execute(
            """UPDATE scores SET run_id=?, score=?, category=?, signals=?, reason=?, action=?,
               scored_by=?, heuristic_score=?, scored_at=? WHERE tweet_id=?""",
            (
                run_id,
                score_res.score,
                score_res.category,
                json.dumps(score_res.intent_signals),
                score_res.reason,
                score_res.suggested_action,
                scored_by,
                h.score,
                _now(),
                t.id,
            ),
        )
        re_scored += 1
        if score_res.category != "noise" and score_res.score >= args.min_score:
            selected += 1

    store.db.commit()
    store.close()
    print(f"Re-scored {re_scored} tweets. Selected {selected} leads >= {args.min_score}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
