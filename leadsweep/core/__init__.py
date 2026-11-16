"""Core package initialization.

Exports the engine primitives that are stable public API.

The autonomous agent deliberately does NOT live here. It is served from
``leadsweep.services.agent.HITLAutonomousAgent``, which is the single implementation that
actually executes actor runs. The earlier ``leadsweep.core.agent.AutonomousAgent`` prototype
planned tasks but never executed them, and having two agent classes in production code was
a correctness hazard (the CLI called a method that did not exist on it).
"""
# NEW FEATURE (Phase B, E, G): Core engine export
from __future__ import annotations

from leadsweep.core.datasets import DatasetEngine
from leadsweep.core.exporter import DatasetExporter
from leadsweep.core.hitl import HITLGuard, PolicyEvaluation

__all__ = ["DatasetEngine", "DatasetExporter", "HITLGuard", "PolicyEvaluation"]