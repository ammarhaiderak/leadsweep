"""Tests for API authentication and CORS policy (PHASE 1).

Covers the exact behaviours the security boundary promises:
  * protected routes reject anonymous callers
  * an invalid key is rejected with 401 and never leaks the expected key
  * a valid key is accepted
  * /api/health stays public but reveals no secrets
  * a missing LEADSWEEP_API_KEY fails CLOSED (503), never open
  * CORS has no wildcard and honours LEADSWEEP_CORS_ORIGINS
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from leadsweep.api import app
from leadsweep.auth import API_KEY_HEADER, PUBLIC_PATHS, auth_enabled
from leadsweep.config import parse_cors_origins

PROTECTED_ROUTES = [
    ("GET", "/api/leads"),
    ("GET", "/api/targets"),
    ("GET", "/api/followers"),
    ("GET", "/api/jobs"),
    ("GET", "/api/runs"),
    ("GET", "/api/eval"),
]


# --------------------------------------------------------------------------- config helpers
def test_parse_cors_origins_trims_and_drops_blanks():
    assert parse_cors_origins("http://a.test, ,http://b.test ,") == ["http://a.test", "http://b.test"]


def test_parse_cors_origins_empty_string_yields_empty_list():
    """An empty allowlist must deny every origin, never fall back to '*'."""
    assert parse_cors_origins("") == []
    assert parse_cors_origins("   ,  ") == []


def test_default_cors_origins_are_not_wildcard():
    from leadsweep.config import DEFAULT_CORS_ORIGINS

    origins = parse_cors_origins(DEFAULT_CORS_ORIGINS)
    assert origins, "there must be a sane dev default"
    assert "*" not in origins


def test_auth_enabled_reflects_configuration(monkeypatch):
    monkeypatch.setenv("LEADSWEEP_API_KEY", "abc123")
    assert auth_enabled() is True
    monkeypatch.setenv("LEADSWEEP_API_KEY", "")
    assert auth_enabled() is False


# --------------------------------------------------------------------------- missing key
def test_missing_key_is_rejected_with_401(anon_client, tmp_db):
    for method, path in PROTECTED_ROUTES:
        res = anon_client.request(method, path)
        assert res.status_code == 401, f"{method} {path} should require a key"
        assert API_KEY_HEADER in res.json()["detail"] or API_KEY_HEADER in str(res.json())


def test_missing_key_response_does_not_leak_the_real_key(anon_client, tmp_db, auth_headers):
    res = anon_client.get("/api/leads")
    assert res.status_code == 401
    # The test key itself must never appear in an error body or header.
    combined = res.text + str(dict(res.headers))
    assert auth_headers[API_KEY_HEADER] not in combined


# --------------------------------------------------------------------------- invalid key
def test_invalid_key_is_rejected_with_401(tmp_db):
    with TestClient(app) as c:
        res = c.get("/api/leads", headers={API_KEY_HEADER: "wrong-key-entirely"})
    assert res.status_code == 401


def test_empty_key_header_is_rejected(tmp_db):
    with TestClient(app) as c:
        res = c.get("/api/leads", headers={API_KEY_HEADER: ""})
    assert res.status_code == 401


def test_key_of_correct_length_but_wrong_value_is_rejected(tmp_db):
    """Guards against a length-only comparison sneaking through."""
    from tests.conftest import TEST_API_KEY

    with TestClient(app) as c:
        res = c.get("/api/leads", headers={API_KEY_HEADER: "X" * len(TEST_API_KEY)})
    assert res.status_code == 401


# --------------------------------------------------------------------------- valid key
def test_valid_key_is_accepted(client, tmp_db):
    for method, path in PROTECTED_ROUTES:
        res = client.request(method, path)
        assert res.status_code == 200, f"{method} {path} should accept a valid key"


def test_write_routes_require_the_key_too(tmp_db):
    with TestClient(app) as c:
        assert c.post("/api/feedback", json={"entity_id": "x", "entity_type": "tweet", "label": "good"}).status_code == 401
        assert c.post("/api/targets", json={"handle": "someone"}).status_code == 401


def test_valid_key_is_accepted_on_write_routes(client, tmp_db):
    res = client.post("/api/targets", json={"handle": "auth_probe_target", "kind": "prospect"})
    assert res.status_code == 200


# --------------------------------------------------------------------------- health
def test_health_is_public_without_a_key(anon_client, tmp_db):
    res = anon_client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"


def test_health_reports_whether_auth_is_configured(client, tmp_db):
    body = client.get("/api/health").json()
    assert body["auth_required"] is True


def test_health_contains_no_config_secrets(anon_client, tmp_db):
    body = anon_client.get("/api/health").json()
    # Only these keys should ever be present on the public endpoint.
    assert set(body) == {
        "status",
        "version",
        "db_version",
        "tweets_count",
        "users_count",
        "auth_required",
        "login_required",
    }


def test_health_never_returns_sessions_or_runs(anon_client, tmp_db):
    body = anon_client.get("/api/health").text.lower()
    for leak in ("sessions", "auth_token", "ct0", "cookie"):
        assert leak not in body


# --------------------------------------------------------------------------- fail closed
def test_missing_configuration_fails_closed(monkeypatch, tmp_db):
    """With LEADSWEEP_API_KEY unset, protected routes must 503 - never serve data."""
    monkeypatch.setenv("LEADSWEEP_API_KEY", "")
    monkeypatch.delenv("LEADSWEEP_API_KEY", raising=False)
    with TestClient(app) as c:
        res = c.get("/api/leads")
        assert res.status_code == 503
        assert "not configured" in res.json()["detail"].lower()
        # And health still answers so orchestrators can see the misconfiguration.
        assert c.get("/api/health").status_code == 200


def test_public_allowlist_is_minimal():
    """The anonymous surface of the product. Widening this is a security decision."""
    assert PUBLIC_PATHS == frozenset({"/api/health", "/docs", "/redoc", "/openapi.json"})
    assert not any(p.startswith("/api/leads") for p in PUBLIC_PATHS)
    assert "/api/session" not in PUBLIC_PATHS


# --------------------------------------------------------------------------- CORS
def test_cors_preflight_is_allowed_without_a_key(tmp_db):
    """Browsers never attach custom headers to a preflight, so it must not be rejected."""
    with TestClient(app) as c:
        res = c.options(
            "/api/leads",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": API_KEY_HEADER,
            },
        )
    assert res.status_code == 200


def test_cors_allows_configured_origin(client, tmp_db):
    res = client.get("/api/leads", headers={"Origin": "http://localhost:5173"})
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_does_not_allow_unconfigured_origin(client, tmp_db):
    res = client.get("/api/leads", headers={"Origin": "http://evil.example.com"})
    assert res.status_code == 200
    assert "access-control-allow-origin" not in {k.lower() for k in res.headers}


def test_cors_never_wildcards(client, tmp_db):
    """Even from an unlisted origin the server must not answer with '*'."""
    res = client.get("/api/leads", headers={"Origin": "http://evil.example.com"})
    assert res.headers.get("access-control-allow-origin") != "*"


def test_cors_honours_configured_origins(monkeypatch):
    """Verify the middleware is built from LEADSWEEP_CORS_ORIGINS.

    The middleware stack is built once at import time (FastAPI forbids adding middleware
    after startup), so this asserts on the configuration the app was constructed with
    rather than trying to rebuild the live stack.
    """
    from starlette.middleware.cors import CORSMiddleware

    from leadsweep.api import _configure_cors

    monkeypatch.setenv("LEADSWEEP_CORS_ORIGINS", "https://studio.example.com,https://admin.example.com")

    # Build a throwaway app so the production app's stack is untouched.
    from fastapi import FastAPI

    probe = FastAPI()
    _configure_cors(probe)
    cors = next(m for m in probe.user_middleware if m.cls is CORSMiddleware)
    assert cors.kwargs["allow_origins"] == ["https://studio.example.com", "https://admin.example.com"]
    assert cors.kwargs["allow_credentials"] is True
    assert "*" not in cors.kwargs["allow_origins"]


def test_cors_with_empty_configuration_denies_every_origin(monkeypatch):
    """An empty allowlist must not silently become a permissive policy."""
    from fastapi import FastAPI
    from starlette.middleware.cors import CORSMiddleware

    from leadsweep.api import _configure_cors

    monkeypatch.setenv("LEADSWEEP_CORS_ORIGINS", ",")  # blank means "use default"; "," is explicitly empty
    probe = FastAPI()
    _configure_cors(probe)
    cors = next(m for m in probe.user_middleware if m.cls is CORSMiddleware)
    assert cors.kwargs["allow_origins"] == []
    # Credentials must not be enabled when there is nothing to enable them for.
    assert cors.kwargs["allow_credentials"] is False