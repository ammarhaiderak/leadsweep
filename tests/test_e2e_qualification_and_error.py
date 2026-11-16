# NEW FEATURE: End-to-End Integration Tests for Qualification and Error Handling (M2-d)
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport

import scripts._mock_guard  # noqa: F401

from leadsweep.api import app
from leadsweep.models import Tweet
from leadsweep.pipeline.qualification_graph import LeadJudgeContract


@pytest.mark.asyncio
async def test_e2e_mocked_groq_qualification():
    """
    M2-d Test 1:
    POST /v1/scrape -> worker runs -> mocked Groq scores row ->
    GET /v1/data/{run_id} returns leadScore, leadCategory, leadReason, evidenceSpans, and evaluator='llm'.
    """
    mock_judge = LeadJudgeContract(
        category="HIRING_OR_CONTRACT",
        score=88,
        evidence_quote="hiring senior rust engineer",
        reason="Verified active job vacancy with contact details",
        confidence=0.95,
        poster_role="recruiter",
        intent_type="recruitment"
    )

    mock_chat = MagicMock()
    mock_chat.ainvoke = AsyncMock(return_value={"parsed": mock_judge, "raw": MagicMock(content="")})

    sample_tweet = Tweet(
        id="tw_test_1001",
        author_username="crypto_jobs",
        author_name="Crypto Jobs Board",
        author_followers=2500,
        text="We are hiring senior rust engineer for high throughput DEX. DM portfolio.",
        created_at="2026-10-17T00:00:00Z",
        url="https://x.com/crypto_jobs/status/tw_test_1001",
    )

    async def mock_actor_run(*args, **kwargs):
        yield sample_tweet

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("langchain_groq.ChatGroq.with_structured_output", return_value=mock_chat), \
             patch("leadsweep.actors.search.SearchActor.run", side_effect=mock_actor_run):
            # 1. Trigger scrape
            scrape_payload = {
                "type": "search",
                "query": "hiring rust engineer",
                "max_items": 1,
                "platform": "twitter",
                "user_email": "owner@example.com"
            }
            resp = await client.post("/v1/scrape", json=scrape_payload)
            assert resp.status_code in (200, 201), resp.text
            run_data = resp.json()
            run_id = run_data["id"]

            # Wait for worker job to complete
            import asyncio
            for _ in range(30):
                r_run = await client.get(f"/v1/jobs/{run_id}")
                if r_run.status_code == 200:
                    s = r_run.json().get("status")
                    if s in ("completed", "succeeded", "failed", "partial"):
                        break
                await asyncio.sleep(0.5)

            # 2. Query GET /v1/data/{run_id}
            data_resp = await client.get(f"/v1/data/{run_id}")
            assert data_resp.status_code == 200, data_resp.text
            items = data_resp.json()
            assert len(items) >= 1

            item = items[0]
            assert item.get("leadScore") is not None
            assert item.get("leadCategory") == "HIRING_OR_CONTRACT"
            assert item.get("leadReason") == "Verified active job vacancy with contact details"
            assert "evidenceSpans" in item
            assert item.get("evaluator") == "llm"


@pytest.mark.asyncio
async def test_e2e_scoring_write_exception_marks_job_partial_or_failed():
    """
    M2-d Test 2:
    A scoring-write / persistence exception must mark the job PARTIAL or FAILED,
    never 'completed'/'succeeded' with swallowed errors.
    """
    sample_tweet = Tweet(
        id="tw_test_1002",
        author_username="test_author",
        author_name="Test Author",
        author_followers=100,
        text="Need a developer immediately for web scraping script",
        created_at="2026-10-17T00:00:00Z",
        url="https://x.com/test_author/status/tw_test_1002",
    )

    async def mock_actor_run(*args, **kwargs):
        yield sample_tweet

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("leadsweep.pipeline.qualification_graph.lead_qualification_pipeline.ainvoke", side_effect=RuntimeError("Simulated LLM database crash")), \
             patch("leadsweep.actors.search.SearchActor.run", side_effect=mock_actor_run):
            scrape_payload = {
                "type": "search",
                "query": "test error handling",
                "max_items": 1,
                "platform": "twitter",
                "user_email": "owner@example.com"
            }
            resp = await client.post("/v1/scrape", json=scrape_payload)
            assert resp.status_code in (200, 201), resp.text
            run_id = resp.json()["id"]

            import asyncio
            for _ in range(30):
                r_run = await client.get(f"/v1/jobs/{run_id}")
                if r_run.status_code == 200:
                    s = r_run.json().get("status")
                    if s in ("completed", "succeeded", "failed", "partial"):
                        break
                await asyncio.sleep(0.5)

            r_run = await client.get(f"/v1/jobs/{run_id}")
            assert r_run.status_code == 200
            run_info = r_run.json()
            # Must be marked failed or partial, NOT succeeded/completed
            assert run_info.get("status") in ("failed", "partial")
            err_msg = run_info.get("error_detail") or ""
            assert any(term in err_msg for term in ("Scoring/persistence failed", "AI evaluation unavailable", "Scoring error"))
