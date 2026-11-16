"""Perform a safe, online backup of the SQLite database using SQLite backup API.

Usage:
  python -m scripts.backup_db [--dest data/backups]
"""
from __future__ import annotations

import argparse
import datetime
import sqlite3
import sys
from pathlib import Path

from leadsweep.config import get_settings


def main() -> int:
    ap = argparse.ArgumentParser(description="Backup LeadSweep SQLite database")
    ap.add_argument("--dest", type=Path, default=Path("data/backups"))
    args = ap.parse_args()

    s = get_settings()
    src_path = s.db_path
    if not src_path.exists():
        print(f"Source database {src_path} does not exist.")
        return 1

    args.dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest_path = args.dest / f"leadsweep_{stamp}.db"

    print(f"Backing up {src_path} to {dest_path}...")
    src_conn = sqlite3.connect(str(src_path))
    dest_conn = sqlite3.connect(str(dest_path))

    with dest_conn:
        src_conn.backup(dest_conn)

    dest_conn.close()
    src_conn.close()

    print(f"Backup successful: {dest_path} ({dest_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
