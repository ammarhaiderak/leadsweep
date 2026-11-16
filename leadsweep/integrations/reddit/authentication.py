"""Access configuration for Reddit ingestion.

Design decisions that matter
----------------------------
* No personal Reddit account, OAuth client, token, cookie or browser session is ever required
  or accepted by this module. There is deliberately no credential field to fill in.
* Reddit's current Data API policy requires OAuth plus prior approval and blocks unauthenticated
  traffic (verified: HTTP 403 on ``www.reddit.com/*.json``). A feature that needs an account is
  therefore reported as unavailable rather than worked around.
* Two compliant modes remain at $0:
    - ``public_unauthenticated``: attempt permitted public JSON endpoints and report
      ``ACCESS_RESTRICTED`` honestly when Reddit refuses them.
    - ``offline_fixtures``: read locally supplied Reddit JSON (your own permitted exports) so the
      full discovery → qualification → export pipeline runs with no network and no credentials.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

PUBLIC_UNAUTHENTICATED = "public_unauthenticated"
OFFLINE_FIXTURES = "offline_fixtures"
DISABLED = "disabled"

VALID_ACCESS_MODES = (PUBLIC_UNAUTHENTICATED, OFFLINE_FIXTURES, DISABLED)

PROVIDER_ARCTIC_SHIFT = "arctic_shift"
PROVIDER_REDDIT_JSON = "reddit_json"
PROVIDER_OFFLINE_FIXTURES = "offline_fixtures"
VALID_SOURCE_PROVIDERS = (PROVIDER_ARCTIC_SHIFT, PROVIDER_REDDIT_JSON)

DEFAULT_USER_AGENT = "python:leadsweep:1.0 (self-hosted public-content-reader)"
DEFAULT_ARCHIVE_BASE_URL = "https://arctic-shift.photon-reddit.com"
DEFAULT_SEARCH_SUBREDDITS: tuple[str, ...] = (
    "SaaS",
    "Entrepreneur",
    "smallbusiness",
    "startups",
    "forhire",
)

# Documented, current Reddit position plus zero-credential archive disclosure.
DOCUMENTED_ACCESS_NOTE = (
    "Reddit's Data API requires OAuth and prior approval, and blocks direct unauthenticated traffic "
    "to www.reddit.com/*.json (HTTP 403 observed; commercial use of Reddit content is governed by "
    "Reddit's Public Content Policy). This integration never requests or stores Reddit account "
    "credentials. Live public ingestion uses the zero-credential Arctic Shift public archive REST API "
    "(arctic-shift.photon-reddit.com, robots.txt Disallow: empty) by default, or offline_fixtures "
    "with your own permitted Reddit JSON exports."
)


@dataclass(slots=True)
class RedditAccessConfig:
    """Resolved, secret-free access configuration."""

    enabled: bool
    mode: str
    user_agent: str
    base_url: str
    max_requests_per_minute: int
    max_concurrent_requests: int
    request_timeout: float
    max_retries: int
    cache_ttl_seconds: int
    fixture_dir: Path
    max_pages: int
    page_size: int
    comment_budget: int
    circuit_breaker_ttl_s: float
    source_provider: str = PROVIDER_ARCTIC_SHIFT
    archive_base_url: str = DEFAULT_ARCHIVE_BASE_URL
    default_search_subreddits: tuple[str, ...] = DEFAULT_SEARCH_SUBREDDITS

    @property
    def live_network_allowed(self) -> bool:
        """Only the public-unauthenticated mode touches the network."""
        return self.enabled and self.mode == PUBLIC_UNAUTHENTICATED

    @property
    def active_provider(self) -> str:
        if not self.enabled:
            return DISABLED
        if self.mode == OFFLINE_FIXTURES:
            return PROVIDER_OFFLINE_FIXTURES
        return self.source_provider

    def describe(self) -> dict[str, Any]:
        """Public, credential-free status payload."""
        notes: list[str] = []
        if not self.enabled:
            notes.append("Reddit integration is disabled by configuration.")
        elif self.mode == PUBLIC_UNAUTHENTICATED:
            if self.source_provider == PROVIDER_ARCTIC_SHIFT:
                notes.append(
                    f"Live zero-credential retrieval active via Arctic Shift Public Archive API ({self.archive_base_url}). "
                    "Newly archived posts (<36h) report initial capture scores until archive metric refresh."
                )
            notes.append(DOCUMENTED_ACCESS_NOTE)
        elif self.mode == OFFLINE_FIXTURES:
            notes.append(
                f"Offline fixture mode: reading Reddit JSON from {self.fixture_dir}. "
                "No network calls and no credentials are used."
            )
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "source_provider": self.active_provider,
            "archive_base_url": self.archive_base_url,
            "default_search_subreddits": list(self.default_search_subreddits),
            "requires_credentials": False,
            "credentials_configured": False,
            "personal_account_required": False,
            "live_network_allowed": self.live_network_allowed,
            "user_agent": self.user_agent,
            "max_requests_per_minute": self.max_requests_per_minute,
            "max_concurrent_requests": self.max_concurrent_requests,
            "request_timeout_s": self.request_timeout,
            "max_retries": self.max_retries,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "fixture_dir": str(self.fixture_dir),
            "page_size": self.page_size,
            "max_pages": self.max_pages,
            "comment_budget": self.comment_budget,
            "documented_access_note": DOCUMENTED_ACCESS_NOTE,
            "notes": notes,
        }


def _coerce_int(raw: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def load_access_config(settings: Any | None = None) -> RedditAccessConfig:
    """Build the access config from application settings without ever failing hard."""
    if settings is None:
        from leadsweep.config import get_settings

        settings = get_settings()

    mode = str(getattr(settings, "reddit_access_mode", PUBLIC_UNAUTHENTICATED) or "").strip().lower()
    if mode not in VALID_ACCESS_MODES:
        mode = PUBLIC_UNAUTHENTICATED

    provider = str(getattr(settings, "reddit_source_provider", PROVIDER_ARCTIC_SHIFT) or "").strip().lower()
    if provider not in VALID_SOURCE_PROVIDERS:
        provider = PROVIDER_ARCTIC_SHIFT

    enabled = bool(getattr(settings, "reddit_enabled", True)) and mode != DISABLED

    return RedditAccessConfig(
        enabled=enabled,
        mode=mode,
        user_agent=str(getattr(settings, "reddit_user_agent", DEFAULT_USER_AGENT) or DEFAULT_USER_AGENT),
        base_url=str(getattr(settings, "reddit_base_url", "https://www.reddit.com") or "https://www.reddit.com").rstrip("/"),
        max_requests_per_minute=_coerce_int(getattr(settings, "reddit_max_requests_per_minute", 30), 30, 1, 600),
        max_concurrent_requests=_coerce_int(getattr(settings, "reddit_max_concurrent_requests", 1), 1, 1, 4),
        request_timeout=float(getattr(settings, "reddit_request_timeout", 20.0) or 20.0),
        max_retries=_coerce_int(getattr(settings, "reddit_max_retries", 3), 3, 0, 5),
        cache_ttl_seconds=_coerce_int(getattr(settings, "reddit_cache_ttl_seconds", 900), 900, 0, 86400),
        fixture_dir=Path(getattr(settings, "reddit_fixture_dir", "data/reddit_fixtures") or "data/reddit_fixtures"),
        max_pages=_coerce_int(getattr(settings, "reddit_max_pages", 2), 2, 1, 10),
        page_size=_coerce_int(getattr(settings, "reddit_page_size", 25), 25, 1, 100),
        comment_budget=_coerce_int(getattr(settings, "reddit_comment_budget", 3), 3, 0, 25),
        circuit_breaker_ttl_s=float(getattr(settings, "reddit_circuit_breaker_ttl_s", 300.0) or 300.0),
        source_provider=provider,
        archive_base_url=str(
            getattr(settings, "reddit_archive_base_url", DEFAULT_ARCHIVE_BASE_URL) or DEFAULT_ARCHIVE_BASE_URL
        ).rstrip("/"),
        default_search_subreddits=DEFAULT_SEARCH_SUBREDDITS,
    )
