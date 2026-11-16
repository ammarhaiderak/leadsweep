# NEW FEATURE: Lead Intelligence Additive Database Migrations
"""
Initializes isolated additive SQLite tables for Lead Intelligence Engine (prefixed with li_).
Zero changes to existing tables.
"""
import os
import sqlite3
import logging
from contextlib import contextmanager
from typing import Any, Dict

log = logging.getLogger("leadsweep.leadintel.db")


def get_db_path() -> str:
    return os.environ.get("LEADSWEEP_DB_PATH", "data/leadsweep.db")


@contextmanager
def get_connection():
    path = get_db_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        init_leadintel_tables(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_leadintel_tables(conn: sqlite3.Connection) -> None:
    """Create all li_ prefixed tables if they do not exist."""
    cursor = conn.cursor()
    
    # 1. User Sales Profile: What the user sells
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS li_profile (
            user_id TEXT PRIMARY KEY,
            offer TEXT NOT NULL,
            offer_type TEXT DEFAULT 'services',
            icp_roles TEXT,
            icp_domains TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 2. Brief Cache: LeadBriefs compiled for queries
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS li_brief_cache (
            brief_id TEXT PRIMARY KEY,
            raw_query TEXT NOT NULL,
            brief_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 3. Query Variant Stats: Performance tracking across runs
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS li_variant_stats (
            query_string TEXT PRIMARY KEY,
            strategy TEXT NOT NULL,
            probe_count INTEGER DEFAULT 0,
            buyer_count INTEGER DEFAULT 0,
            precision_rate REAL DEFAULT 0.0,
            cost_requests INTEGER DEFAULT 0,
            cost_tokens INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 4. Learned Negatives: Words learned from user rejections
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS li_negatives (
            term TEXT PRIMARY KEY,
            reject_count INTEGER DEFAULT 1,
            approve_count INTEGER DEFAULT 0,
            is_safe INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 5. Feedback Store: User approve / reject feedback on leads
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS li_feedback (
            id TEXT PRIMARY KEY,
            tweet_id TEXT NOT NULL,
            label TEXT NOT NULL, -- 'approve' | 'reject'
            direction TEXT,
            features_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 6. Model Calibration Weights: Versioned logistic regression weights
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS li_models (
            version TEXT PRIMARY KEY,
            weights_json TEXT NOT NULL,
            samples_count INTEGER DEFAULT 0,
            calibrated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 7. Local Tracing: LangChain execution logs without paid LangSmith
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS li_trace (
            id TEXT PRIMARY KEY,
            run_id TEXT,
            node_name TEXT NOT NULL,
            model_used TEXT NOT NULL,
            tokens_used INTEGER DEFAULT 0,
            latency_ms REAL DEFAULT 0.0,
            cache_hit INTEGER DEFAULT 0,
            fallback_used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 8. Hash Cache: Classification cache (model + prompt_v + hash of text)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS li_classification_cache (
            content_hash TEXT PRIMARY KEY,
            model_version TEXT NOT NULL,
            result_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 9. Candidates store (realtime tier + historical archive)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS li_candidates (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            author_username TEXT,
            author_name TEXT,
            author_bio TEXT,
            author_followers INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            replies INTEGER DEFAULT 0,
            posted_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_li_cand_posted ON li_candidates(posted_at DESC);")

    # 10. FTS5 full text search table over candidates
    try:
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS li_candidates_fts USING fts5(
                id UNINDEXED,
                text,
                author_username,
                content='li_candidates',
                content_rowid='rowid'
            );
        """)
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_li_candidates_ai AFTER INSERT ON li_candidates BEGIN
                INSERT INTO li_candidates_fts(rowid, id, text, author_username)
                VALUES (new.rowid, new.id, new.text, new.author_username);
            END;
        """)
    except Exception as e:
        log.warning("FTS5 table creation fallback: %s", e)

    # 11. Judgments and Job rankings
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS li_judgments (
            id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL,
            direction TEXT NOT NULL,
            score INTEGER NOT NULL,
            evidence_quote TEXT,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS li_job_rank (
            job_id TEXT NOT NULL,
            candidate_id TEXT NOT NULL,
            final_rank REAL NOT NULL,
            score INTEGER NOT NULL,
            PRIMARY KEY (job_id, candidate_id)
        );
    """)

    # 12. Rejected noise tracking: avoid re-judging the same dropped posts
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS li_rejected_ids (
            tweet_id TEXT PRIMARY KEY,
            rejected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 13. Seen-state tracker: avoid returning previously viewed leads to the same user
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS li_user_seen_leads (
            user_id TEXT,
            query_text TEXT,
            tweet_id TEXT,
            seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, query_text, tweet_id)
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_li_seen_lookup ON li_user_seen_leads(user_id, query_text);")

    conn.commit()
    log.info("Lead Intelligence database tables initialized.")


def normalize_query_text(q: str) -> str:
    """Normalize query text for consistent seen-state tracking (lowercase, trim, collapse spaces)."""
    return " ".join((q or "").strip().lower().split())


def is_tweet_rejected_or_known(conn: sqlite3.Connection, tweet_id: str) -> bool:
    """Check if tweet_id is already in li_rejected_ids or li_candidates."""
    tid = str(tweet_id).strip()
    if not tid:
        return False
    row = conn.execute(
        "SELECT 1 FROM li_rejected_ids WHERE tweet_id = ? UNION SELECT 1 FROM li_candidates WHERE id = ?",
        (tid, tid),
    ).fetchone()
    return bool(row)


def record_rejected_tweet_ids(conn: sqlite3.Connection, tweet_ids: list[str]) -> int:
    """Record dropped tweet IDs into li_rejected_ids."""
    added = 0
    for tid in tweet_ids:
        clean = str(tid).strip()
        if clean:
            try:
                conn.execute("INSERT OR IGNORE INTO li_rejected_ids (tweet_id) VALUES (?)", (clean,))
                added += 1
            except Exception:
                pass
    return added


def mark_user_seen_leads(conn: sqlite3.Connection, user_id: str, query_text: str, tweet_ids: list[str]) -> int:
    """Record batch of displayed leads into li_user_seen_leads for user_id and query_text."""
    norm_q = normalize_query_text(query_text)
    uid = str(user_id).strip()
    count = 0
    for tid in tweet_ids:
        clean_tid = str(tid).strip()
        if clean_tid:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO li_user_seen_leads (user_id, query_text, tweet_id) VALUES (?, ?, ?)",
                    (uid, norm_q, clean_tid),
                )
                count += 1
            except Exception:
                pass
    return count



def purge_and_rebuild_leadintel_db(conn: sqlite3.Connection) -> dict[str, Any]:
    """Purge candidate FTS5, classification cache, and operational state tables.
    
    Drops operational state indices before rebuilding, truncates classification cache,
    re-indexes FTS5 virtual table, and enforces ANALYZE and VACUUM in WAL mode to guarantee
    zero ghost reads.
    """
    cursor = conn.cursor()
    purged_counts: dict[str, int] = {}

    # 1. Truncate classification cache and candidate tables
    target_tables = [
        "li_classification_cache",
        "li_candidates",
        "li_judgments",
        "li_job_rank",
        "li_trace",
    ]
    for tbl in target_tables:
        try:
            cnt_row = cursor.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()
            purged_counts[tbl] = cnt_row[0] if cnt_row else 0
            cursor.execute(f"DELETE FROM {tbl};")
        except Exception as e:
            log.warning("Table %s purge notice: %s", tbl, e)
            purged_counts[tbl] = 0

    # 2. Clear & rebuild FTS5 virtual table
    try:
        cursor.execute("DROP TABLE IF EXISTS li_candidates_fts;")
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS li_candidates_fts USING fts5(
                id UNINDEXED,
                text,
                author_username,
                content='li_candidates',
                content_rowid='rowid'
            );
        """)
        purged_counts["li_candidates_fts"] = 1
    except Exception as e:
        log.warning("FTS5 rebuild notice: %s", e)

    # 3. Drop and recreate operational state indices
    try:
        cursor.execute("DROP INDEX IF EXISTS idx_li_cand_posted;")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_li_cand_posted ON li_candidates(posted_at DESC);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_li_judg_cand ON li_judgments(candidate_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_li_rank_job ON li_job_rank(job_id);")
    except Exception as e:
        log.warning("Index recreation notice: %s", e)

    conn.commit()

    # 4. Enforce WAL mode, ANALYZE, and VACUUM to eliminate ghost reads
    try:
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        cursor.execute("ANALYZE;")
        cursor.execute("VACUUM;")
        conn.commit()
    except Exception as e:
        log.warning("WAL optimize notice: %s", e)

    log.info("Lead Intelligence purge & vacuum complete: %s", purged_counts)
    return purged_counts


