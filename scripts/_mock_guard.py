"""Shared Mock Guard Helper:
Must be imported BEFORE leadsweep is imported by any script that patches or fakes the LLM.

1. Automatically points LEADSWEEP_DB_PATH to a safe temporary database file before leadsweep initializes.
2. Refuses to run (raises RuntimeError) if the configured db_path equals the production database.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Resolve production DB path
REPO_ROOT = Path(__file__).resolve().parent.parent
PROD_DB_PATH = (REPO_ROOT / "data" / "leadsweep.db").resolve()

# If user/caller explicitly forced LEADSWEEP_DB_PATH to prod DB, refuse immediately
configured_env = os.environ.get("LEADSWEEP_DB_PATH")
if configured_env and Path(configured_env).resolve() == PROD_DB_PATH:
    raise RuntimeError(
        f"MOCK GUARD REFUSAL: Active LEADSWEEP_DB_PATH ({configured_env}) points to production database ({PROD_DB_PATH})!\n"
        f"Scripts that patch or fake the LLM are strictly blocked from executing against production data."
    )

# Direct to isolated temporary test DB before leadsweep is imported
MOCK_GUARD_DB = Path(tempfile.gettempdir()) / "leadsweep_mock_guard.db"
os.environ["LEADSWEEP_DB_PATH"] = str(MOCK_GUARD_DB)


def assert_not_production_db() -> None:
    """Verifies at runtime that leadsweep settings did not resolve to production DB."""
    from leadsweep.config import get_settings
    active_path = Path(get_settings().db_path).resolve()
    if active_path == PROD_DB_PATH:
        raise RuntimeError(
            f"MOCK GUARD REFUSAL: Configured database ({active_path}) is the production database!\n"
            f"Execution halted to prevent writing mocked LLM output into production."
        )


# Verify immediately upon import if leadsweep was already imported
if "leadsweep.config" in sys.modules:
    assert_not_production_db()
