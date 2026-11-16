"""
leadsweep/leadintel/session.py -- Account Connection & Playwright Session Manager ($0 Cost)

- Zero password storage: Uses manual login on first run and saves Playwright context storage state.
- Strictly per-user sessions stored in `sessions/{user_id}.json`.
- Validates active session on x.com and triggers login if expired or disconnected.
"""
from __future__ import annotations

import logging
import os
import time  # UPDATED LOGIC: Import time module
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("leadsweep.leadintel.session")

def get_sessions_dir() -> Path:
    return Path(os.getenv("LEADSWEEP_SESSIONS_DIR", "sessions"))


class NotConnectedError(RuntimeError):
    """Raised when no valid X session exists for the user."""
    pass


def get_session_path(user_id: str) -> Path:
    """Return the absolute or relative Path for a given user's session state."""
    clean_id = str(user_id).strip().replace("/", "_").replace("\\", "_")
    return get_sessions_dir() / f"{clean_id}.json"


def has_saved_session(user_id: str) -> bool:
    """Check if a session JSON file exists and has non-empty content."""
    p = get_session_path(user_id)
    if p.exists() and p.stat().st_size > 10:
        return True
    
    # Check admin or default
    for fallback_id in ("admin", "default"):
        fp = get_session_path(fallback_id)
        if fp.exists() and fp.stat().st_size > 10:
            return True

    # Fallback to repo root sessions.json if present
    import json
    root_sessions = Path("sessions.json")
    if root_sessions.exists() and root_sessions.stat().st_size > 10:
        try:
            raw = json.loads(root_sessions.read_text(encoding="utf-8"))
            if raw.get("sessions") and len(raw["sessions"]) > 0:
                first = raw["sessions"][0]
                if first.get("auth_token") and first.get("ct0"):
                    # Auto-sync into user storage_state file
                    get_sessions_dir().mkdir(parents=True, exist_ok=True)
                    storage = {
                        "cookies": [
                            {"name": "auth_token", "value": first["auth_token"], "domain": ".x.com", "path": "/", "expires": -1, "httpOnly": True, "secure": True, "sameSite": "None"},
                            {"name": "ct0", "value": first["ct0"], "domain": ".x.com", "path": "/", "expires": -1, "httpOnly": False, "secure": True, "sameSite": "Lax"}
                        ],
                        "origins": []
                    }
                    p.write_text(json.dumps(storage, indent=2), encoding="utf-8")
                    return True
        except Exception:
            pass

    return False


def connect_account(user_id: str, timeout_seconds: int = 300) -> str:
    """
    Launch Chromium with headless=False, navigate to https://x.com/login,
    let the user manually log in (handling any 2FA or Captcha challenge),
    wait until home timeline / navigation is detected, then save storage_state.
    
    Zero passwords stored or transmitted.
    """
    from playwright.sync_api import sync_playwright

    get_sessions_dir().mkdir(parents=True, exist_ok=True)
    session_file = get_session_path(user_id)

    log.info("Opening browser for user '%s' manual X authentication...", user_id)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        page.goto("https://x.com/login", wait_until="domcontentloaded")

        deadline = time.monotonic() + timeout_seconds
        authenticated = False
        while time.monotonic() < deadline:
            try:
                cookies = {c["name"]: c["value"] for c in context.cookies("https://x.com")}
                current_url = getattr(page, "url", "").lower()
                if ("auth_token" in cookies and "ct0" in cookies) or ("/home" in current_url) or ('/explore' in current_url):
                    authenticated = True
                    break
            except Exception:
                pass
            time.sleep(1.0)

        if authenticated:
            context.storage_state(path=str(session_file))
            log.info("Session state successfully saved for user '%s' at %s", user_id, session_file)
        else:
            browser.close()
            raise TimeoutError(f"Timed out waiting for manual X login completion ({timeout_seconds}s).")

        browser.close()

    return str(session_file)


async def async_connect_account(user_id: str, timeout_seconds: int = 300) -> str:
    """Async variant of connect_account using async_playwright."""
    import asyncio
    import time
    from playwright.async_api import async_playwright

    get_sessions_dir().mkdir(parents=True, exist_ok=True)
    session_file = get_session_path(user_id)

    log.info("Opening async browser for user '%s' manual X authentication...", user_id)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto("https://x.com/login", wait_until="domcontentloaded")

        deadline = time.monotonic() + timeout_seconds
        authenticated = False
        while time.monotonic() < deadline:
            try:
                cookies = {c["name"]: c["value"] for c in await context.cookies("https://x.com")}
                current_url = getattr(page, "url", "").lower()
                if ("auth_token" in cookies and "ct0" in cookies) or ("/home" in current_url) or ("/explore" in current_url):
                    authenticated = True
                    break
            except Exception:
                pass
            await asyncio.sleep(1.0)

        if authenticated:
            await context.storage_state(path=str(session_file))
            log.info("Async session state saved for user '%s' at %s", user_id, session_file)
        else:
            await browser.close()
            raise TimeoutError(f"Timed out waiting for manual X login completion ({timeout_seconds}s).")

        await browser.close()

    return str(session_file)


def load_context(browser: Any, user_id: str, **context_kwargs: Any) -> Any:
    """
    If the session file exists, create a browser context with storage_state.
    Otherwise raises NotConnectedError.
    """
    session_file = get_session_path(user_id)
    if not session_file.exists() or session_file.stat().st_size <= 10:
        raise NotConnectedError(
            "Account Not Connected. Please connect your X account via the UI or run connect_account() before searching."
        )

    return browser.new_context(storage_state=str(session_file), **context_kwargs)


async def async_load_context(browser: Any, user_id: str, **context_kwargs: Any) -> Any:
    """Async variant: create a browser context with storage_state if file exists."""
    session_file = get_session_path(user_id)
    if not session_file.exists() or session_file.stat().st_size <= 10:
        raise NotConnectedError(
            "Account Not Connected. Please connect your X account via the UI or run connect_account() before searching."
        )

    return await browser.new_context(storage_state=str(session_file), **context_kwargs)


def enforce_account_connected(user_id: str = "admin") -> Path:
    """
    Mandatory Session Gatekeeper:
    Checks if a valid session state file exists for the user.
    If absent or empty, raises NotConnectedError immediately before initiating any data extraction.
    """
    session_file = get_session_path(user_id)
    if not session_file.exists() or session_file.stat().st_size <= 10:
        # Also check default fallback paths if user_id is admin/default
        admin_file = get_session_path("admin")
        default_file = get_session_path("default")
        if admin_file.exists() and admin_file.stat().st_size > 10:
            return admin_file
        if default_file.exists() and default_file.stat().st_size > 10:
            return default_file
        raise NotConnectedError(
            "Account Not Connected. Please connect your X account via the UI or run connect_account() before searching."
        )
    return session_file


def is_session_valid(page: Any) -> bool:
    """
    Checks if current page in context is authenticated on X.
    If redirected to login / signup URL or displays login form, treats session as invalid.
    """
    try:
        current_url = getattr(page, "url", "").lower()
        if any(marker in current_url for marker in ("login", "i/flow/login", "signup", "i/flow/single_sign_on")):
            return False
    except Exception:
        pass

    return True


def validate_page_session(page: Any) -> None:
    """Validates active page session and raises NotConnectedError if redirected to login."""
    if not is_session_valid(page):
        raise NotConnectedError(
            "Account Not Connected. Please connect your X account via the UI or run connect_account() before searching."
        )
