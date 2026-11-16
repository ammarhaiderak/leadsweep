"""Reddit lead-generation integration (zero-credential, zero-cost by design).

Public surface:
    RedditNativeAdapter    - platform adapter used by the existing SearchActor
    RedditIngestionService - plan/fetch/normalize/report orchestration
    load_access_config     - credential-free access configuration
    build_plan             - deterministic discovery planning
"""
from __future__ import annotations

from .adapter import RedditNativeAdapter
from .authentication import (
    DISABLED,
    OFFLINE_FIXTURES,
    PUBLIC_UNAUTHENTICATED,
    RedditAccessConfig,
    load_access_config,
)
from .discovery import RedditDiscoveryPlan, build_plan
from .models import RedditComment, RedditExecutionSummary, RedditPost
from .service import RedditIngestionService

__all__ = [
    "RedditNativeAdapter",
    "RedditIngestionService",
    "RedditAccessConfig",
    "RedditDiscoveryPlan",
    "RedditPost",
    "RedditComment",
    "RedditExecutionSummary",
    "load_access_config",
    "build_plan",
    "PUBLIC_UNAUTHENTICATED",
    "OFFLINE_FIXTURES",
    "DISABLED",
]
