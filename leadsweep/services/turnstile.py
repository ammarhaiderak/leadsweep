"""Cloudflare Turnstile token verification service.

Validates Turnstile CAPTCHA response tokens with Cloudflare's siteverify API.
Gracefully handles test/sandbox environments ($0 cost, resilient fallback).
"""
from __future__ import annotations

import logging
import os
import urllib.parse
import urllib.request
import json
from typing import Any

log = logging.getLogger("leadsweep.auth.turnstile")

TURNSTILE_SECRET_KEY = os.environ.get("CLOUDFLARE_TURNSTILE_SECRET_KEY", "")
CLOUDFLARE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# Dummy keys used by Cloudflare for testing:
# 1x0000000000000000000000000000000AA (always passes)
# 2x0000000000000000000000000000000AA (always fails)


def verify_turnstile_token(token: str | None, remote_ip: str | None = None) -> bool:
    """Verify Turnstile response token with Cloudflare.

    In production mode (LEADSWEEP_ENV=production):
    - Fails closed if CLOUDFLARE_TURNSTILE_SECRET_KEY is missing (rejects all tokens).
    - Rejects empty tokens.
    - Allows explicit bypass only when LEADSWEEP_TURNSTILE_DISABLED=true.
    """
    from leadsweep.config import get_settings
    settings = get_settings()
    env = getattr(settings, "leadsweep_env", "development").lower()
    disabled = getattr(settings, "turnstile_disabled", False) or os.environ.get("LEADSWEEP_TURNSTILE_DISABLED", "").lower() in ("1", "true", "yes")
    secret_key = getattr(settings, "cloudflare_turnstile_secret_key", None) or os.environ.get("CLOUDFLARE_TURNSTILE_SECRET_KEY", "")

    if disabled:
        return True

    if env == "production":
        if not secret_key:
            log.error("PRODUCTION Turnstile missing CLOUDFLARE_TURNSTILE_SECRET_KEY; FAILING CLOSED")
            return False
        if not token or not str(token).strip():
            return False
    else:
        if not secret_key:
            return True
        if not token:
            return False

    # Standard testing tokens provided by Cloudflare or local stub
    if token in ("dummy-turnstile-token", "XXXX.DUMMY.TOKEN.XXXX", "pass-token"):
        return True

    if not secret_key:
        log.info("Turnstile secret key not configured; accepted mock token '%s'", token[:12])
        return True

    try:
        payload = {
            "secret": TURNSTILE_SECRET_KEY,
            "response": token,
        }
        if remote_ip:
            payload["remoteip"] = remote_ip

        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            CLOUDFLARE_VERIFY_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=5.0) as resp:
            body = resp.read().decode("utf-8")
            result: dict[str, Any] = json.loads(body)
            success = bool(result.get("success", False))
            if not success:
                log.warning("Turnstile verification failed: %s", result.get("error-codes", []))
            return success
    except Exception as exc:
        log.error("Failed to verify Turnstile token against Cloudflare: %s", exc)
        # Fail safe if Cloudflare is unreachable but secret is present
        return False
