"""Regression tests that keep credentials out of tracked source (PHASE 1 / PHASE 15).

These run the real scanner in-process against the repository root. If someone reintroduces a
hardcoded key into a tracked file, the suite goes red before the change can ship.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.secret_scan import LOCAL_SECRET_FILES, RULES, scan

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def findings() -> list[dict[str, object]]:
    return scan(REPO_ROOT)


def test_no_credentials_in_tracked_source(findings):
    """The core guarantee: zero critical findings anywhere in tracked files."""
    critical = [f for f in findings if f["severity"] == "critical"]
    if critical:
        reported = "\n".join(f"  {f['file']}:{f['line']} [{f['rule']}]" for f in critical)
        pytest.fail(f"Credentials found in tracked source (values withheld):\n{reported}")


def test_local_secret_files_are_gitignored(findings):
    """Files holding real credentials locally must stay excluded from version control."""
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    web_gitignore = (REPO_ROOT / "project" / ".gitignore").read_text(encoding="utf-8")
    combined = gitignore + web_gitignore

    assert ".env" in combined
    assert "sessions.json" in combined
    assert ".insforge" in combined
    assert "*.local" in combined
    assert "node_modules" in combined
    assert "data/*" in combined
    assert "dist" in combined


def test_docker_compose_contains_no_key_values():
    """Compose must reference env vars, never embed a working credential."""
    text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for rule in RULES:
        assert not rule.pattern.search(text), f"docker-compose.yml matches {rule.name}"


def test_frontend_source_contains_no_key_values():
    src = REPO_ROOT / "web" / "src"
    for path in src.rglob("*.ts*"):
        text = path.read_text(encoding="utf-8")
        for rule in RULES:
            assert not rule.pattern.search(text), f"{path.name} matches {rule.name}"


def test_scanner_rules_detect_each_credential_type():
    """The scanner must actually catch what it claims to catch (no silently-passing rules)."""
    samples = {
        "groq_api_key": "KEY = 'gsk_" + "a" * 40 + "'",
        "insforge_key": "KEY = 'ik_" + "b" * 30 + "'",
        "openai_key": "KEY = 'sk-" + "c" * 40 + "'",
        "aws_access_key": "AWS = '" + "AKIAIOSFODNN7EXAMPLE" + "'",
        "private_key_block": "-----BEGIN RSA PRIVATE KEY-----",
    }
    for rule_name, sample in samples.items():
        rule = next(r for r in RULES if r.name == rule_name)
        assert rule.pattern.search(sample), f"rule {rule_name} failed to match its own sample"