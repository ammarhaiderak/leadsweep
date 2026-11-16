"""Owner Account Bootstrap & Password Reset CLI.

Securely creates or resets the platform owner account in SQLite without exposing
passwords on argv or stdout. Password is read exclusively through getpass.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def create_or_reset_owner(db_path: Path | str, email: str, password: str) -> None:
    """Create or reset owner account in app_users table."""
    clean_email = email.strip().lower()
    if not clean_email or "@" not in clean_email:
        raise ValueError("Invalid owner email address.")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")

    pwd_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        existing = conn.execute("SELECT id FROM app_users WHERE lower(email) = ?", (clean_email,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE app_users 
                SET password_hash = ?, role = 'owner', status = 'APPROVED', early_access_status = 1
                WHERE lower(email) = ?
                """,
                (pwd_hash, clean_email),
            )
        else:
            conn.execute(
                """
                INSERT INTO app_users (id, email, name, password_hash, role, plan, status, credits, early_access_status, created_at)
                VALUES ('usr_owner_bootstrap', ?, 'Platform Owner', ?, 'owner', 'Enterprise Owner', 'APPROVED', 999999, 1, ?)
                """,
                (clean_email, pwd_hash, now_iso),
            )
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    from leadsweep.config import get_settings
    settings = get_settings()

    parser = argparse.ArgumentParser(description="Create or reset platform owner account.")
    parser.add_argument("--email", default=None, help="Owner email (defaults to LEADSWEEP_OWNER_EMAIL)")
    parser.add_argument("--db-path", default=None, help="Path to SQLite database (defaults to LEADSWEEP_DB_PATH)")
    args = parser.parse_args()

    owner_email = args.email or settings.admin_email or settings.owner_email
    if not owner_email:
        print("ERROR: pass --email or set LEADSWEEP_ADMIN_EMAIL in .env", file=sys.stderr)
        return 1
    target_db = Path(args.db_path) if args.db_path else settings.db_path

    if not target_db.exists():
        # Ensure schema initialized
        from leadsweep.pipeline.store import Store
        Store(target_db).close()

    try:
        pw1 = getpass.getpass(f"Enter new password for owner [{owner_email}]: ")
        pw2 = getpass.getpass("Confirm password: ")
        if pw1 != pw2:
            print("ERROR: Passwords do not match.", file=sys.stderr)
            return 1

        create_or_reset_owner(target_db, owner_email, pw1)
        print(f"[OK] Owner account '{owner_email}' configured successfully (role=owner, status=APPROVED).")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
