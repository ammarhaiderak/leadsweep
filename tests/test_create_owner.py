"""Tests for scripts/create_owner.py using temporary SQLite database."""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.create_owner import create_or_reset_owner, main
from leadsweep.pipeline.store import Store


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    db_file = tmp_path / "temp_leadsweep.db"
    store = Store(db_file)
    store.close()
    return db_file


def test_create_new_owner(temp_db: Path):
    email = "testowner@example.com"
    raw_pwd = "SuperSecretPassword123"

    create_or_reset_owner(temp_db, email, raw_pwd)

    conn = sqlite3.connect(str(temp_db))
    conn.row_factory = sqlite3.Row
    user = conn.execute("SELECT * FROM app_users WHERE email = ?", (email,)).fetchone()
    conn.close()

    assert user is not None
    assert user["email"] == email
    assert user["role"] == "owner"
    assert user["status"] == "APPROVED"
    assert user["early_access_status"] == 1
    expected_hash = hashlib.sha256(raw_pwd.encode("utf-8")).hexdigest()
    assert user["password_hash"] == expected_hash


def test_reset_existing_owner(temp_db: Path):
    email = "testowner@example.com"
    pwd1 = "FirstPassword123"
    pwd2 = "SecondPassword456"

    create_or_reset_owner(temp_db, email, pwd1)
    create_or_reset_owner(temp_db, email, pwd2)

    conn = sqlite3.connect(str(temp_db))
    conn.row_factory = sqlite3.Row
    user = conn.execute("SELECT * FROM app_users WHERE email = ?", (email,)).fetchone()
    conn.close()

    assert user is not None
    expected_hash = hashlib.sha256(pwd2.encode("utf-8")).hexdigest()
    assert user["password_hash"] == expected_hash


def test_validation_errors(temp_db: Path):
    with pytest.raises(ValueError, match="Invalid owner email"):
        create_or_reset_owner(temp_db, "invalid-email", "validpassword123")

    with pytest.raises(ValueError, match="at least 6 characters"):
        create_or_reset_owner(temp_db, "owner@example.com", "123")


def test_cli_main_success(temp_db: Path, monkeypatch):
    monkeypatch.setenv("LEADSWEEP_OWNER_EMAIL", "cliowner@example.com")
    monkeypatch.setattr(
        "sys.argv",
        ["create_owner.py", "--db-path", str(temp_db), "--email", "cliowner@example.com"],
    )

    with patch("getpass.getpass", side_effect=["ValidPass123", "ValidPass123"]):
        exit_code = main()

    assert exit_code == 0
    conn = sqlite3.connect(str(temp_db))
    conn.row_factory = sqlite3.Row
    user = conn.execute("SELECT * FROM app_users WHERE email = ?", ("cliowner@example.com",)).fetchone()
    conn.close()
    assert user is not None
    assert user["role"] == "owner"


def test_cli_main_mismatch(temp_db: Path, monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["create_owner.py", "--db-path", str(temp_db), "--email", "cliowner@example.com"],
    )

    with patch("getpass.getpass", side_effect=["PassA123", "PassB123"]):
        exit_code = main()

    assert exit_code == 1
