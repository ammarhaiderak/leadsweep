# NEW FEATURE: Lead Intelligence Retrieval Engine (WS1)
"""
retrieval.py -- Core Retrieval Engine for Lead Intelligence
- Query planner (LLM + deterministic fallback)
- Query linter with repair loop
- Time-window slicing (today-first, 24h/72h/7d)
- Local FTS5 candidate reuse
- Scatter-gather scatter execution with provenance tracking
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from leadsweep.leadintel.lead_quick import (
    DEFAULT_NEGATIVES,
    MAX_OR_TERMS,
    MAX_QUERY_LEN,
    QueryPlan,
    QueryVariant,
    lint_query,
    plan_queries,
)

log = logging.getLogger("leadsweep.leadintel.retrieval")


class TimeWindowSlice(BaseModel):
    name: str  # e.g., "24h", "72h", "7d", "14d"
    since_date: str  # YYYY-MM-DD
    until_date: Optional[str] = None  # YYYY-MM-DD
    window_days: int


class RetrievalTask(BaseModel):
    task_id: str
    variant_id: str
    strategy: str
    query_string: str
    window: TimeWindowSlice
    probe_cap: int = 25


def generate_time_windows(max_window_days: int = 7, strict_today: bool = False, now: Optional[datetime] = None) -> List[TimeWindowSlice]:
    """Generates reverse-chronological time window slices."""
    now = now or datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    windows = [
        TimeWindowSlice(name="24h", since_date=yesterday_str, until_date=today_str, window_days=1)
    ]
    if strict_today:
        return windows

    if max_window_days >= 3:
        d3_str = (now - timedelta(days=3)).strftime("%Y-%m-%d")
        windows.append(TimeWindowSlice(name="72h", since_date=d3_str, until_date=yesterday_str, window_days=3))
    if max_window_days >= 7:
        d7_str = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        windows.append(TimeWindowSlice(name="7d", since_date=d7_str, until_date=(now - timedelta(days=3)).strftime("%Y-%m-%d"), window_days=7))

    return windows


def apply_window_to_query(query: str, window: TimeWindowSlice) -> str:
    """Appends X search since: and until: operators cleanly to query string."""
    q = query.strip()
    if f"since:{window.since_date}" not in q:
        q += f" since:{window.since_date}"
    if window.until_date and f"until:{window.until_date}" not in q:
        q += f" until:{window.until_date}"
    return q


class CascadeRetrievalResult(BaseModel):
    items: List[Dict[str, Any]]
    total_found: int
    requested_n: int
    short_by: int
    noise_suppressed: int
    tier1_local_count: int
    tier2_live_count: int
    qualified_count: int
    early_exit: bool
    status: str


class RetrievalEngine:
    """Manages the full X-style retrieval lifecycle (WS1 + Search-Mixer + Earlybird Cascade)."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    def build_query_portfolio(
        self,
        user_query: str,
        offer: str = "",
        llm: Any = None,
        max_window_days: int = 7,
        strict_today: bool = False,
    ) -> Tuple[QueryPlan, List[RetrievalTask]]:
        """Plans variants, lints syntax, and produces sliced retrieval tasks."""
        plan, lint_report = plan_queries(user_query, offer=offer, llm=llm)
        windows = generate_time_windows(max_window_days=max_window_days, strict_today=strict_today)

        tasks: List[RetrievalTask] = []
        for i, v in enumerate(plan.variants):
            for w in windows:
                sliced_q = apply_window_to_query(v.query, w)
                tasks.append(
                    RetrievalTask(
                        task_id=f"var_{i+1}_{w.name}",
                        variant_id=f"var_{i+1}",
                        strategy=v.strategy,
                        query_string=sliced_q,
                        window=w,
                        probe_cap=25,
                    )
                )

        return plan, tasks

    def query_local_fts5_candidates(self, query: str, limit: int = 50, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Tier 1 Earlybird Core: Queries local FTS5 index sorted in strict reverse-chronological order, excluding seen leads."""
        if not self.db_path or not self.db_path.exists():
            return []
        try:
            import sqlite3
            from leadsweep.leadintel.db import normalize_query_text

            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            words = [w for w in query.replace('"', '').replace("'", "").split() if len(w) > 2 and not w.startswith('-')][:5]
            if not words:
                conn.close()
                return []

            norm_q = normalize_query_text(query)
            seen_filter_sql = ""
            seen_params: list[Any] = []
            if user_id:
                seen_filter_sql = "AND c.id NOT IN (SELECT tweet_id FROM li_user_seen_leads WHERE user_id = ? AND query_text = ?)"
                seen_params = [str(user_id).strip(), norm_q]

            # Try native SQLite FTS5 MATCH query first
            rows = []
            try:
                # Sanitized match terms for FTS5
                clean_fts = " OR ".join([f'"{w}"' for w in words])
                fts_sql = f"""
                    SELECT c.id, c.text, c.author_username, c.author_name, c.author_bio,
                           c.author_followers, c.likes, c.replies, c.posted_at
                    FROM li_candidates c
                    JOIN li_candidates_fts fts ON fts.rowid = c.rowid
                    WHERE li_candidates_fts MATCH ? {seen_filter_sql}
                    ORDER BY c.posted_at DESC LIMIT ?
                """
                rows = cursor.execute(fts_sql, [clean_fts] + seen_params + [limit]).fetchall()
            except Exception as fts_err:
                log.debug("Direct FTS5 MATCH query fallback to LIKE: %s", fts_err)

            if not rows:
                pattern = f"%{words[0]}%"
                like_sql = f"""
                    SELECT c.id, c.text, c.author_username, c.author_name, c.author_bio,
                           c.author_followers, c.likes, c.replies, c.posted_at
                    FROM li_candidates c
                    WHERE c.text LIKE ? {seen_filter_sql}
                    ORDER BY c.posted_at DESC LIMIT ?
                """
                rows = cursor.execute(like_sql, [pattern] + seen_params + [limit]).fetchall()

            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            log.warning("Local candidate cache lookup skipped: %s", e)
            return []

    def judge_candidate_pool(
        self,
        candidates: List[Dict[str, Any]],
        brief: Optional[Any] = None,
        query: str = "",
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Tier 3 Judge Funnel Contract (Section 3B):
        - Evaluates candidates against direction heuristics & score v2.
        - Suppresses low-relevance junk (Spam/Job Seekers score <= 25).
        - Sorts matches by: Quality/Score (Dominates) -> Freshness (Breaks Ties).
        - Returns (qualified_list, noise_suppressed_count).
        """
        from leadsweep.leadintel.judge import judge_candidate
        from leadsweep.leadintel.db import record_rejected_tweet_ids, is_tweet_rejected_or_known, get_connection

        DISALLOWED_CLASSES = {
            "PROMOTIONAL_OR_TASK_UPDATE",
            "IRRELEVANT",
            "GENERAL_DISCUSSION",
            "JOB_SEEKER",
            "PROMO",
            "SERVICE_PROVIDER_PROMO",
            "INFO_OR_THOUGHT_CONTENT",
            "AIRDROP_BOT_SPAM",
        }

        qualified: List[Dict[str, Any]] = []
        noise_suppressed = 0
        dropped_ids: List[str] = []

        with get_connection() as conn:
            for c in candidates:
                cid = str(c.get("id") or c.get("tweet_id") or "")
                
                # Fast dedupe skip: if already rejected or known candidate, skip compute
                if cid and is_tweet_rejected_or_known(conn, cid):
                    # Check if already a known candidate in DB
                    existing_cand = conn.execute("SELECT 1 FROM li_candidates WHERE id = ?", (cid,)).fetchone()
                    if not existing_cand:
                        noise_suppressed += 1
                        continue

                text = c.get("text", "")
                bio = c.get("author_bio", "") or c.get("author", {}).get("description", "")
                followers = int(c.get("author_followers", 0) or c.get("author", {}).get("followers_count", 0) or 0)
                score_res = judge_candidate(
                    post_text=text,
                    author_bio=bio,
                    author_followers=followers,
                    topic_rel_score=int(float(c.get("rule_score", 70.0))),
                    brief=brief,
                    conn=conn,
                )

                c_augmented = dict(c)
                c_augmented["score"] = score_res.final_score
                c_augmented["direction"] = score_res.direction.value
                c_augmented["quote_verified"] = score_res.quote_verified
                c_augmented["evidence_quote"] = score_res.evidence_quote
                c_augmented["why_text"] = score_res.why_text

                # Strict Quality Gate: Score > 50 only & drop disallowed classifications
                direction_val = str(score_res.direction.value).upper()
                if score_res.final_score <= 50 or direction_val in DISALLOWED_CLASSES:
                    noise_suppressed += 1
                    if cid:
                        dropped_ids.append(cid)
                else:
                    qualified.append(c_augmented)
                    # Persist only qualified leads into li_candidates
                    if cid:
                        try:
                            conn.execute(
                                """
                                INSERT OR IGNORE INTO li_candidates 
                                (id, text, author_username, author_name, author_bio, author_followers, likes, replies, posted_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    cid,
                                    text,
                                    c.get("author_username") or (c.get("author") or {}).get("screen_name") or "",
                                    c.get("author_name") or (c.get("author") or {}).get("name") or "",
                                    bio,
                                    followers,
                                    int(c.get("likes") or c.get("favorite_count") or 0),
                                    int(c.get("replies") or c.get("reply_count") or 0),
                                    c.get("posted_at") or c.get("created_at"),
                                ),
                            )
                        except Exception as ins_err:
                            log.debug("Candidate persistence notice: %s", ins_err)

            if dropped_ids:
                record_rejected_tweet_ids(conn, dropped_ids)

        # Sort: Quality/Score (Dominates) -> Freshness / posted_at (Breaks Ties)
        def _sort_key(item: Dict[str, Any]) -> Tuple[int, str]:
            sc = int(item.get("score", 0))
            dt = str(item.get("posted_at") or item.get("created_at") or "")
            return (sc, dt)

        qualified.sort(key=_sort_key, reverse=True)
        return qualified, noise_suppressed

    async def execute_cascading_retrieval(
        self,
        query: str,
        n_limit: int = 10,
        offer: str = "",
        live_fetcher: Optional[Callable[[str, int], Any]] = None,
        brief: Optional[Any] = None,
        llm: Any = None,
        user_id: Optional[str] = None,
    ) -> CascadeRetrievalResult:
        """X Search-Mixer + Earlybird Cascading Engine:
        Handles sliding Top-N limits (N = 10, 100, 1000) dynamically without junk padding:
        1. Tier 1 (Earlybird Core): Query local FTS5 candidates in strict reverse-chronological order.
           Excludes seen leads for this user_id and query.
           If local high-quality records >= N, terminate early and return immediately.
        2. Tier 2 (Scatter-Gather Live Discovery): If local search yields fewer than N items,
           compute shortfall = N - local_count. Distribute search operators targeting shortfall
           across sliding time windows (24h -> 72h -> 7d).
        3. Tier 3 (Strict Top-N Judge Funnel): Pass all fresh candidates through Judge Funnel.
           Sort by Quality/Score (Dominates) -> Freshness (Breaks Ties).
           DO NOT pad with low-relevance junk (score <= 50).
           Accurately return qualified rows with short_by and noise_suppressed counts.
        """
        # --- Tier 1: Earlybird Core (Local In-Memory / FTS) ---
        local_raw = self.query_local_fts5_candidates(query, limit=max(n_limit * 2, 50), user_id=user_id)
        local_qualified, local_noise = self.judge_candidate_pool(local_raw, brief=brief, query=query)

        tier1_count = len(local_qualified)
        if tier1_count >= n_limit:
            # Terminate early instantly
            final_items = local_qualified[:n_limit]
            return CascadeRetrievalResult(
                items=final_items,
                total_found=tier1_count,
                requested_n=n_limit,
                short_by=0,
                noise_suppressed=local_noise,
                tier1_local_count=tier1_count,
                tier2_live_count=0,
                qualified_count=len(final_items),
                early_exit=True,
                status="tier1_early_exit_satisfied",
            )

        # --- Tier 2: Real-time Live Discovery with Dynamic Target Backfill ---
        # Shortfall Calculator: Count ONLY leads that pass strict quality funnel gate.
        # Evaluate formula: (current_qualified_count < target_N).
        # Continue executing search and scrolls until shortfall is resolved or safety cap is exhausted.
        active_qualified: List[Dict[str, Any]] = list(local_qualified)
        active_noise: int = local_noise
        live_raw_collected: int = 0
        total_scroll_iterations: int = 0
        seen_cand_ids: set[str] = {
            str(c.get("id") or c.get("tweet_id") or c.get("text", "")[:40])
            for c in local_raw
        }

        # Safety caps: Max 60 scrolls / 600 raw posts
        MAX_SAFETY_SCROLLS = 60
        MAX_RAW_POSTS_CAP = 600

        if live_fetcher and len(active_qualified) < n_limit:
            # 1. Mandatory Session Gatekeeping: Check account connection before live scraping
            from leadsweep.leadintel.session import enforce_account_connected
            enforce_account_connected(user_id or "admin")

            windows = generate_time_windows(max_window_days=7, strict_today=False)
            plan, _ = self.build_query_portfolio(query, offer=offer, llm=llm)

            import random

            # Outer backfill loop: continue until current_qualified_count >= n_limit
            # or safety caps are exhausted.
            for win in windows:
                if len(active_qualified) >= n_limit or total_scroll_iterations >= MAX_SAFETY_SCROLLS or live_raw_collected >= MAX_RAW_POSTS_CAP:
                    break

                for variant in plan.variants:
                    if len(active_qualified) >= n_limit or total_scroll_iterations >= MAX_SAFETY_SCROLLS or live_raw_collected >= MAX_RAW_POSTS_CAP:
                        break

                    scoped_q = apply_window_to_query(variant.query, win)

                    # Dynamic probe loop for this query variant
                    consecutive_empty_probes = 0
                    while (
                        len(active_qualified) < n_limit
                        and total_scroll_iterations < MAX_SAFETY_SCROLLS
                        and live_raw_collected < MAX_RAW_POSTS_CAP
                    ):
                        remaining_needed = n_limit - len(active_qualified)
                        # Fetch in adaptive batches (e.g. 25-50 raw items) to resolve shortfall
                        fetch_batch_size = max(25, min(remaining_needed * 3, 50))
                        
                        try:
                            batch = live_fetcher(scoped_q, fetch_batch_size)
                            if asyncio.iscoroutine(batch):
                                batch = await batch
                        except Exception as err:
                            log.warning("Scatter-gather probe error for query '%s': %s", scoped_q, err)
                            break

                        total_scroll_iterations += 1

                        if not batch or not isinstance(batch, list):
                            consecutive_empty_probes += 1
                            if consecutive_empty_probes >= 2:
                                break
                            continue

                        consecutive_empty_probes = 0
                        live_raw_collected += len(batch)

                        # Filter out already seen candidates
                        new_batch: List[Dict[str, Any]] = []
                        for item in batch:
                            cid = str(item.get("id") or item.get("tweet_id") or item.get("text", "")[:40])
                            if cid not in seen_cand_ids:
                                seen_cand_ids.add(cid)
                                new_batch.append(item)

                        if not new_batch:
                            # No new unique items in this scroll iteration; slide to next variant
                            break

                        # Evaluate through Tier 3 Quality Funnel gate immediately
                        fresh_qualified, suppressed_count = self.judge_candidate_pool(new_batch, brief=brief, query=query)
                        active_noise += suppressed_count

                        for q_lead in fresh_qualified:
                            active_qualified.append(q_lead)
                            if len(active_qualified) >= n_limit:
                                break

                        log.info(
                            "[Backfill scroll %d/%d] query='%s' raw=+%d, qualified_so_far=%d/%d, suppressed=%d",
                            total_scroll_iterations,
                            MAX_SAFETY_SCROLLS,
                            scoped_q[:40],
                            len(new_batch),
                            len(active_qualified),
                            n_limit,
                            suppressed_count,
                        )

                        # Check termination condition: target fulfilled
                        if len(active_qualified) >= n_limit:
                            break

                        # Random non-linear pacing delay (3.0 - 6.5s) between backfill scrolls
                        # to protect the connected account from rate-limiting flags.
                        await asyncio.sleep(random.uniform(3.0, 6.5))
                        if total_scroll_iterations % random.randint(5, 8) == 0:
                            await asyncio.sleep(random.uniform(4.0, 8.0))

        # --- Tier 3: Strict Top-N Final Ordering (Quality Dominates -> Freshness Breaks Ties) ---
        def _sort_key(item: Dict[str, Any]) -> Tuple[int, str]:
            sc = int(item.get("score", 0))
            dt = str(item.get("posted_at") or item.get("created_at") or "")
            return (sc, dt)

        active_qualified.sort(key=_sort_key, reverse=True)

        final_leads = active_qualified[:n_limit]
        actual_qualified_count = len(final_leads)
        remaining_shortfall = max(0, n_limit - actual_qualified_count)

        return CascadeRetrievalResult(
            items=final_leads,
            total_found=len(active_qualified),
            requested_n=n_limit,
            short_by=remaining_shortfall,
            noise_suppressed=active_noise,
            tier1_local_count=tier1_count,
            tier2_live_count=live_raw_collected,
            qualified_count=actual_qualified_count,
            early_exit=False,
            status="cascade_completed",
        )

