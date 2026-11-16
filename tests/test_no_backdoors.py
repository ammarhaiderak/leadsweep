"""Regression tests: no built-in credentials, master tokens or default secrets."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADSWEEP_DB_PATH", str(tmp_path / "backdoor.db"))
    from leadsweep import api as api_module

    with TestClient(api_module.app) as c:
        yield c


@pytest.mark.parametrize("token", ["tok_admin_master", "tok_admin_master_active", "admin_master_token", "tok_admin_x"])
def test_magic_admin_tokens_are_rejected(api_client, token):
    headers = {"Authorization": f"Bearer {token}"}
    assert api_client.get("/v1/admin/users", headers=headers).status_code == 401
    assert api_client.get("/v1/auth/me", params={"token": token}).status_code == 401


def test_env_admin_login_requires_configured_password(api_client, monkeypatch):
    monkeypatch.delenv("LEADSWEEP_ADMIN_PASSWORD", raising=False)
    res = api_client.post("/v1/auth/login", json={"email": "owner@example.com", "password": ""})
    assert res.status_code in (401, 422)
    res = api_client.post("/v1/auth/login", json={"email": "owner@example.com", "password": "anything"})
    assert res.status_code == 401


def test_env_admin_login_works_with_configured_password(api_client, monkeypatch):
    monkeypatch.setenv("LEADSWEEP_ADMIN_PASSWORD", "correct-horse")
    bad = api_client.post("/v1/auth/login", json={"email": "owner@example.com", "password": "wrong"})
    assert bad.status_code == 401
    good = api_client.post("/v1/auth/login", json={"email": "owner@example.com", "password": "correct-horse"})
    assert good.status_code == 200
    token = good.json()["token"]
    me = api_client.get("/v1/auth/me", params={"token": token})
    assert me.status_code == 200 and me.json()["role"] == "owner"


def test_plaintext_passwords_are_never_returned(api_client, monkeypatch):
    monkeypatch.setenv("LEADSWEEP_ADMIN_PASSWORD", "correct-horse")
    token = api_client.post("/v1/auth/login", json={"email": "owner@example.com", "password": "correct-horse"}).json()["token"]
    users = api_client.get("/v1/admin/users", headers={"Authorization": f"Bearer {token}"}).json()
    assert users and all(u["password"] == "••••••••" for u in users)
    assert all("correct-horse" not in str(u) for u in users)


def test_no_default_owner_is_seeded(tmp_path):
    from leadsweep.pipeline.store import Store

    store = Store(tmp_path / "fresh.db")
    try:
        assert store.db.execute("SELECT COUNT(*) FROM app_users").fetchone()[0] == 0
    finally:
        store.close()


def test_normal_user_cannot_use_owner_endpoints(api_client):
    from tests._auth_helpers import make_session_token

    headers = {"Authorization": f"Bearer {make_session_token('normal.user@example.com', 'user')}"}
    assert api_client.get("/v1/admin/users", headers=headers).status_code == 403
    res = api_client.post("/v1/admin/users", headers=headers,
                          json={"name": "X", "email": "x@example.com", "password": "password123"})
    assert res.status_code == 403
    assert api_client.delete("/v1/admin/users/owner@example.com", headers=headers).status_code == 403


def test_owner_adds_user_who_can_sign_in(api_client, monkeypatch):
    monkeypatch.setenv("LEADSWEEP_ADMIN_PASSWORD", "correct-horse")
    token = api_client.post("/v1/auth/login", json={"email": "owner@example.com", "password": "correct-horse"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    res = api_client.post("/v1/admin/users", headers=headers,
                          json={"name": "Teammate", "email": "mate@example.com", "password": "teammate-pass"})
    assert res.status_code == 200, res.text
    login = api_client.post("/v1/auth/login", json={"email": "mate@example.com", "password": "teammate-pass"})
    assert login.status_code == 200 and login.json()["user"]["role"] == "user"


def test_public_early_access_signup_is_gone(api_client):
    res = api_client.post("/v1/early-access", json={"name": "A", "email": "a@example.com"})
    assert res.status_code in (404, 405)
