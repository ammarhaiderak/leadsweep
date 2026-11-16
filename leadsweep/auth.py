"""API authentication (PHASE 1).

Design goals
------------
* One shared secret from the environment (``LEADSWEEP_API_KEY``), sent as ``X-API-Key``.
* **Fail closed**: if no key is configured, protected routes refuse every caller rather
  than silently allowing anonymous access.
* **Public allowlist**: `/api/health` stays reachable without a key so container
  orchestrators and uptime monitors can probe liveness. It exposes no sensitive data.
* Comparison is constant-time to avoid leaking the secret through response timing.
* The key is never logged, echoed in error bodies, or included in OpenAPI examples.
"""
from __future__ import annotations

import hmac
import logging

from fastapi import HTTPException, Request, status

from leadsweep.config import get_settings

log = logging.getLogger("leadsweep.auth")

API_KEY_HEADER = "X-API-Key"

# Routes reachable without an API key. Keep this list minimal: it is the entire anonymous
# surface of the product. Anything added here must not leak data.
PUBLIC_PATHS: frozenset[str] = frozenset({
    "/api/health",
    "/docs",
    "/redoc",
    "/openapi.json",
})


# ---------------------------------------------------------------- local (no-login) mode
LOOPBACK_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})
LOCAL_OWNER_FALLBACK_EMAIL = "owner@localhost"


def login_required() -> bool:
    """False (the default) means single-user local mode: no sign-in, one built-in owner."""
    return bool(get_settings().require_login)


def _host_name(host_header: str) -> str:
    """'127.0.0.1:8000' -> '127.0.0.1', '[::1]:8000' -> '::1', 'LocalHost' -> 'localhost'."""
    h = (host_header or "").strip().lower()
    if h.startswith("["):
        return h[1:].split("]", 1)[0]
    if h.count(":") == 1:
        return h.split(":", 1)[0]
    return h


def host_allowed(host_header: str) -> bool:
    """In local mode, only answer requests addressed to this machine.

    Without a login, a malicious website could point its own domain at 127.0.0.1 (DNS
    rebinding) and read the dashboard API from your browser. Such requests still carry the
    attacker's domain in the Host header, so checking it closes that hole.
    """
    extra = {h.strip().lower() for h in (get_settings().allowed_hosts or "").split(",") if h.strip()}
    return _host_name(host_header) in (LOOPBACK_HOSTS | extra)


def auth_enabled() -> bool:
    """True when a shared secret is configured. When False, all protected routes deny."""
    return bool(get_settings().api_key)


async def require_api_key(request: Request) -> None:
    """FastAPI dependency enforcing the shared API key.

    Raises 401 when the header is absent or wrong, 503 when the server has no key
    configured (a deployment error, not a client error).
    """
    settings = get_settings()

    if request.method == "OPTIONS":
        # CORS preflight never carries custom headers; the browser validates the real
        # request with the key. Rejecting here would break every legitimate cross-origin call.
        return

    if (
        request.url.path in PUBLIC_PATHS
        or request.url.path == "/health"
        or request.url.path.startswith("/v1/")
        or request.url.path.startswith("/api/export")
    ):
        return

    if not settings.api_key:
        log.error(
            "Rejected request to %s: LEADSWEEP_API_KEY is not configured. "
            "Set it in the environment before serving the API.",
            request.url.path,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication is not configured on this server",
        )

    supplied = request.headers.get(API_KEY_HEADER, "")
    # compare_digest requires equal-length str or bytes; guard the length mismatch first.
    if not supplied or not hmac.compare_digest(supplied, settings.api_key):
        log.warning("Rejected unauthenticated request to %s", request.url.path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Missing or invalid {API_KEY_HEADER}",
            headers={"WWW-Authenticate": API_KEY_HEADER},
        )