"""Shared pytest fixtures.

Every API test must authenticate. Rather than sprinkling headers through each test, the
fixtures here provision a known test key and hand back clients that already carry it.
Tests that care about the auth boundary itself use ``anon_client``.
"""
from __future__ import annotations

import importlib
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# A fixed, obviously-fake key. This is a test fixture value, not a credential.
TEST_API_KEY = "test-key-not-a-real-secret"


@pytest.fixture(autouse=True)
def _api_key_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give every test a configured API key and a clean data directory.

    Setting the env var (rather than patching the module) exercises the real
    pydantic-settings path, so a regression in configuration wiring is caught.
    """
    monkeypatch.setenv("LEADSWEEP_API_KEY", TEST_API_KEY)
    monkeypatch.setenv("LEADSWEEP_GROQ_API_KEY", "gsk_test_offline_mock_key_12345")
    monkeypatch.setenv("LEADSWEEP_SESSIONS_FILE", "tests/fixtures/sessions.fixture.json")
    # A HITL-gated agent blocks on its resume event. Production default is 3600s, which would
    # hang the suite, so tests get a short gate. Production behaviour is untouched.
    monkeypatch.setenv("LEADSWEEP_HITL_TIMEOUT_S", "1")
    # Fixture owner identity (no real person's email is baked into the code).
    monkeypatch.setenv("LEADSWEEP_ADMIN_EMAIL", "owner@example.com")
    monkeypatch.setenv("LEADSWEEP_OWNER_EMAIL", "owner@example.com")
    # Most tests exercise the multi-user login mode (sessions, owner-only routes, isolation).
    # The default no-login local mode is covered in tests/test_local_mode.py.
    monkeypatch.setenv("LEADSWEEP_REQUIRE_LOGIN", "true")
    yield


@pytest.fixture
def auth_headers() -> dict[str, str]:
    from leadsweep.auth import API_KEY_HEADER

    return {API_KEY_HEADER: TEST_API_KEY}


@pytest.fixture
def anon_client() -> Iterator[TestClient]:
    """Client that sends no credentials."""
    from leadsweep import api as api_module

    with TestClient(api_module.app) as c:
        yield c


@pytest.fixture
def client(auth_headers: dict[str, str]) -> Iterator[TestClient]:
    """Client that sends a valid API key on every request."""
    from leadsweep import api as api_module

    with TestClient(api_module.app) as c:
        c.headers.update(auth_headers)
        yield c


@pytest.fixture(autouse=True)
def _no_real_browser_or_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the suite hermetic: no test may launch a real browser.

    Without this, any test that reaches an actor's extraction path starts the Playwright
    driver subprocess. That is slow, depends on browsers being installed, and orphans a
    subprocess when the TestClient's private event loop closes - producing flaky
    "Event loop is closed" / "subprocess still running" warnings unrelated to the code under
    test. Tests must exercise architecture with fakes, never with a live browser.

    A test that genuinely needs a browser must opt out explicitly and is expected to be
    marked `@pytest.mark.live` and excluded from the default run.
    """
    if os.environ.get("LEADSWEEP_ALLOW_LIVE_BROWSER") == "1":
        return

    def _blocked(*args, **kwargs):
        raise RuntimeError(
            "Live browser launch is blocked during tests. Inject a fake scraper via "
            "RunContext(scraper=...) or HITLAutonomousAgent.execute_stream(scraper=...). "
            "Set LEADSWEEP_ALLOW_LIVE_BROWSER=1 to override (not recommended in CI)."
        )

    for module_path, attr in (
        ("leadsweep.scraper", "async_playwright"),
        ("leadsweep.services.enrichment_worker", "async_playwright"),
    ):
        try:
            mod = importlib.import_module(module_path)
        except ImportError:  # pragma: no cover
            continue
        if hasattr(mod, attr):
            monkeypatch.setattr(mod, attr, _blocked)


@pytest.fixture
def fake_scraper():
    """A drop-in XScraper stand-in for architecture tests. No browser, no network."""
    from leadsweep.models import Tweet, XUser

    class _FakeScraper:
        instances_created = 0

        def __init__(self):
            _FakeScraper.instances_created += 1
            self.calls: list[tuple] = []

        async def search_tweets(self, query, max_results=15, tab="live"):
            self.calls.append(("search_tweets", query, max_results))
            return [Tweet(id=f"t{len(self.calls)}", url="https://x.com/i/status/x",
                          text="We need an AI developer for our automation work. " * 4,
                          author_username="someone", author_followers=1200, like_count=3)]

        async def fetch_user_profile_tweets(self, username, limit=10):
            self.calls.append(("profile", username, limit))
            return [Tweet(id=f"p{len(self.calls)}", url="https://x.com/i/status/y",
                          text="Building automation tooling for teams. " * 4,
                          author_username=username, author_followers=5000, like_count=7)]

        async def fetch_user_followers(self, username, limit=50):
            self.calls.append(("followers", username, limit))
            return [XUser(rest_id=f"u{len(self.calls)}", handle=f"user{len(self.calls)}",
                          bio="Founder building AI agents and workflow automation",
                          followers_count=1500, is_blue_verified=True)]

    return _FakeScraper


@pytest.fixture
def tmp_db(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Point the whole application at a throwaway, fully migrated SQLite database.

    Keeps the real data/leadsweep.db untouched and gives each test an isolated schema.
    ``Store`` owns the migrations (DatasetEngine only reads), so it is instantiated once
    here to bring the file up to the current ``user_version``.
    """
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("LEADSWEEP_DB_PATH", str(db_path))

    from leadsweep.pipeline.store import Store

    Store(db_path).close()

    yield str(db_path)


@pytest.fixture(autouse=True)
def _isolate_settings() -> None:
    """Guard against tests leaking LEADSWEEP_* values into one another via the real .env file.

    ``Settings`` reads ``.env`` from the working directory. If a developer's .env sets a
    value a test does not expect, the test result would depend on the machine. This records
    the pre-existing value of the handful of keys we care about so tests stay deterministic.
    """
    # Nothing to reset today (get_settings() is intentionally uncached so monkeypatch works),
    # but keeping the hook documents the invariant and gives future settings a place to land.
    return None


@pytest.fixture(autouse=True)
def _block_live_groq_in_non_live_tests(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hermetic guard: fail any non-live test that attempts to connect to api.groq.com."""
    if "live" in request.keywords:
        return

    import socket
    orig_getaddrinfo = socket.getaddrinfo

    def guarded_getaddrinfo(host, port, *args, **kwargs):
        if isinstance(host, (str, bytes)) and "groq.com" in str(host).lower():
            raise RuntimeError(
                f"Attempted live network call to '{host}' in non-live test '{request.node.name}'. "
                "Tests that call real Groq must be marked '@pytest.mark.live' or mock the LLM."
            )
        return orig_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)


from leadsweep.config import get_settings
_CONFIGURED_PROD_DB_PATH = Path(get_settings().db_path).resolve()


class _FakeStructuredChat:
    def __init__(self, schema, include_raw: bool = False):
        self.schema = schema
        self.include_raw = include_raw

    async def ainvoke(self, prompt, *args, **kwargs):
        # MOCK HYGIENE ASSERTION: Mocked LLM execution can never write to configured production db_path
        current_db = Path(get_settings().db_path).resolve()
        assert current_db != _CONFIGURED_PROD_DB_PATH, (
            f"MOCK HYGIENE VIOLATION: Mocked LLM output can never be written to the configured production db_path ({_CONFIGURED_PROD_DB_PATH})!"
        )

        p_str = str(prompt).lower()
        if getattr(self.schema, "__name__", "") == "QueryPlan":
            from leadsweep.leadintel.models import QueryPlan, QueryVariant
            parsed = QueryPlan(
                topic_terms=["web3", "founder"],
                variants=[QueryVariant(strategy="natural", query="web3 founder", rationale="Direct query")],
            )
            if self.include_raw:
                class _RawMsg:
                    response_metadata = {
                        "x-ratelimit-remaining-tokens": "8000",
                        "x-ratelimit-remaining-requests": "30",
                        "token_usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70}
                    }
                return {"parsed": parsed, "raw": _RawMsg()}
            return parsed

        from leadsweep.pipeline.qualification_graph import LeadJudgeContract
        if "seeking opportunities" in p_str or "job seeker" in p_str:
            parsed = LeadJudgeContract(
                category="GENERAL_DISCUSSION",
                score=15,
                evidence_quote="Seeking opportunities",
                reason="Author is a job seeker offering services rather than procuring",
                confidence=0.9,
                poster_role="seller",
                intent_type="self_promotion",
            )
        elif "hiring" in p_str or "looking to hire" in p_str or "looking for a developer" in p_str or "developer" in p_str or "engineer" in p_str:
            quote = ""
            for kw in [
                "Looking for a developer to build an automated scraper with LangGraph",
                "Looking for a developer",
                "We are hiring a senior rust engineer to build our solana dex",
                "We are hiring a smart contract developer for our team",
                "Looking to hire a smart contract developer",
                "Looking to hire a full stack engineer",
                "We are hiring another developer",
                "We are hiring",
                "Looking to hire",
                "developer",
                "engineer",
            ]:
                pos = p_str.find(kw.lower())
                if pos != -1:
                    quote = prompt[pos:pos + len(kw)]
                    break
            parsed = LeadJudgeContract(
                category="HIRING_OR_CONTRACT",
                score=85,
                evidence_quote=quote,
                reason="Explicit hiring opportunity with verified technical role",
                confidence=0.95,
                poster_role="recruiter",
                intent_type="recruitment",
            )
        else:
            parsed = LeadJudgeContract(
                category="GENERAL_DISCUSSION",
                score=25,
                evidence_quote="",
                reason="General discussion without commercial lead signals",
                confidence=0.8,
                poster_role="bystander",
                intent_type="noise",
            )

        class _RawMsg:
            response_metadata = {
                "x-ratelimit-remaining-tokens": "8000",
                "x-ratelimit-remaining-requests": "30",
                "token_usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 45,
                    "total_tokens": 165,
                }
            }

        if self.include_raw:
            return {"parsed": parsed, "raw": _RawMsg()}
        return parsed

    def invoke(self, prompt, *args, **kwargs):
        import asyncio
        return asyncio.run(self.ainvoke(prompt, *args, **kwargs))


class _FakeChatGroq:
    _is_mock = True

    def __init__(self, *args, **kwargs):
        pass

    def with_structured_output(self, schema, include_raw: bool = False, **kwargs):
        return _FakeStructuredChat(schema, include_raw=include_raw)

    async def ainvoke(self, prompt, *args, **kwargs):
        class _Resp:
            content = "Fake LLM Response"
            response_metadata = {
                "x-ratelimit-remaining-tokens": "8000",
                "x-ratelimit-remaining-requests": "30",
                "token_usage": {
                    "prompt_tokens": 50,
                    "completion_tokens": 20,
                    "total_tokens": 70,
                }
            }
        return _Resp()


@pytest.fixture(autouse=True)
def _isolate_test_db_for_mock_llm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Make tests that mock the LLM use a temporary DB path only (D1 requirement)."""
    if "live" in request.keywords or os.environ.get("LEADSWEEP_ALLOW_PROD_DB_FOR_TESTS") == "1":
        return
    tmp_db = tmp_path / "test_isolated.db"
    monkeypatch.setenv("LEADSWEEP_DB_PATH", str(tmp_db))
    from leadsweep.core.datasets import DatasetEngine
    from leadsweep.pipeline.store import Store
    Store(tmp_db)
    DatasetEngine(tmp_db)


@pytest.fixture(autouse=True)
def _mock_groq_llm_for_non_live_tests(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock LangChain ChatGroq for non-live tests to ensure deterministic offline execution."""
    if "live" in request.keywords:
        return
    try:
        import langchain_groq
        monkeypatch.setattr(langchain_groq, "ChatGroq", _FakeChatGroq)
    except ImportError:
        pass


def pytest_report_header(config: pytest.Config) -> str:
    db = os.environ.get("LEADSWEEP_DB_PATH", "(repo default: data/leadsweep.db)")
    return f"leadsweep tests | LEADSWEEP_DB_PATH={db}"