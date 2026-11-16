import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from leadsweep.config import Settings
from leadsweep.resilience import CanaryReport, notify_alert, run_resilience_canary


def test_canary_report_structure():
    rep = CanaryReport()
    rep.sessions_total = 2
    rep.sessions_healthy = 2
    rep.search_timeline_ok = True
    d = rep.to_dict()
    assert d["status"] == "ok"
    assert d["sessions_healthy"] == 2
    assert d["search_timeline_ok"] is True


def test_canary_report_degraded():
    rep = CanaryReport()
    rep.sessions_total = 1
    rep.sessions_healthy = 0
    rep.sessions_dead = 1
    d = rep.to_dict()
    assert d["status"] == "alert"


def test_notify_alert_without_webhook():
    assert notify_alert(None, "TEST", "Message") is False


@patch("urllib.request.urlopen")
def test_notify_alert_with_mock_webhook(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    res = notify_alert("http://localhost:9999/webhook", "COOKIE_EXPIRED", "Session died", {"user": "test"})
    assert res is True
    mock_urlopen.assert_called_once()
