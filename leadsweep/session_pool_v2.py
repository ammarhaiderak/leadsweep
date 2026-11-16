"""Deprecated location for the Phase D "Session Pool V2" anti-ban engine.

PHASE 6 - resolution of a long-standing naming ambiguity
-------------------------------------------------------
This module previously contained a second, near-identical implementation called
``SessionPoolV2``. It was never imported by anything: the scraper, the resilience engine,
every script and both test modules all import from :mod:`leadsweep.session_pool`, whose class
docstring has described itself as "Session Pool V2" since Phase D. In other words the *live*
class was always ``SessionPool``; only this file's name suggested otherwise, and its
``SessionPoolV2`` class was ~95% duplicated logic that could silently drift.

Rather than delete the module outright (which would break any external import of the name),
this file now re-exports the canonical implementation. Both spellings resolve to the same
class, so there is exactly one behaviour to reason about.

New code should import from :mod:`leadsweep.session_pool`.
"""
from __future__ import annotations

from .session_pool import SessionCreds, SessionMetrics, SessionPool

# Backwards-compatible alias. Deliberately the SAME class object, not a subclass: a subclass
# here would reintroduce the drift this module exists to eliminate.
SessionPoolV2 = SessionPool

__all__ = ["SessionCreds", "SessionMetrics", "SessionPool", "SessionPoolV2"]

# Surfaced by scripts.doctor / tooling so the deprecation is visible rather than silent.
DEPRECATION_NOTICE = (
    "leadsweep.session_pool_v2 is a deprecated alias. Import SessionPool from leadsweep.session_pool."
)