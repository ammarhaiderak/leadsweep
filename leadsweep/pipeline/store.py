"""SQLite system of record (stdlib only, $0). Everything scored is stored, so tweets are never re-scored."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import ScoredTweet

SCHEMA = """
CREATE TABLE IF NOT EXISTS tweets(
  id TEXT PRIMARY KEY, url TEXT, text TEXT, author_username TEXT, author_name TEXT, author_followers INTEGER,
  created_at TEXT, lang TEXT, like_count INTEGER, retweet_count INTEGER, reply_count INTEGER, quote_count INTEGER,
  view_count INTEGER, is_reply INTEGER, scraped_at TEXT, first_run_id TEXT, platform TEXT DEFAULT 'twitter');
CREATE TABLE IF NOT EXISTS scores(
  tweet_id TEXT PRIMARY KEY, run_id TEXT, queries TEXT, query_type TEXT, score INTEGER, category TEXT, signals TEXT,
  reason TEXT, action TEXT, scored_by TEXT, heuristic_score INTEGER, scored_at TEXT);
CREATE TABLE IF NOT EXISTS runs(
  run_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, status TEXT, scorer TEXT, queries_total INTEGER,
  stats TEXT, errors TEXT);
CREATE INDEX IF NOT EXISTS idx_scores_score ON scores(score DESC);
"""


STUDIO_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS targets (
  id TEXT PRIMARY KEY,
  handle TEXT UNIQUE NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('competitor', 'influencer', 'customer', 'prospect')),
  notes TEXT,
  enabled INTEGER DEFAULT 1,
  schedule TEXT,
  caps_override TEXT,
  last_run_at TEXT,
  last_cursor TEXT,
  approx_followers INTEGER,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS x_users (
  rest_id TEXT PRIMARY KEY,
  handle TEXT NOT NULL,
  name TEXT,
  bio TEXT,
  location TEXT,
  website TEXT,
  followers_count INTEGER,
  following_count INTEGER,
  tweets_count INTEGER,
  listed_count INTEGER,
  created_at TEXT,
  is_blue_verified INTEGER,
  verified_type TEXT,
  protected INTEGER DEFAULT 0,
  avatar_url TEXT,
  professional_category TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  content_hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_x_users_handle ON x_users(handle);

CREATE TABLE IF NOT EXISTS follow_edges (
  target_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  first_seen_run TEXT NOT NULL,
  last_seen_run TEXT NOT NULL,
  active INTEGER DEFAULT 1,
  PRIMARY KEY (target_id, user_id),
  FOREIGN KEY (target_id) REFERENCES targets(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES x_users(rest_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_follow_edges_user ON follow_edges(user_id);

CREATE TABLE IF NOT EXISTS follower_runs (
  id TEXT PRIMARY KEY,
  target_id TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  pulled_count INTEGER DEFAULT 0,
  new_count INTEGER DEFAULT 0,
  lost_count INTEGER DEFAULT 0,
  coverage_percent REAL,
  status TEXT NOT NULL,
  error_code TEXT,
  FOREIGN KEY (target_id) REFERENCES targets(id)
);

CREATE TABLE IF NOT EXISTS user_scores (
  user_id TEXT PRIMARY KEY,
  icp_score INTEGER NOT NULL,
  persona TEXT,
  fit_reason TEXT,
  outreach_angle TEXT,
  scored_by TEXT NOT NULL,
  scored_at TEXT NOT NULL,
  rules_score INTEGER NOT NULL,
  FOREIGN KEY (user_id) REFERENCES x_users(rest_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_user_scores_icp ON user_scores(icp_score DESC);

CREATE TABLE IF NOT EXISTS lead_workflow (
  entity_id TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL CHECK(entity_type IN ('tweet', 'user')),
  status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new', 'reviewing', 'contacted', 'replied', 'won', 'lost', 'ignored')),
  owner TEXT,
  tags TEXT,
  notes TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
  id TEXT PRIMARY KEY,
  entity_id TEXT NOT NULL,
  entity_type TEXT NOT NULL CHECK(entity_type IN ('tweet', 'user')),
  label TEXT NOT NULL CHECK(label IN ('good', 'bad')),
  reason_code TEXT,
  note TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  params TEXT,
  status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'paused')),
  progress_percent INTEGER DEFAULT 0,
  current_step TEXT,
  result_summary TEXT,
  error_code TEXT,
  error_detail TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    """SQLite system of record.

    Connection handling: one long-lived connection with ``check_same_thread=False``, closed
    explicitly via :meth:`close`. Callers own the lifecycle (see the ``finally: store.close()``
    pattern throughout ``leadsweep/api.py``).
    """

    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)

        # Apply migration 002 if user_version < 2
        ver = self.db.execute("PRAGMA user_version").fetchone()[0]
        if ver < 2:
            self.db.executescript(STUDIO_SCHEMA_V2)
            self.db.execute("PRAGMA user_version = 2")
            self.db.commit()

        # Apply migration 003: enrichment fields on tweets and x_users
        if ver < 3:
            for col, col_def in [
                ("email", "TEXT"),
                ("linkedin_url", "TEXT"),
                ("company_website", "TEXT"),
                ("is_enriched", "INTEGER DEFAULT 0"),
                ("platform", "TEXT DEFAULT 'twitter'"),
            ]:
                try:
                    self.db.execute(f"ALTER TABLE tweets ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    pass  # already exists
                try:
                    self.db.execute(f"ALTER TABLE x_users ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    pass  # already exists
            self.db.execute("PRAGMA user_version = 3")
            self.db.commit()

        # Apply migration 004 (Phase B): Apify-class Runs, Datasets, and FTS5 search
        if ver < 4:
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS actor_runs (
                run_id TEXT PRIMARY KEY,
                actor_name TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'paused', 'succeeded', 'failed', 'aborted', 'hitl_pending')),
                input_json TEXT NOT NULL,
                dataset_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                items_count INTEGER DEFAULT 0,
                cursor_checkpoint TEXT,
                error_detail TEXT,
                session_id TEXT
            );

            CREATE TABLE IF NOT EXISTS dataset_items (
                id TEXT PRIMARY KEY,
                dataset_id TEXT NOT NULL,
                item_type TEXT NOT NULL,
                data_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_dataset_items_ds ON dataset_items(dataset_id);

            CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
                item_id,
                content_text,
                tokenize = 'porter unicode61'
            );
            """)
            self.db.execute("PRAGMA user_version = 4")
            self.db.commit()

        # Apply migration 005: Multi-user auth & admin management
        if ver < 5:
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS app_users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                plan TEXT NOT NULL DEFAULT 'Enterprise Admin',
                status TEXT NOT NULL DEFAULT 'APPROVED',
                credits INTEGER DEFAULT 100,
                early_access_status INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS auth_sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE CASCADE
            );
            """)
            # No account is pre-seeded: the owner is created on first sign-in from
            # LEADSWEEP_ADMIN_EMAIL / LEADSWEEP_ADMIN_PASSWORD (or scripts/create_owner.py).
            self.db.execute("PRAGMA user_version = 5")
            self.db.commit()

        # Apply migration 006: Early access, persistent scheduler, query cache & global intelligence
        if ver < 6:
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS early_access_requests (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                company TEXT,
                role TEXT,
                intended_use TEXT,
                website TEXT,
                status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'APPROVED', 'REJECTED', 'SUSPENDED')),
                created_at TEXT NOT NULL,
                approved_at TEXT,
                notes TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_ea_email ON early_access_requests(email);
            CREATE INDEX IF NOT EXISTS idx_ea_status ON early_access_requests(status);

            CREATE TABLE IF NOT EXISTS query_cache (
                query_hash TEXT PRIMARY KEY,
                raw_query TEXT NOT NULL,
                normalized_query TEXT NOT NULL,
                platform TEXT NOT NULL,
                intent_json TEXT,
                result_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                last_scraped_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_qc_norm ON query_cache(normalized_query, platform);

            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                platform TEXT NOT NULL,
                query TEXT NOT NULL,
                schedule_time TEXT NOT NULL DEFAULT '10:00',
                timezone TEXT NOT NULL DEFAULT 'Asia/Karachi',
                frequency TEXT NOT NULL DEFAULT 'daily',
                enabled INTEGER NOT NULL DEFAULT 1,
                last_run_at TEXT,
                next_run_at TEXT NOT NULL,
                last_status TEXT NOT NULL DEFAULT 'queued',
                items_per_run INTEGER NOT NULL DEFAULT 25,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sch_next ON scheduled_jobs(next_run_at, enabled);

            CREATE TABLE IF NOT EXISTS global_intelligence (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                source_id TEXT,
                source_url TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                username TEXT,
                headline TEXT,
                content TEXT,
                profile_url TEXT,
                email TEXT,
                phone TEXT,
                website TEXT,
                data_json TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_gi_platform ON global_intelligence(platform, source_id);
            """)

            # Add status column to app_users if not present
            try:
                self.db.execute("ALTER TABLE app_users ADD COLUMN status TEXT DEFAULT 'APPROVED'")
            except sqlite3.OperationalError:
                pass

            self.db.execute("PRAGMA user_version = 6")
            self.db.commit()

        # Apply migration 007: Production Owner Access Requests & Audit Logging
        if ver < 7:
            for col, col_def in [
                ("reviewed_by", "TEXT"),
                ("reviewed_at", "TEXT"),
                ("rejected_at", "TEXT"),
                ("approval_reason", "TEXT"),
                ("rejection_reason", "TEXT"),
                ("notification_status", "TEXT DEFAULT 'PENDING'"),
                ("notification_sent_at", "TEXT"),
                ("notification_error", "TEXT"),
            ]:
                try:
                    self.db.execute(f"ALTER TABLE early_access_requests ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    pass

            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id TEXT PRIMARY KEY,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT,
                metadata_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);
            CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_logs(created_at DESC);
            """)

            # Migration version 7
            pass

            self.db.execute("PRAGMA user_version = 7")
            self.db.commit()

        # Apply migration 008: Store password hash in early_access_requests
        if ver < 8:
            try:
                self.db.execute("ALTER TABLE early_access_requests ADD COLUMN password_hash TEXT")
            except sqlite3.OperationalError:
                pass
            self.db.execute("PRAGMA user_version = 8")
            self.db.commit()

        # Apply migration 010: Persistent User Activity Events & Actor Run Tenancy & App Users Credits
        if ver < 10:
            for col, col_def in [
                ("credits", "INTEGER DEFAULT 100"),
                ("early_access_status", "INTEGER DEFAULT 1"),
            ]:
                try:
                    self.db.execute(f"ALTER TABLE app_users ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    pass

            for col, col_def in [
                ("user_id", "TEXT"),
                ("user_email", "TEXT"),
            ]:
                try:
                    self.db.execute(f"ALTER TABLE actor_runs ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    pass

            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS activity_events (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                user_email TEXT NOT NULL,
                category TEXT NOT NULL,
                event_type TEXT NOT NULL,
                description TEXT NOT NULL,
                resource_type TEXT,
                resource_id TEXT,
                status TEXT NOT NULL DEFAULT 'completed',
                metadata_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_activity_user ON activity_events(user_email, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_activity_category ON activity_events(category);
            CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_events(created_at DESC);
            """)
        # Apply migration 011: Enhanced Admin Audit Logs & Analytics Tenancy
        if ver < 11:
            for col, col_def in [
                ("ip_address", "TEXT"),
                ("severity", "TEXT DEFAULT 'INFO'"),
                ("user_email", "TEXT"),
            ]:
                try:
                    self.db.execute(f"ALTER TABLE audit_logs ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    pass

            for col, col_def in [
                ("user_email", "TEXT"),
            ]:
                try:
                    self.db.execute(f"ALTER TABLE tweets ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    pass

            self.db.execute("PRAGMA user_version = 11")
            self.db.commit()

        for col, col_def in [
            ("request_count", "INTEGER DEFAULT 1"),
            ("last_requested_at", "TEXT"),
        ]:
            try:
                self.db.execute(f"ALTER TABLE early_access_requests ADD COLUMN {col} {col_def}")
            except sqlite3.OperationalError:
                pass

        # Legacy column: plaintext passwords used to be stored here. The column is kept for
        # schema compatibility but is always NULL, and any old values are wiped.
        for col, tbl in [("plain_password", "app_users"), ("plain_password", "early_access_requests")]:
            try:
                self.db.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass
            self.db.execute(f"UPDATE {tbl} SET {col} = NULL WHERE {col} IS NOT NULL")

        # Migration: system_notifications & password_resets & user company profile
        try:
            self.db.execute("ALTER TABLE app_users ADD COLUMN company TEXT DEFAULT 'Personal Workspace'")
        except sqlite3.OperationalError:
            pass

        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS system_notifications (
            id TEXT PRIMARY KEY,
            user_email TEXT,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'SYSTEM',
            severity TEXT NOT NULL DEFAULT 'INFO',
            link_url TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sys_notif_email ON system_notifications(user_email, created_at DESC);

        CREATE TABLE IF NOT EXISTS password_resets (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            token TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pwd_resets_token ON password_resets(token);
        """)

        self.db.execute("PRAGMA user_version = 15")
        self.db.commit()




    def close(self) -> None:
        self.db.close()

    def known_ids(self, ids: list[str]) -> set[str]:
        out: set[str] = set()
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            q = f"SELECT id FROM tweets WHERE id IN ({','.join('?' * len(chunk))})"
            out |= {r["id"] for r in self.db.execute(q, chunk)}
        return out

    def start_run(self, run_id: str, scorer: str, queries_total: int) -> None:
        self.db.execute("INSERT OR REPLACE INTO runs(run_id, started_at, status, scorer, queries_total) VALUES(?,?,?,?,?)",
                        (run_id, _now(), "running", scorer, queries_total))
        self.db.commit()

    def finish_run(self, run_id: str, status: str, stats: dict[str, Any], errors: list[str]) -> None:
        self.db.execute("UPDATE runs SET finished_at=?, status=?, stats=?, errors=? WHERE run_id=?",
                        (_now(), status, json.dumps(stats, default=str), json.dumps(errors), run_id))
        self.db.commit()

    def save_scored(self, run_id: str, items: list[ScoredTweet]) -> None:
        for s in items:
            t = s.tweet
            self.db.execute(
                """
                INSERT OR IGNORE INTO tweets(
                    id, url, text, author_username, author_name, author_followers,
                    created_at, lang, like_count, retweet_count, reply_count,
                    quote_count, view_count, is_reply, scraped_at, first_run_id
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (t.id, t.url, t.text, t.author_username, t.author_name, t.author_followers,
                 t.created_at.isoformat() if t.created_at else None, t.lang, t.like_count, t.retweet_count,
                 t.reply_count, t.quote_count, t.view_count, int(t.is_reply), t.scraped_at.isoformat(), run_id))
            self.db.execute(
                """
                INSERT INTO scores(
                    tweet_id, run_id, queries, query_type, score, category,
                    signals, reason, action, scored_by, heuristic_score, scored_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(tweet_id) DO UPDATE SET
                    run_id=excluded.run_id,
                    queries=excluded.queries,
                    query_type=excluded.query_type,
                    score=excluded.score,
                    category=excluded.category,
                    signals=excluded.signals,
                    reason=excluded.reason,
                    action=excluded.action,
                    scored_by=excluded.scored_by,
                    heuristic_score=excluded.heuristic_score,
                    scored_at=excluded.scored_at
                WHERE excluded.scored_by = 'llm' OR scores.scored_by != 'llm'
                """,
                (t.id, run_id, ",".join(s.queries), s.query_type, s.score.score, s.score.category,
                 json.dumps(s.score.intent_signals), s.score.reason, s.score.suggested_action, s.scored_by,
                 s.heuristic_score, _now()))
        self.db.commit()

    def top_leads(self, min_score: int = 0, limit: int = 20, days: int | None = None) -> list[sqlite3.Row]:
        sql = ("SELECT s.score, s.category, s.queries, s.scored_by, s.reason, s.action, t.author_username, t.author_followers, "
               "t.like_count, t.text, t.url, s.scored_at FROM scores s JOIN tweets t ON t.id = s.tweet_id "
               "WHERE s.score >= ? AND s.category != 'noise'")
        args: list[Any] = [min_score]
        if days:
            sql += " AND s.scored_at >= datetime('now', ?)"
            args.append(f"-{int(days)} days")
        sql += " ORDER BY s.score DESC, s.scored_at DESC LIMIT ?"
        args.append(limit)
        return list(self.db.execute(sql, args))

    def insert_tweets(self, tweets: list[Any], run_id: str | None = None, platform: str = "twitter") -> None:
        """Insert a batch of Tweet models or dicts directly into the tweets table."""
        now_str = _now()
        for t in tweets:
            t_id = getattr(t, "id", None) or (t.get("id") if isinstance(t, dict) else None)
            if not t_id:
                continue
            t_url = getattr(t, "url", None) or (t.get("url") if isinstance(t, dict) else None) or f"https://x.com/status/{t_id}"
            t_text = getattr(t, "text", None) or (t.get("text") if isinstance(t, dict) else None) or ""
            author_user = getattr(t, "author_username", None) or (t.get("author_username") if isinstance(t, dict) else None)
            author_name = getattr(t, "author_name", None) or (t.get("author_name") if isinstance(t, dict) else None)
            author_followers = getattr(t, "author_followers", None) or (t.get("author_followers") if isinstance(t, dict) else None)
            created_at = getattr(t, "created_at", None) or (t.get("created_at") if isinstance(t, dict) else None)
            created_at_str = created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at or now_str)
            if created_at_str and " " in created_at_str and "T" not in created_at_str:
                created_at_str = created_at_str.replace(" ", "T", 1)
            lang = getattr(t, "lang", None) or (t.get("lang") if isinstance(t, dict) else None)
            likes = getattr(t, "like_count", 0) or (t.get("like_count", 0) if isinstance(t, dict) else 0)
            retweets = getattr(t, "retweet_count", 0) or (t.get("retweet_count", 0) if isinstance(t, dict) else 0)
            replies = getattr(t, "reply_count", 0) or (t.get("reply_count", 0) if isinstance(t, dict) else 0)
            quotes = getattr(t, "quote_count", 0) or (t.get("quote_count", 0) if isinstance(t, dict) else 0)
            views = getattr(t, "view_count", None) or (t.get("view_count") if isinstance(t, dict) else None)
            is_reply = int(getattr(t, "is_reply", False) or (t.get("is_reply", False) if isinstance(t, dict) else False))
            item_platform = getattr(t, "platform", None) or (t.get("platform") if isinstance(t, dict) else None) or platform

            self.db.execute(
                """
                INSERT OR IGNORE INTO tweets(
                    id, url, text, author_username, author_name, author_followers,
                    created_at, lang, like_count, retweet_count, reply_count,
                    quote_count, view_count, is_reply, scraped_at, first_run_id, platform
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (str(t_id), t_url, t_text, author_user, author_name, author_followers,
                 created_at_str, lang, likes, retweets, replies, quotes, views, is_reply, now_str, run_id, item_platform),
            )
        self.db.commit()

    def insert_x_users(self, users: list[Any]) -> None:
        """Insert a batch of XUser models or dicts directly into the x_users table."""
        now_str = _now()
        for u in users:
            rest_id = getattr(u, "rest_id", None) or (u.get("rest_id") if isinstance(u, dict) else None)
            handle = getattr(u, "handle", None) or (u.get("handle") if isinstance(u, dict) else None)
            if not rest_id or not handle:
                continue
            name = getattr(u, "name", None) or (u.get("name") if isinstance(u, dict) else None)
            bio = getattr(u, "bio", None) or (u.get("bio") if isinstance(u, dict) else None)
            followers = getattr(u, "followers_count", None) or (u.get("followers_count") if isinstance(u, dict) else None)
            following = getattr(u, "following_count", None) or (u.get("following_count") if isinstance(u, dict) else None)
            verified = int(getattr(u, "is_blue_verified", False) or (u.get("is_blue_verified", False) if isinstance(u, dict) else False))

            self.db.execute(
                """
                INSERT OR REPLACE INTO x_users(
                    rest_id, handle, name, bio, followers_count, following_count,
                    is_blue_verified, first_seen_at, last_seen_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (str(rest_id), handle, name, bio, followers, following, verified, now_str, now_str),
            )
        self.db.commit()

    def get_run(self, run_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()

    def log_activity(
        self,
        user_email: str,
        category: str,
        event_type: str,
        description: str,
        user_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        status: str = "completed",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Persist a user-specific activity event."""
        import uuid
        ev_id = f"act_{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now(timezone.utc).isoformat()
        meta_str = json.dumps(metadata or {}, default=str)
        self.db.execute(
            """
            INSERT INTO activity_events (
                id, user_id, user_email, category, event_type, description,
                resource_type, resource_id, status, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ev_id, user_id, user_email.lower().strip(), category, event_type, description,
             resource_type, resource_id, status, meta_str, now_iso)
        )
        self.db.commit()
        return ev_id

    def get_user_activity(
        self,
        user_email: str,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Retrieve chronological lifetime activity events for a specific user."""
        sql = "SELECT * FROM activity_events WHERE lower(user_email) = ?"
        params: list[Any] = [user_email.lower().strip()]
        if category and category.lower() != "all":
            sql += " AND category = ?"
            params.append(category.lower())
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = self.db.execute(sql, params).fetchall()
        out = []
        for r in rows:
            meta = {}
            try:
                meta = json.loads(r["metadata_json"] or "{}")
            except Exception:
                pass
            out.append({
                "id": r["id"],
                "userId": r["user_id"],
                "userEmail": r["user_email"],
                "category": r["category"],
                "eventType": r["event_type"],
                "description": r["description"],
                "resourceType": r["resource_type"],
                "resourceId": r["resource_id"],
                "status": r["status"],
                "metadata": meta,
                "createdAt": r["created_at"],
            })
        return out

    def log_admin_audit(
        self,
        actor: str,
        action: str,
        target_type: str,
        target_id: str | None = None,
        severity: str = "INFO",
        ip_address: str | None = None,
        user_email: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Persist system-wide admin audit log with severity and IP."""
        import uuid
        log_id = f"aud_{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now(timezone.utc).isoformat()
        meta_str = json.dumps(metadata or {}, default=str)
        self.db.execute(
            """
            INSERT INTO audit_logs (
                id, actor, action, target_type, target_id,
                severity, ip_address, user_email, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (log_id, actor, action, target_type, target_id,
             severity.upper(), ip_address or "127.0.0.1", user_email or actor, meta_str, now_iso)
        )
        self.db.commit()
        return log_id

    def get_admin_audit_logs(
        self,
        severity: str | None = None,
        search: str | None = None,
        user_email: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Retrieve system-wide audit logs with filters."""
        sql = "SELECT * FROM audit_logs WHERE 1=1"
        params: list[Any] = []
        if severity and severity.upper() != "ALL":
            sql += " AND UPPER(COALESCE(severity, 'INFO')) = ?"
            params.append(severity.upper())
        if user_email:
            sql += " AND (lower(COALESCE(user_email, '')) = ? OR lower(COALESCE(actor, '')) = ?)"
            params.extend([user_email.lower().strip(), user_email.lower().strip()])
        if search:
            sql += " AND (action LIKE ? OR target_type LIKE ? OR metadata_json LIKE ?)"
            pat = f"%{search}%"
            params.extend([pat, pat, pat])
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = self.db.execute(sql, params).fetchall()
        out = []
        for r in rows:
            meta = {}
            try:
                meta = json.loads(r["metadata_json"] or "{}")
            except Exception:
                pass
            out.append({
                "id": r["id"],
                "actor": r["actor"],
                "action": r["action"],
                "targetType": r["target_type"],
                "targetId": r["target_id"],
                "target_type": r["target_type"],
                "target_id": r["target_id"],
                "severity": r["severity"] if "severity" in r.keys() and r["severity"] else "INFO",
                "ipAddress": r["ip_address"] if "ip_address" in r.keys() and r["ip_address"] else "127.0.0.1",
                "ip_address": r["ip_address"] if "ip_address" in r.keys() and r["ip_address"] else "127.0.0.1",
                "userEmail": r["user_email"] if "user_email" in r.keys() and r["user_email"] else r["actor"],
                "user_email": r["user_email"] if "user_email" in r.keys() and r["user_email"] else r["actor"],
                "metadata": meta,
                "metadata_json": r["metadata_json"],
                "createdAt": r["created_at"],
                "created_at": r["created_at"],
                "timestamp": r["created_at"],
            })
        return out


