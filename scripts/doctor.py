"""Environment doctor: checks Python, required packages, project files. Fixes packages with --install.
Run:  python -m scripts.doctor            (diagnose)
      python -m scripts.doctor --install  (pip-install anything missing/outdated + sync requirements.txt)"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

REQUIRED = [
    "playwright>=1.47", "pydantic>=2.7", "pydantic-settings>=2.3", "pytest>=8.0",
    "mcp>=1.10,<2", "langgraph>=1.0,<2", "langchain-core>=1.0,<2", "langchain-ollama>=1.0,<2",
]


def pkg_name(spec: str) -> str:
    return re.split(r"[<>=!~ ]", spec, maxsplit=1)[0]


def installed_version(spec: str) -> str | None:
    try:
        return metadata.version(pkg_name(spec))
    except metadata.PackageNotFoundError:
        return None


def status(spec: str, installed: str | None) -> str:
    """'ok' | 'missing' | 'wrong version (x)'"""
    if installed is None:
        return "missing"
    try:
        from packaging.requirements import Requirement
    except ImportError:
        return "ok"
    return "ok" if Requirement(spec).specifier.contains(installed, prereleases=True) else f"wrong version ({installed})"


def report() -> list[str]:
    bad: list[str] = []
    for spec in REQUIRED:
        st = status(spec, installed_version(spec))
        print(f"  {'OK     ' if st == 'ok' else 'PROBLEM'} {spec:<22} {st if st != 'ok' else installed_version(spec)}")
        if st != "ok":
            bad.append(spec)
    return bad


def sync_requirements(path: Path = Path("requirements.txt")) -> list[str]:
    have = {pkg_name(l.strip()).lower() for l in path.read_text().splitlines() if l.strip()} if path.exists() else set()
    add = [s for s in REQUIRED if pkg_name(s).lower() not in have]
    if add:
        with path.open("a", encoding="utf-8") as f:
            f.write(("\n" if path.exists() and not path.read_text().endswith("\n") else "") + "\n".join(add) + "\n")
    return add


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", action="store_true")
    args = ap.parse_args()

    print(f"Python {sys.version.split()[0]} | env: {sys.prefix}")
    problems = 0
    if sys.version_info < (3, 11):
        print("  PROBLEM Python >= 3.11 required (tomllib)")
        problems += 1
    print("Packages:")
    bad = report()
    if bad and args.install:
        print(f"\nInstalling: {bad}")
        if subprocess.call([sys.executable, "-m", "pip", "install", *bad]) != 0:
            print("pip failed - see output above")
            return 1
        added = sync_requirements()
        if added:
            print(f"requirements.txt was outdated; appended: {added}")
        print("\nRe-checking:")
        bad = report()
    problems += len(bad)

    print("Project files:")
    for f, hint in [("config/queries.toml", "missing - unzip the latest leadsweep-full zip"),
                    ("sessions.json", "missing - run: python -m scripts.capture_session --id acct-1")]:
        ok = Path(f).exists()
        print(f"  {'OK     ' if ok else 'PROBLEM'} {f}{'' if ok else '  -> ' + hint}")
        problems += 0 if ok else 1
    homes = [Path.home() / ".cache" / "ms-playwright", Path.home() / "Library" / "Caches" / "ms-playwright",
             Path.home() / "AppData" / "Local" / "ms-playwright"]
    if not any(h.exists() and any(h.glob("chromium*")) for h in homes):
        print("  WARN    Playwright Chromium not found -> run: playwright install chromium")

    if problems:
        print(f"\n{problems} problem(s)." + ("" if args.install else "  Fix packages automatically with: python -m scripts.doctor --install"))
        return 1
    print("\nEnvironment OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
