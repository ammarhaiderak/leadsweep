"""Test helper: mint a real login session instead of forging tokens."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from leadsweep.config import get_settings
from leadsweep.pipeline.store import Store


def make_session_token(email: str, role: str = "user") -> str:
    """Create (or reuse) an APPROVED user and return a valid bearer token for it."""
    store = Store(get_settings().db_path)
    try:
        now = datetime.now(timezone.utc)
        row = store.db.execute("SELECT id FROM app_users WHERE lower(email) = lower(?)", (email,)).fetchone()
        if row:
            user_id = row["id"]
            store.db.execute("UPDATE app_users SET role = ? WHERE id = ?", (role, user_id))
        else:
            user_id = f"usr_{uuid.uuid4().hex[:12]}"
            store.db.execute(
                "INSERT INTO app_users (id, email, name, password_hash, role, plan, status, credits, early_access_status, created_at)"
                " VALUES (?, ?, ?, 'x', ?, 'Test', 'APPROVED', 10, 1, ?)",
                (user_id, email, email.split("@")[0], role, now.isoformat()),
            )
        token = f"tok_{secrets.token_urlsafe(16)}"
        store.db.execute(
            "INSERT INTO auth_sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now.isoformat(), (now + timedelta(hours=1)).isoformat()),
        )
        store.db.commit()
        return token
    finally:
        store.close()
