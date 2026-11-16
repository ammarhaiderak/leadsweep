"""Re-evaluate unevaluated rows of a scrape run.

Usage:
    python scripts/reevaluate.py <run_id>

Judges only rows where scored_by != 'llm' or category == 'unevaluated'.
Uses cache-aware pipeline and Groq free-tier pacing.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path

from leadsweep.config import get_settings
from leadsweep.pipeline.qualification_graph import lead_qualification_pipeline
from leadsweep.pipeline.store import _now


async def reevaluate_run(run_id: str) -> dict[str, int]:
    settings = get_settings()
    db_path = settings.db_path
    if not db_path.exists():
        print(f"Error: database {db_path} does not exist.")
        return {"total": 0, "unevaluated": 0, "rejudged": 0}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT run_id, status, items_count, error_detail, input_json FROM actor_runs WHERE run_id = ?", (run_id,))
    run_row = c.fetchone()
    if not run_row:
        print(f"Run {run_id} not found in actor_runs.")
        conn.close()
        return {"total": 0, "unevaluated": 0, "rejudged": 0}

    input_data = {}
    try:
        if run_row["input_json"]:
            input_data = json.loads(run_row["input_json"])
    except Exception:
        pass

    query_context = input_data.get("queries", [""])[0] if input_data.get("queries") else input_data.get("query", "")
    platform = input_data.get("platform", "twitter").lower()
    source_mode = input_data.get("type", "search")

    c.execute("SELECT tweet_id, score, category, scored_by, reason FROM scores WHERE run_id = ?", (run_id,))
    score_rows = c.fetchall()
    total_scores = len(score_rows)

    unevaluated = [
        r for r in score_rows
        if r["scored_by"] != "llm" or r["category"] == "unevaluated" or r["score"] is None
    ]

    print(f"Run {run_id}: {total_scores} total score rows, {len(unevaluated)} unevaluated.")
    if not unevaluated:
        print("All rows already evaluated by LLM. Nothing to re-evaluate.")
        conn.close()
        return {"total": total_scores, "unevaluated": 0, "rejudged": 0}

    rejudged_count = 0
    start_time = time.time()

    for row in unevaluated:
        tid = row["tweet_id"]
        # Lookup tweet text & author
        c.execute("SELECT id, author_username, author_name, author_followers, text FROM tweets WHERE id = ?", (tid,))
        tweet = c.fetchone()
        if not tweet:
            # Fallback to dataset_items
            c.execute("SELECT data_json FROM dataset_items WHERE id = ?", (tid,))
            ds_item = c.fetchone()
            if ds_item and ds_item[0]:
                try:
                    d = json.loads(ds_item[0])
                    tweet = {
                        "id": tid,
                        "author_username": d.get("author_username", ""),
                        "author_name": d.get("author_name", ""),
                        "author_followers": d.get("author_followers", 0),
                        "text": d.get("text", ""),
                    }
                except Exception:
                    tweet = None

        if not tweet or not tweet["text"]:
            print(f"  Item {tid}: no text found in database, skipping.")
            continue

        print(f"  Evaluating item {tid} (@{tweet['author_username']})...", end=" ", flush=True)
        t_row_start = time.time()
        try:
            qual_res = await lead_qualification_pipeline.ainvoke({
                "tweet_id": str(tid),
                "author_username": str(tweet["author_username"] or ""),
                "author_name": str(tweet["author_name"] or ""),
                "author_followers": int(tweet["author_followers"] or 0),
                "text": str(tweet["text"] or ""),
                "query_context": str(query_context),
                "search_mode": "lead_generation",
                "platform": platform,
                "source_mode": source_mode,
            })

            evaluator = qual_res.get("evaluator", "unevaluated")
            score = qual_res.get("buyer_intent_score")
            cat = qual_res.get("primary_category", "unevaluated")
            reason = qual_res.get("reasoning_summary") or qual_res.get("intent_reason", "")
            action = qual_res.get("suggested_angle", "")

            signals_data = {
                "technologies": qual_res.get("technologies", []),
                "evidence_spans": qual_res.get("evidence_spans", []),
                "primary_category": cat,
                "decision": qual_res.get("decision", "disqualified"),
                "lead_direction": qual_res.get("lead_direction", "UNCLEAR"),
                "direction_reason": qual_res.get("direction_reason", ""),
                "direction_evidence": qual_res.get("direction_evidence", ""),
                "evaluator": evaluator,
                "poster_role": qual_res.get("poster_role", "unknown"),
                "model_version": qual_res.get("model_version", "unknown"),
                "token_usage": qual_res.get("token_usage"),
            }

            now_dt = _now()
            conn.execute(
                """
                UPDATE scores
                SET score = ?, category = ?, signals = ?, reason = ?, action = ?, scored_by = ?, heuristic_score = ?, scored_at = ?
                WHERE tweet_id = ?
                """,
                (score, cat, json.dumps(signals_data), reason, action, evaluator, score, now_dt, tid),
            )
            conn.commit()

            row_elapsed = time.time() - t_row_start
            print(f"Done ({evaluator}, score={score}, {row_elapsed:.2f}s)")
            if evaluator == "llm":
                rejudged_count += 1
        except Exception as e:
            print(f"Failed: {e}")

    total_elapsed = time.time() - start_time
    # Update actor_runs status if all unevaluated rows were re-evaluated
    c.execute("SELECT count(*) FROM scores WHERE run_id = ? AND (scored_by != 'llm' OR score IS NULL OR category = 'unevaluated')", (run_id,))
    remaining_unevaluated = c.fetchone()[0]
    if remaining_unevaluated == 0:
        conn.execute("UPDATE actor_runs SET error_detail = NULL WHERE run_id = ?", (run_id,))
    else:
        conn.execute("UPDATE actor_runs SET error_detail = ? WHERE run_id = ?", (f"Partial: {remaining_unevaluated}/{total_scores} items unevaluated", run_id))
    conn.commit()
    conn.close()

    print(f"\nRe-evaluation finished in {total_elapsed:.2f}s: {rejudged_count}/{len(unevaluated)} newly evaluated by LLM. Remaining unevaluated: {remaining_unevaluated}.")
    return {"total": total_scores, "unevaluated": len(unevaluated), "rejudged": rejudged_count, "remaining": remaining_unevaluated}


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/reevaluate.py <run_id>")
        sys.exit(1)
    run_id = sys.argv[1]
    asyncio.run(reevaluate_run(run_id))


if __name__ == "__main__":
    main()
