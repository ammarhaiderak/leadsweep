"""Comprehensive status dashboard for LeadSweep: sessions, runs, canary, and storage.

Usage:
  python -m scripts.status
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from leadsweep.config import get_settings
from leadsweep.session_pool import SessionPool


def main() -> int:
    s = get_settings()

    print("=" * 60)
    print("                LEADSWEEP SYSTEM STATUS DASHBOARD")
    print("=" * 60)

    # 1. Sessions
    print("\n[1] SESSION POOL")
    try:
        pool = SessionPool(s.sessions_file, s.state_file)
        summary = pool.summary()
        for idx, sess in enumerate(summary, start=1):
            state = "DEAD" if sess["dead"] else ("COOLING" if sess["cooldown_s"] > 0 else "READY")
            cooldown = f" (cooldown {sess['cooldown_s']}s)" if sess["cooldown_s"] > 0 else ""
            reason = f" - Reason: {sess['reason']}" if sess["reason"] else ""
            print(f"  [{idx}] {sess['id']}: {state}{cooldown}{reason}")
    except Exception as e:
        print(f"  Error reading session pool: {e}")

    # 2. Scorer & Config
    print("\n[2] SCORER & CONFIG")
    print(f"  Configured Provider: {s.llm_provider}")
    print(f"  Groq Key Set:        {'YES' if bool(s.groq_api_key) else 'NO'}")
    print(f"  Groq Model:          {s.groq_model}")
    print(f"  Webhook Configured:  {s.webhook_url or 'None (stderr only)'}")

    # 3. Database & Recent Runs
    print("\n[3] DATABASE & RUNS")
    if s.db_path.exists():
        size_kb = s.db_path.stat().st_size / 1024
        print(f"  Database Path:       {s.db_path} ({size_kb:.1f} KB)")
        try:
            db = sqlite3.connect(str(s.db_path))
            cur = db.cursor()
            cur.execute("SELECT COUNT(*) FROM tweets")
            total_tweets = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM scores WHERE score >= 70 AND category != 'noise'")
            high_leads = cur.fetchone()[0]
            print(f"  Total Tweets Stored: {total_tweets}")
            print(f"  Qualified Leads (>=70): {high_leads}")

            cur.execute("SELECT run_id, started_at, status, scorer FROM runs ORDER BY started_at DESC LIMIT 5")
            runs = cur.fetchall()
            print("  Recent Runs:")
            for r in runs:
                print(f"    - {r[0]} | {r[1]} | status={r[2]} | scorer={r[3]}")
            db.close()
        except Exception as e:
            print(f"  Error reading database statistics: {e}")
    else:
        print(f"  Database Path:       {s.db_path} (Not created yet)")

    # 4. Canary Status
    print("\n[4] CANARY HEALTH")
    canary_file = Path("data/debug/canary_last.json")
    if canary_file.exists():
        try:
            canary_data = json.loads(canary_file.read_text(encoding="utf-8"))
            print(f"  Last Canary Check:   {canary_data.get('timestamp')}")
            print(f"  SearchTimeline:      {'PASS' if canary_data.get('search_timeline_ok') else 'FAIL'}")
            print(f"  Profile Timeline:    {'PASS' if canary_data.get('profile_timeline_ok') else 'FAIL'}")
            print(f"  Overall Status:      {canary_data.get('status', 'unknown').upper()}")
        except Exception as e:
            print(f"  Error parsing canary report: {e}")
    else:
        print("  Canary Report:       None (run 'python -m scripts.canary' to generate)")

    print("\n" + "=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
