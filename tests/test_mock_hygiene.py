"""D1 & D3 Tests: Assert that mocked LLM output cannot write to prod DB and non-live tests cannot reach api.groq.com."""
from __future__ import annotations

import asyncio
from pathlib import Path
import socket
import pytest
from tests.conftest import _FakeStructuredChat, _CONFIGURED_PROD_DB_PATH


def test_mocked_llm_cannot_write_to_production_db(monkeypatch: pytest.MonkeyPatch):
    """Assert that mocked LLM execution fails closed if active DB matches the production DB path."""
    prod_path = str(_CONFIGURED_PROD_DB_PATH)
    monkeypatch.setenv("LEADSWEEP_DB_PATH", prod_path)
    monkeypatch.setenv("LEADSWEEP_ALLOW_PROD_DB_FOR_TESTS", "1")

    chat = _FakeStructuredChat(schema=None)
    with pytest.raises(AssertionError, match="MOCK HYGIENE VIOLATION"):
        asyncio.run(chat.ainvoke("We are hiring a blockchain engineer"))


def test_non_live_tests_cannot_reach_groq_network():
    """Assert that any attempt to resolve api.groq.com in non-live tests is blocked by fixture."""
    with pytest.raises(RuntimeError, match="groq.com"):
        socket.getaddrinfo("api.groq.com", 443)
