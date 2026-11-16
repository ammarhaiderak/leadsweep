"""Phase 5 — Resilience engine: Canary health checker & Cookie-expiry alerting.

Provides:
- Endpoint-drift canary: tests SearchTimeline & UserOriginalsTimeline against known patterns
- Session health monitor: checks alive sessions, detects expiry, and alerts via webhook/log
- Fallback strategies & proactive notifications
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings, get_settings
from .exceptions import NoSessionAvailableError, ServerOutageError, SessionExpiredError
from .scraper import XScraper
from .session_pool import SessionPool

log = logging.getLogger("leadsweep.resilience")


class CanaryReport:
    def __init__(self) -> None:
        self.timestamp: str = datetime.now(timezone.utc).isoformat()
        self.sessions_total: int = 0
        self.sessions_healthy: int = 0
        self.sessions_dead: int = 0
        self.endpoints_healthy: bool = True
        self.search_timeline_ok: bool = False
        self.profile_timeline_ok: bool = False
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "sessions_total": self.sessions_total,
            "sessions_healthy": self.sessions_healthy,
            "sessions_dead": self.sessions_dead,
            "endpoints_healthy": self.endpoints_healthy,
            "search_timeline_ok": self.search_timeline_ok,
            "profile_timeline_ok": self.profile_timeline_ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "status": "ok" if (self.endpoints_healthy and self.sessions_healthy > 0) else "alert",
        }


def notify_alert(webhook_url: str | None, event_type: str, message: str, details: dict | None = None) -> bool:
    """Send an alert to a Discord / Slack / n8n webhook, or log it when no URL is configured.

    The HTTP call is a blocking ``urllib`` request on purpose (stdlib only, no new
    dependency), so callers running inside an asyncio event loop MUST use
    :func:`notify_alert_async`. A slow webhook would otherwise stall the whole loop.
    """
    log.warning("[ALERT %s] %s (details: %s)", event_type, message, details or {})
    if not webhook_url:
        return False
    return _post_alert(webhook_url, event_type, message, details)


def _post_alert(webhook_url: str, event_type: str, message: str, details: dict | None) -> bool:
    payload = {
        "event": f"LEADSWEEP_ALERT_{event_type.upper()}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": message,
        "details": details or {},
    }
    body = json.dumps(payload).encode("utf-8")
    try:
        req = urllib.request.Request(
            webhook_url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "leadsweep-resilience/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            return 200 <= resp.status < 300
    except Exception as e:  # noqa: BLE001
        # Never echo the webhook URL: it usually embeds a secret token.
        log.error("Failed to post alert via webhook (%s: %s)", type(e).__name__, e)
        return False


async def notify_alert_async(webhook_url: str | None, event_type: str, message: str,
                             details: dict | None = None) -> bool:
    """Non-blocking alert delivery for coroutines. Use this from any async path."""
    log.warning("[ALERT %s] %s (details: %s)", event_type, message, details or {})
    if not webhook_url:
        return False
    return await asyncio.to_thread(_post_alert, webhook_url, event_type, message, details)


async def run_resilience_canary(
    settings: Settings | None = None,
    check_profile: bool = True,
    profile_target: str = "github",
    headed: bool = False,
) -> CanaryReport:
    """End-to-end resilience canary: tests session validity, checks endpoint drift, and dispatches alerts."""
    s = settings or get_settings()
    report = CanaryReport()

    # 1. Inspect sessions pool
    try:
        pool = SessionPool(s.sessions_file, s.state_file)
        summary = pool.summary()
        report.sessions_total = len(summary)
        report.sessions_dead = sum(1 for item in summary if item["dead"])
        report.sessions_healthy = sum(1 for item in summary if not item["dead"])

        if report.sessions_healthy == 0:
            msg = "All cookie sessions are dead or invalid! Scraping is halted."
            report.errors.append(msg)
            report.endpoints_healthy = False
            notify_alert(s.webhook_url, "SESSIONS_EXPIRED", msg, {"summary": summary})
            return report

        if report.sessions_dead > 0:
            warn = f"{report.sessions_dead}/{report.sessions_total} sessions marked dead."
            report.warnings.append(warn)
            notify_alert(s.webhook_url, "SESSION_DEGRADED", warn, {"summary": summary})
    except Exception as e:  # noqa: BLE001
        err = f"Session pool init failed: {e}"
        report.errors.append(err)
        report.endpoints_healthy = False
        return report

    # 2. Test SearchTimeline endpoint (proactive drift detection)
    scraper_settings = s.model_copy(update={"headless": not headed})
    try:
        log.info("Canary checking SearchTimeline endpoint...")
        async with XScraper(settings=scraper_settings, pool=pool) as scraper:
            # Use a robust English query to avoid X's rate-limiting on bare 2-letter search terms
            tweets = await scraper.search_with_failover(query="AI lang:en", max_results=5)
            if tweets:
                report.search_timeline_ok = True
            else:
                report.warnings.append("SearchTimeline returned 0 tweets (check query or layout)")

            # 3. Test UserOriginalsTimeline / UserTweets endpoint
            if check_profile and report.endpoints_healthy:
                try:
                    log.info("Canary checking profile timeline endpoint for @%s...", profile_target)
                    p_tweets = await scraper.profile_with_failover(username=profile_target, limit=5)
                    if p_tweets:
                        report.profile_timeline_ok = True
                    else:
                        report.warnings.append(f"Profile @{profile_target} returned 0 tweets")
                except ServerOutageError as e:
                    msg = f"Profile timeline temporarily unavailable (X/Cloudflare edge outage): {e}"
                    report.warnings.append(msg)
                    report.profile_timeline_ok = False
                except Exception as e:  # noqa: BLE001
                    msg = f"Profile timeline canary failed: {e}"
                    report.errors.append(msg)
                    report.profile_timeline_ok = False
                    notify_alert(s.webhook_url, "ENDPOINT_DRIFT_PROFILE", msg)
    except SessionExpiredError as e:
        msg = f"Canary detected expired session during search: {e}"
        report.errors.append(msg)
        report.endpoints_healthy = False
        notify_alert(s.webhook_url, "SESSION_EXPIRED", msg)
    except Exception as e:  # noqa: BLE001
        msg = f"SearchTimeline canary failed: {e}"
        report.errors.append(msg)
        report.endpoints_healthy = False
        notify_alert(s.webhook_url, "ENDPOINT_DRIFT", msg)

    # Save canary report to data/debug/canary_last.json
    try:
        dump_path = Path("data/debug/canary_last.json")
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        dump_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    return report
