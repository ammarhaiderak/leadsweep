"""Read leads back from SQLite.  Run: python -m scripts.show_leads [--min-score 60] [--limit 20] [--days 7]"""
from __future__ import annotations

import argparse

from leadsweep.config import get_settings
from leadsweep.pipeline.store import Store


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-score", type=int, default=60)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--days", type=int)
    args = ap.parse_args()
    s = get_settings()
    if not s.db_path.exists():
        print(f"No database yet at {s.db_path}. Run: python -m scripts.run_pipeline")
        return 1
    store = Store(s.db_path)
    rows = store.top_leads(args.min_score, args.limit, args.days)
    for r in rows:
        print(f"{r['score']:3d} {r['category']:<5} @{r['author_username']} ({r['author_followers']}) [{r['queries']}] via {r['scored_by']}")
        print(f"    {' '.join(r['text'].split())[:110]!r}\n    {r['url']}\n    why: {(r['reason'] or '')[:130]}")
    runs = store.db.execute("SELECT run_id, status, scorer, started_at FROM runs ORDER BY started_at DESC LIMIT 3").fetchall()
    print(f"\n{len(rows)} lead(s) >= {args.min_score}.  Last runs: " + "; ".join(f"{r['run_id']}:{r['status']}" for r in runs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
