"""Lead Quality & Feedback Service: Stores good/bad annotations, computes precision/recall, and maintains regression suites."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from leadsweep.config import Settings, get_settings
from leadsweep.pipeline.store import Store

log = logging.getLogger("leadsweep.services.quality")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class QualityService:
    def __init__(self, store: Store | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.store = store or Store(self.settings.db_path)

    def record_feedback(
        self,
        entity_id: str,
        entity_type: str,
        label: str,
        reason_code: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Record human good/bad feedback on a tweet lead or user profile."""
        if label not in ("good", "bad"):
            raise ValueError("label must be 'good' or 'bad'")
        if entity_type not in ("tweet", "user"):
            raise ValueError("entity_type must be 'tweet' or 'user'")

        feedback_id = f"fb_{uuid.uuid4().hex[:12]}"
        now = _now()
        self.store.db.execute(
            """
            INSERT INTO feedback (id, entity_id, entity_type, label, reason_code, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (feedback_id, entity_id, entity_type, label, reason_code, note, now),
        )
        self.store.db.commit()
        return {
            "id": feedback_id,
            "entity_id": entity_id,
            "entity_type": entity_type,
            "label": label,
            "reason_code": reason_code,
            "note": note,
            "created_at": now,
        }

    def list_feedback(self, entity_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = "SELECT * FROM feedback"
        args: list[Any] = []
        if entity_type:
            sql += " WHERE entity_type = ?"
            args.append(entity_type)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.store.db.execute(sql, args).fetchall()]

    def evaluate_precision_at_k(self, k: int = 10, min_score: int = 70) -> dict[str, Any]:
        """Compute Precision@K over human feedback.

        ``min_score`` is now genuinely applied (PHASE 7): only items whose stored score meets
        the threshold are considered, ranked by score, and the top ``k`` of those are
        evaluated. Previously the parameter was accepted and ignored, so ``xs eval
        --min-score`` was a silent no-op and the reported precision covered every labeled
        row regardless of quality.
        """
        tweet_feedback = self.store.db.execute(
            """
            SELECT s.score, f.label
            FROM feedback f
            JOIN scores s ON s.tweet_id = f.entity_id
            WHERE f.entity_type = 'tweet' AND s.score >= ?
            ORDER BY s.score DESC
            LIMIT ?
            """,
            (min_score, k),
        ).fetchall()

        user_feedback = self.store.db.execute(
            """
            SELECT us.icp_score as score, f.label
            FROM feedback f
            JOIN user_scores us ON us.user_id = f.entity_id
            WHERE f.entity_type = 'user' AND us.icp_score >= ?
            ORDER BY us.icp_score DESC
            LIMIT ?
            """,
            (min_score, k),
        ).fetchall()

        def compute_metrics(rows: list[Any]) -> dict[str, Any]:
            if not rows:
                return {"count": 0, "precision": 0.0, "false_positives": 0, "good": 0, "bad": 0}
            good = sum(1 for r in rows if r["label"] == "good")
            bad = sum(1 for r in rows if r["label"] == "bad")
            total = len(rows)
            precision = round((good / total) * 100, 1) if total > 0 else 0.0
            return {
                "count": total,
                "precision": precision,
                "false_positives": bad,
                "good": good,
                "bad": bad,
            }

        return {
            "k": k,
            "min_score": min_score,
            "tweets": compute_metrics(tweet_feedback),
            "users": compute_metrics(user_feedback),
            "evaluated_at": _now(),
        }
