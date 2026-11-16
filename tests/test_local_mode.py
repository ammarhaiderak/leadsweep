"""Default single-user mode: no login, one built-in owner, localhost-only."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def local_client(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[TestClient]:
    monkeypatch.setenv("LEADSWEEP_REQUIRE_LOGIN", "false")
    monkeypatch.setenv("LEADSWEEP_DB_PATH", str(tmp_path / "local.db"))
    from leadsweep import api as api_module

    api_module._LOCAL_OWNER_CACHE.clear()
    with TestClient(api_module.app, base_url="http://127.0.0.1:8000") as c:
        yield c


def test_default_is_no_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEADSWEEP_REQUIRE_LOGIN", raising=False)
    from leadsweep.config import Settings

    assert Settings(_env_file=None).require_login is False


def test_me_returns_local_owner_without_token(local_client: TestClient) -> None:
    r = local_client.get("/v1/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["authMode"] == "local"
    assert body["role"] == "owner"
    assert body["email"] == "owner@example.com"  # LEADSWEEP_ADMIN_EMAIL from conftest


def test_local_owner_falls_back_without_admin_email(
    local_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)  # settings also read ./.env; make sure no developer .env leaks in
    for var in ("LEADSWEEP_ADMIN_EMAIL", "LEADSWEEP_OWNER_EMAIL", "ADMIN_EMAIL"):
        monkeypatch.delenv(var, raising=False)
    r = local_client.get("/v1/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == "owner@localhost"


def test_owner_only_routes_work_without_login(local_client: TestClient) -> None:
    r = local_client.get("/v1/admin/users")
    assert r.status_code not in (401, 403), r.text


@pytest.mark.parametrize("host", ["127.0.0.1:8000", "localhost:8000", "[::1]:8000", "LOCALHOST"])
def test_localhost_hosts_allowed(local_client: TestClient, host: str) -> None:
    assert local_client.get("/v1/auth/me", headers={"host": host}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example.com", "192.168.1.20:8000", "127.0.0.1.evil.com"])
def test_foreign_hosts_blocked(local_client: TestClient, host: str) -> None:
    r = local_client.get("/v1/auth/me", headers={"host": host})
    assert r.status_code == 403
    assert "LEADSWEEP_REQUIRE_LOGIN" in r.json()["detail"]


def test_health_reachable_from_any_host(local_client: TestClient) -> None:
    assert local_client.get("/health?minimal=1", headers={"host": "leadsweep"}).status_code == 200


def test_allowed_hosts_extends_list(local_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEADSWEEP_ALLOWED_HOSTS", "devbox, leadsweep.lan")
    assert local_client.get("/v1/auth/me", headers={"host": "leadsweep.lan:8000"}).status_code == 200


def test_login_mode_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEADSWEEP_REQUIRE_LOGIN", "true")
    from leadsweep import api as api_module

    with TestClient(api_module.app) as c:  # host "testserver": guard is off in login mode
        assert c.get("/v1/auth/me").status_code == 401
        assert c.get("/v1/admin/users").status_code == 401
