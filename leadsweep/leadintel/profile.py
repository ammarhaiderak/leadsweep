# NEW FEATURE: Lead Intelligence User Sales Profile Store
"""
Manages the user's reusable "What I sell" sales profile.
Stored in SQLite table `li_profile`. Allows users to define what they sell once,
so future queries need no clarifying questions.
"""
import json
import sqlite3
import logging
from typing import Optional, Dict, Any, List

log = logging.getLogger("leadsweep.leadintel.profile")


def get_user_profile(conn: sqlite3.Connection, user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve existing 'What I sell' profile for user."""
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT user_id, offer, offer_type, icp_roles, icp_domains, updated_at
            FROM li_profile WHERE user_id = ?
        """, (user_id,))
        row = cursor.fetchone()
        if row:
            return {
                "user_id": row[0],
                "offer": row[1],
                "offer_type": row[2] or "services",
                "icp_roles": json.loads(row[3]) if row[3] else [],
                "icp_domains": json.loads(row[4]) if row[4] else [],
                "updated_at": row[5]
            }
    except Exception as e:
        log.warning(f"Failed to fetch user sales profile: {e}")
    return None


def save_user_profile(
    conn: sqlite3.Connection,
    user_id: str,
    offer: str,
    offer_type: str = "services",
    icp_roles: Optional[List[str]] = None,
    icp_domains: Optional[List[str]] = None
) -> None:
    """Save or update user's 'What I sell' profile."""
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO li_profile (user_id, offer, offer_type, icp_roles, icp_domains, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                offer = excluded.offer,
                offer_type = excluded.offer_type,
                icp_roles = excluded.icp_roles,
                icp_domains = excluded.icp_domains,
                updated_at = CURRENT_TIMESTAMP;
        """, (
            user_id,
            offer,
            offer_type,
            json.dumps(icp_roles or []),
            json.dumps(icp_domains or [])
        ))
        conn.commit()
    except Exception as e:
        log.error(f"Failed to save user sales profile: {e}")


def get_user_sales_profile(user_id: str = "default_user") -> Optional[Dict[str, Any]]:
    """Convenience wrapper for getting user sales profile."""
    from leadsweep.leadintel.db import get_connection
    with get_connection() as conn:
        return get_user_profile(conn, user_id=user_id)


def save_user_sales_profile(
    offering: str,
    target_customer: str = "",
    deal_size_tier: str = "mid",
    user_id: str = "default_user",
) -> None:
    """Convenience wrapper for saving user sales profile."""
    from leadsweep.leadintel.db import get_connection
    with get_connection() as conn:
        save_user_profile(
            conn,
            user_id=user_id,
            offer=offering,
            offer_type="services",
            icp_roles=[target_customer] if target_customer else [],
            icp_domains=[deal_size_tier] if deal_size_tier else [],
        )

