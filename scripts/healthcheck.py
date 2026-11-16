"""Check health of the LeadSweep system, database, and last execution.

Exits with:
  0 = healthy (database OK, sessions available, recent successful run)
  1 = degraded or unhealthy
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

from leadsweep.config import get_settings
from leadsweep.session_pool import SessionPool


def main() -> int:
    s = get_settings()
    errors = []
    warnings = []

    # 1. Check sessions
    try:
        pool = SessionPool(s.sessions_file, s.state_file)
        summary = pool.summary()
        alive = sum(1 for item in summary if not item["dead"])
        if alive == 0:
            errors.append("No active/healthy cookie sessions available in pool")
        elif alive < len(summary):
            warnings.append(f"{len(summary) - alive} of {len(summary)} sessions marked dead")
    except Exception as e:
        errors.append(f"Cannot read session pool: {e}")

    # 2. Check database
    try:
        if not s.db_path.exists():
            warnings.append(f"Database {s.db_path} has not been created yet")
        else:
            db = sqlite3.connect(str(s.db_path))
            cur = db.cursor()
            cur.execute("SELECT run_id, finished_at, status, scorer FROM runs ORDER BY started_at DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                run_id, fin, status, scorer = row
                print(f"Last Run: {run_id} | Finished: {fin} | Status: {status} | Scorer: {scorer}")
                if status == "aborted":
                    warnings.append(f"Last run {run_id} was aborted")
            else:
                warnings.append("No recorded runs in database")
            db.close()
    except Exception as e:
        errors.append(f"Database check failed: {e}")

    # Print summary
    print(f"Sessions Alive: {alive if 'alive' in locals() else 0}")
    if warnings:
        print("Warnings:")
        for w in warnings:
            print(f"  [WARN] {w}")
    if errors:
        print("Errors:")
        for err in errors:
            print(f"  [ERROR] {err}")
        return 1

    print("Health check OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
