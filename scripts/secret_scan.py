"""Secret scanner (PHASE 1 / PHASE 15).

Scans the repository for credentials that must never live in tracked source. It reports the
FILE, LINE and SECRET TYPE only - never the matched value - so running it is always safe to
paste into a ticket.

    python -m scripts.secret_scan          # scan and exit non-zero on findings
    python -m scripts.secret_scan --json   # machine-readable output

Patterns cover the credential shapes this project actually uses plus common generic ones.
Allow-listed by path (see IGNORED_PATH_PREFIXES) are examples, templates and build output.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Directories that never contain tracked source we own.
SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", "dist",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".eggs", "*.egg-info",
}

# Paths where a credential-like string is expected and acceptable (examples/templates).
IGNORE_PATTERNS = (
    "sessions.example.json",
    "sessions.fixture.json",
    "tests/fixtures/",
    ".env.example",
    "scripts/secret_scan.py",
    "tests/conftest.py",
    # Holds deliberately fake credentials that prove each rule still matches.
    "tests/test_secret_scan.py",
    "data/",
    "node_modules/",
)

# Local, gitignored runtime files that are SUPPOSED to hold real credentials on a developer
# machine. A finding here is not a defect - but it is also why these files must stay ignored.
# Findings in these paths are reported as INFO; findings anywhere else are FAILURES.
LOCAL_SECRET_FILES = (
    ".env",
    "sessions.json",
    ".insforge/project.json",
    "web/.env.local",
)


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    description: str


RULES: tuple[Rule, ...] = (
    Rule("groq_api_key", re.compile(r"\bgsk_[A-Za-z0-9_\-]{20,}"),
         "Groq API key"),
    Rule("insforge_key", re.compile(r"\bik_[A-Za-z0-9]{20,}"),
         "InsForge anon/service key"),
    Rule("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
         "OpenAI-style API key"),
    Rule("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
         "AWS access key id"),
    Rule("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
         "Google API key"),
    Rule("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
         "Slack token"),
    Rule("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
         "GitHub token"),
    Rule("bearer_literal", re.compile(r"(?i)\bauthorization\s*[:=]\s*[\"']?(bearer|token)\s+[A-Za-z0-9._\-]{20,}"),
         "Hardcoded Authorization bearer value"),
    Rule("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
         "Private key material"),
    Rule("x_session_cookie_value", re.compile(
        r"(?i)[\"']?(?:auth_token|ct0)[\"']?\s*[:=]\s*[\"'][A-Za-z0-9%_\-]{30,}[\"']"),
        "X/Twitter session cookie value"),
    Rule("password_assignment", re.compile(
        r"(?i)\b(?:password|passwd|secret|api_key|apikey|private_key)\s*[:=]\s*[\"'][^\"'\s]{12,}[\"']"),
        "Hardcoded password/secret assignment"),
)


def _iter_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        parts = set(path.parts)
        if any(d in parts for d in SKIP_DIRS) or path.suffix in {".db", ".sqlite", ".png", ".jpg", ".ico", ".pyc"}:
            continue
        out.append(path)
    return out


def _ignored(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    return any(pat in rel for pat in IGNORE_PATTERNS)


def _is_local_secret_file(rel: str) -> bool:
    return rel.replace("\\", "/") in LOCAL_SECRET_FILES


def scan(root: Path) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for path in _iter_files(root):
        rel = str(path.relative_to(root)).replace("\\", "/")
        if _ignored(rel):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable
        local_file = _is_local_secret_file(rel)
        for lineno, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            # Skip obvious placeholders and documentation examples.
            if any(m in stripped.lower() for m in
                   ("your_", "placeholder", "example.com", "changeme", "xxx", "<redacted",
                    "not-a-real", "fake", "todo", "# copy to")):
                continue
            for rule in RULES:
                if rule.pattern.search(line):
                    findings.append({
                        "file": rel,
                        "line": lineno,
                        "rule": rule.name,
                        "description": rule.description,
                        "severity": "info" if local_file else "critical",
                    })
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description="Scan the repository for committed credentials.")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    ap.add_argument("--root", default=".", help="repository root (default: cwd)")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    findings = scan(root)

    critical = [f for f in findings if f["severity"] == "critical"]
    local = [f for f in findings if f["severity"] == "info"]

    if args.json:
        print(json.dumps(
            {"findings": findings, "critical": len(critical), "local_secret_files": len(local)},
            indent=2,
        ))
    else:
        if local:
            print(f"INFO: {len(local)} credential(s) in local gitignored files (expected, keep them ignored):")
            for f in local:
                print(f"    {f['file']}:{f['line']}  [{f['rule']}]")
            print()
        if critical:
            print(f"FAIL: {len(critical)} credential(s) in TRACKED source/config under {root}")
            for f in critical:
                print(f"  {f['file']}:{f['line']}  [{f['rule']}] {f['description']}")
            print("\nValues are never printed. Remove them and rotate the credential.")
        else:
            print(f"PASS: no credentials in tracked source under {root}")

    return 1 if critical else 0


if __name__ == "__main__":
    sys.exit(main())