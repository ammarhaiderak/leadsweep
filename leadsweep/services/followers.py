"""Follower Intelligence Service: targets, extractions, follower snapshots, and edges."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from leadsweep.config import Settings, get_settings
from leadsweep.models import XUser
from leadsweep.pipeline.store import Store
from leadsweep.scraper import XScraper

log = logging.getLogger("leadsweep.services.followers")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FollowersService:
    def __init__(self, store: Store | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.store = store or Store(self.settings.db_path)

    # ------------------------------------------------------------------ Targets
    def list_targets(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM targets"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY created_at DESC"
        return [dict(r) for r in self.store.db.execute(sql).fetchall()]

    def get_or_create_target(self, handle: str, kind: str = "competitor", notes: str = "") -> dict[str, Any]:
        handle = handle.strip().lstrip("@").lower()
        row = self.store.db.execute("SELECT * FROM targets WHERE handle = ?", (handle,)).fetchone()
        if row:
            return dict(row)
        target_id = f"tgt_{uuid.uuid4().hex[:12]}"
        now = _now()
        self.store.db.execute(
            "INSERT INTO targets (id, handle, kind, notes, enabled, created_at) VALUES (?, ?, ?, ?, 1, ?)",
            (target_id, handle, kind, notes, now),
        )
        self.store.db.commit()
        return dict(self.store.db.execute("SELECT * FROM targets WHERE id = ?", (target_id,)).fetchone())

    # ------------------------------------------------------------------ Follower Pull
    async def pull_followers(
        self,
        handle: str,
        limit: int = 50,
        scraper: XScraper | None = None,
        progress_cb: Any = None,
    ) -> dict[str, Any]:
        """Scrape followers for handle and update x_users, follow_edges, follower_runs."""
        target = self.get_or_create_target(handle)
        target_id = target["id"]
        run_id = f"frun_{uuid.uuid4().hex[:12]}"
        now = _now()

        self.store.db.execute(
            "INSERT INTO follower_runs (id, target_id, started_at, status) VALUES (?, ?, ?, 'running')",
            (run_id, target_id, now),
        )
        self.store.db.commit()

        if progress_cb:
            await progress_cb(10, f"Navigating to @{handle} followers...")

        users: list[XUser] = []
        error_code = None
        try:
            if scraper is not None:
                users = await scraper.followers_with_failover(handle, limit=limit)
            else:
                async with XScraper(self.settings) as sc:
                    users = await sc.followers_with_failover(handle, limit=limit)
        except Exception as e:
            error_code = type(e).__name__
            log.exception("Error extracting followers for @%s: %s", handle, e)
            self.store.db.execute(
                "UPDATE follower_runs SET finished_at=?, status='failed', error_code=? WHERE id=?",
                (_now(), error_code, run_id),
            )
            self.store.db.commit()
            raise

        if progress_cb:
            await progress_cb(60, f"Extracted {len(users)} profiles, persisting to database...")

        new_count = 0
        pulled_count = len(users)

        for u in users:
            # 1. Upsert x_users
            self.store.db.execute(
                """
                INSERT INTO x_users (
                    rest_id, handle, name, bio, location, website,
                    followers_count, following_count, tweets_count, listed_count,
                    created_at, is_blue_verified, verified_type, protected,
                    avatar_url, professional_category, first_seen_at, last_seen_at, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(rest_id) DO UPDATE SET
                    handle=excluded.handle,
                    name=excluded.name,
                    bio=excluded.bio,
                    location=excluded.location,
                    website=excluded.website,
                    followers_count=excluded.followers_count,
                    following_count=excluded.following_count,
                    tweets_count=excluded.tweets_count,
                    listed_count=excluded.listed_count,
                    is_blue_verified=excluded.is_blue_verified,
                    verified_type=excluded.verified_type,
                    avatar_url=excluded.avatar_url,
                    professional_category=excluded.professional_category,
                    last_seen_at=excluded.last_seen_at,
                    content_hash=excluded.content_hash
                """,
                (
                    u.rest_id,
                    u.handle,
                    u.name,
                    u.bio,
                    u.location,
                    u.website,
                    u.followers_count,
                    u.following_count,
                    u.tweets_count,
                    u.listed_count,
                    u.created_at.isoformat() if u.created_at else None,
                    1 if u.is_blue_verified else 0,
                    u.verified_type,
                    1 if u.protected else 0,
                    u.avatar_url,
                    u.professional_category,
                    u.first_seen_at.isoformat(),
                    u.last_seen_at.isoformat(),
                    u.content_hash,
                ),
            )

            # 2. Check if edge is new
            existing_edge = self.store.db.execute(
                "SELECT 1 FROM follow_edges WHERE target_id = ? AND user_id = ?",
                (target_id, u.rest_id),
            ).fetchone()
            if not existing_edge:
                new_count += 1
                self.store.db.execute(
                    "INSERT INTO follow_edges (target_id, user_id, first_seen_run, last_seen_run, active) VALUES (?, ?, ?, ?, 1)",
                    (target_id, u.rest_id, run_id, run_id),
                )
            else:
                self.store.db.execute(
                    "UPDATE follow_edges SET last_seen_run = ?, active = 1 WHERE target_id = ? AND user_id = ?",
                    (run_id, target_id, u.rest_id),
                )

        # 3. Score extracted followers using ICP heuristic rules
        try:
            from .icp_scoring import ICPScoringService
            icp_svc = ICPScoringService(self.store, self.settings)
            for u in users:
                icp_svc.score_heuristically(u)
        except Exception as e:
            log.warning("Follower ICP auto-scoring encountered issue: %s", e)

        # 4. Update target metadata
        self.store.db.execute(
            "UPDATE targets SET last_run_at = ? WHERE id = ?",
            (_now(), target_id),
        )

        # 5. Finalize follower_run
        self.store.db.execute(
            """
            UPDATE follower_runs
            SET finished_at = ?, pulled_count = ?, new_count = ?, status = 'succeeded'
            WHERE id = ?
            """,
            (_now(), pulled_count, new_count, run_id),
        )
        self.store.db.commit()

        if progress_cb:
            await progress_cb(100, f"Completed: pulled {pulled_count}, new {new_count}")

        return {
            "run_id": run_id,
            "target_id": target_id,
            "handle": handle,
            "pulled_count": pulled_count,
            "new_count": new_count,
            "users": [u.model_dump(mode="json") for u in users],
        }

    # ------------------------------------------------------------------ Query & Overlap
    def list_followers(
        self,
        target_handle: str | None = None,
        min_score: int | None = None,
        overlap_only: bool = False,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List followers with optional ICP qualification filter and multi-target overlap count."""
        sql = """
        SELECT
            u.rest_id, u.handle, u.name, u.bio, u.location, u.followers_count,
            u.is_blue_verified, u.last_seen_at,
            us.icp_score, us.persona, us.fit_reason,
            (SELECT COUNT(DISTINCT fe2.target_id) FROM follow_edges fe2 WHERE fe2.user_id = u.rest_id AND fe2.active = 1) as overlap_targets,
            (SELECT GROUP_CONCAT(t.handle, ', ')
             FROM follow_edges fe3
             JOIN targets t ON t.id = fe3.target_id
             WHERE fe3.user_id = u.rest_id AND fe3.active = 1) as followed_targets,
            lw.status as workflow_status
        FROM x_users u
        LEFT JOIN user_scores us ON us.user_id = u.rest_id
        LEFT JOIN lead_workflow lw ON lw.entity_id = u.rest_id AND lw.entity_type = 'user'
        """
        clauses = []
        args: list[Any] = []

        if target_handle:
            clauses.append("u.rest_id IN (SELECT fe.user_id FROM follow_edges fe JOIN targets t ON t.id = fe.target_id WHERE t.handle = ? AND fe.active = 1)")
            args.append(target_handle.strip().lstrip("@").lower())

        if min_score is not None:
            clauses.append("us.icp_score >= ?")
            args.append(min_score)

        if overlap_only:
            clauses.append("(SELECT COUNT(DISTINCT fe_sub.target_id) FROM follow_edges fe_sub WHERE fe_sub.user_id = u.rest_id AND fe_sub.active = 1) > 1")

        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        sql += " ORDER BY COALESCE(us.icp_score, 0) DESC, overlap_targets DESC, u.followers_count DESC LIMIT ?"
        args.append(limit)

        return [dict(r) for r in self.store.db.execute(sql, args).fetchall()]
