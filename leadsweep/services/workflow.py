"""Unified Workflow Service for Leads and Users (status triage, notes, tags)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from leadsweep.config import Settings, get_settings
from leadsweep.pipeline.store import Store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


VALID_STATUSES = ("new", "reviewing", "contacted", "replied", "won", "lost", "ignored")


class WorkflowService:
    def __init__(self, store: Store | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.store = store or Store(self.settings.db_path)

    def get_status(self, entity_id: str, entity_type: str = "tweet") -> dict[str, Any]:
        row = self.store.db.execute(
            "SELECT * FROM lead_workflow WHERE entity_id = ? AND entity_type = ?",
            (entity_id, entity_type),
        ).fetchone()
        if row:
            data = dict(row)
            data["tags"] = json.loads(data["tags"]) if data.get("tags") else []
            return data
        return {
            "entity_id": entity_id,
            "entity_type": entity_type,
            "status": "new",
            "owner": None,
            "tags": [],
            "notes": None,
            "updated_at": _now(),
        }

    def update_status(
        self,
        entity_id: str,
        entity_type: str,
        status: str,
        owner: str | None = None,
        tags: list[str] | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}. Allowed: {VALID_STATUSES}")
        if entity_type not in ("tweet", "user"):
            raise ValueError("entity_type must be 'tweet' or 'user'")

        now = _now()
        tags_json = json.dumps(tags or []) if tags is not None else None

        current = self.store.db.execute(
            "SELECT * FROM lead_workflow WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()

        if current:
            final_owner = owner if owner is not None else current["owner"]
            final_tags = tags_json if tags_json is not None else current["tags"]
            final_notes = notes if notes is not None else current["notes"]
            self.store.db.execute(
                """
                UPDATE lead_workflow
                SET status = ?, owner = ?, tags = ?, notes = ?, updated_at = ?
                WHERE entity_id = ?
                """,
                (status, final_owner, final_tags, final_notes, now, entity_id),
            )
        else:
            self.store.db.execute(
                """
                INSERT INTO lead_workflow (entity_id, entity_type, status, owner, tags, notes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (entity_id, entity_type, status, owner, tags_json, notes, now),
            )
        self.store.db.commit()
        return self.get_status(entity_id, entity_type)

    def list_workflow(self, entity_type: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM lead_workflow"
        clauses = []
        args: list[Any] = []
        if entity_type:
            clauses.append("entity_type = ?")
            args.append(entity_type)
        if status:
            clauses.append("status = ?")
            args.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC"
        rows = self.store.db.execute(sql, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
            out.append(d)
        return out
