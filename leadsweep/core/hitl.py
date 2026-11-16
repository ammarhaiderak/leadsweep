"""Human-in-the-Loop (HITL) Guard and Execution Engine (Phase E).

Responsibilities:
- Evaluates Pre-Flight Actor Estimates against risk policies.
- Automatically places high-risk or large-volume jobs into 'hitl_pending' state.
- Dispatches approval alerts via Webhook / UI notification.
- Supports operator resume (`approve`) or cancel (`reject`).
"""
# NEW FEATURE (Phase E): HITL Guard Engine
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from leadsweep.actors.base import Actor, ActorEstimate
from leadsweep.core.datasets import DatasetEngine
from leadsweep.resilience import notify_alert

log = logging.getLogger("leadsweep.core.hitl")


@dataclass
class PolicyEvaluation:
    requires_approval: bool
    risk_level: str
    reasons: list[str]


class HITLGuard:
    def __init__(
        self,
        engine: DatasetEngine,
        webhook_url: str | None = None,
        max_auto_items: int = 100,
        risk_threshold: str = "medium",  # "medium" or "high" triggers guard
    ) -> None:
        self.engine = engine
        self.webhook_url = webhook_url
        self.max_auto_items = max_auto_items
        self.risk_threshold = risk_threshold

    def evaluate_request(self, actor: Actor, input_data: Any) -> PolicyEvaluation:
        """Pre-flight evaluation to decide whether operator consent is mandatory."""
        est: ActorEstimate = actor.estimate(input_data)
        reasons = []

        # 1. High risk actor check
        if est.risk_level == "high":
            reasons.append("Actor risk level is categorized as HIGH (aggressive scraping hazard)")
        elif est.risk_level == "medium" and self.risk_threshold == "medium":
            reasons.append("Actor risk level is MEDIUM requiring supervisor confirmation")

        # 2. Large volume item request check
        if est.estimated_items > self.max_auto_items:
            reasons.append(f"Requested items ({est.estimated_items}) exceed safety ceiling ({self.max_auto_items})")

        requires_approval = len(reasons) > 0
        return PolicyEvaluation(
            requires_approval=requires_approval,
            risk_level=est.risk_level,
            reasons=reasons,
        )

    def trigger_guard(self, run_id: str, actor_name: str, reasons: list[str], input_data: dict[str, Any]) -> None:
        """Update run to hitl_pending and dispatch webhook alert."""
        reason_str = " | ".join(reasons)
        self.engine.update_run_status(run_id, status="hitl_pending", error_detail=reason_str)
        log.warning("HITL GUARD TRIGGERED for run %s (%s): %s", run_id, actor_name, reason_str)

        notify_alert(
            self.webhook_url,
            "HITL_APPROVAL_REQUIRED",
            f"Run {run_id} ({actor_name}) paused pending human authorization: {reason_str}",
            {"run_id": run_id, "actor": actor_name, "reasons": reasons, "input": input_data},
        )

    def approve_run(self, run_id: str, operator: str = "admin") -> dict[str, Any]:
        """Human approval granted; unlock run back to 'running'."""
        run = self.engine.get_run(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")
        if run["status"] != "hitl_pending":
            raise ValueError(f"Run {run_id} is in status '{run['status']}', expected 'hitl_pending'")

        self.engine.update_run_status(run_id, status="running", error_detail=f"Approved by {operator}")
        log.info("HITL run %s APPROVED by %s", run_id, operator)
        return {"run_id": run_id, "status": "running", "approved_by": operator}

    def reject_run(self, run_id: str, operator: str = "admin", reason: str = "Rejected by user") -> dict[str, Any]:
        """Human rejection; mark run aborted."""
        run = self.engine.get_run(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")
        if run["status"] != "hitl_pending":
            raise ValueError(f"Run {run_id} is in status '{run['status']}', expected 'hitl_pending'")

        self.engine.finish_run(run_id, status="aborted", error_detail=f"Rejected by {operator}: {reason}")
        log.info("HITL run %s REJECTED by %s", run_id, operator)
        return {"run_id": run_id, "status": "aborted", "rejected_by": operator, "reason": reason}
