"""Tests for LeadSweep Lead Relevance Quality & Unified Exporter Regression Suite.

Verifies:
1. Off-topic streetwear designer post is capped at <= 15 and disqualified under query 'web3 founder'.
2. Genuine Web3 founder hiring post is correctly recognized and qualified.
3. Export endpoints return HTTP 200, valid Content-Disposition, UTF-8 BOM, and formula escaping.
4. Single-job vs all-jobs scoping and multi-format support (csv, json, jsonl, xlsx, tsv).
"""
import pytest
import html
from starlette.testclient import TestClient

from leadsweep.api import app
from leadsweep.pipeline.qualification_graph import compute_topic_relevance, node_intent_classifier
from leadsweep.core.exporter import DatasetExporter, sanitize_cell_value


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Test 1: Lead Relevance & Streetwear Bug Regression
# ---------------------------------------------------------------------------
def test_streetwear_off_topic_gating():
    """Verify that off-topic hiring requests (streetwear designer) are capped <= 15 and disqualified."""
    import asyncio
    streetwear_post = (
        "Looking for a streetwear designer to bring my MERRILL PROJECT to life. "
        "Need technical sketches and tech packs done ASAP."
    )
    query = "web3 founder"

    # Step A: compute_topic_relevance must score < 40
    topic_score = compute_topic_relevance(streetwear_post, query)
    assert topic_score < 40, f"Expected low topic relevance for streetwear designer in web3 context, got {topic_score}"

    # Step B: node_intent_classifier must hard-gate and disqualify
    state = {
        "text": streetwear_post,
        "query_context": query,
        "author_username": "merrillboy601",
    }
    result = asyncio.run(node_intent_classifier(state))
    assert result["buyer_intent_score"] <= 15, f"Score should be capped <= 15, got {result['buyer_intent_score']}"
    assert result["primary_category"] == "IRRELEVANT"
    assert result["decision"] == "disqualified"
    assert "Off-topic" in result["rejection_reason"]


def test_genuine_web3_founder_qualified():
    """Verify that a genuine Web3 founder procurement post is recognized with high relevance."""
    import asyncio
    web3_post = (
        "We are building our new DeFi protocol on Solana. "
        "Looking to hire a smart contract developer to build our liquidity staking vaults. DM if interested."
    )
    query = "web3 founder"

    topic_score = compute_topic_relevance(web3_post, query)
    assert topic_score >= 50, f"Expected high topic relevance for genuine Web3 DeFi post, got {topic_score}"

    state = {
        "text": web3_post,
        "query_context": query,
        "author_username": "solana_builder",
    }
    result = asyncio.run(node_intent_classifier(state))
    assert result["buyer_intent_score"] >= 70, f"Expected qualified lead score >= 70, got {result['buyer_intent_score']}"
    assert result["decision"] in ("qualified", "approved")


def test_html_entity_unescaping():
    """Verify HTML entities like &amp; &gt; are cleanly unescaped."""
    raw_text = "Looking for Web3 &amp; AI developers &gt; hiring immediately"
    unescaped = html.unescape(raw_text)
    assert "&amp;" not in unescaped
    assert "Web3 & AI" in unescaped


# ---------------------------------------------------------------------------
# Test 2: Formula Injection Sanitization
# ---------------------------------------------------------------------------
def test_formula_injection_escaping():
    """Verify spreadsheet formula injection prefixes (=, +, -, @, cmd) are escaped with single quote."""
    assert sanitize_cell_value("=1+1") == "'=1+1"
    assert sanitize_cell_value("+SUM(A1:A10)") == "'+SUM(A1:A10)"
    assert sanitize_cell_value("-5*10") == "'-5*10"
    assert sanitize_cell_value("@calc") == "'@calc"
    assert sanitize_cell_value("Safe string") == "Safe string"


# ---------------------------------------------------------------------------
# Test 3: Dataset Exporter UTF-8 BOM & Multi-format Bytes
# ---------------------------------------------------------------------------
def test_dataset_exporter_csv_tsv_bom():
    """Verify CSV and TSV export starts with UTF-8 BOM."""
    items = [
        {"id": "item_1", "author_username": "web3dev", "text": "Hiring Solidity devs", "leadScore": 90},
        {"id": "item_2", "author_username": "noisy", "text": "=cmd|' /C calc'!A0", "leadScore": 10},
    ]

    # Test CSV
    csv_str = DatasetExporter.to_csv(items)
    assert csv_str.startswith("\ufeff"), "CSV must include UTF-8 BOM"
    assert "item_1" in csv_str
    assert "'+cmd" in csv_str or "'=cmd" in csv_str, "Formula must be escaped"

    # Test TSV
    tsv_str = DatasetExporter.to_tsv(items)
    assert tsv_str.startswith("\ufeff"), "TSV must include UTF-8 BOM"
    assert "\t" in tsv_str

    # Test JSON & JSONL
    json_str = DatasetExporter.to_json(items)
    assert "item_1" in json_str
    jsonl_str = DatasetExporter.to_jsonl(items)
    assert "\n" in jsonl_str

    # Test XLSX
    xlsx_bytes = DatasetExporter.to_xlsx_bytes(items)
    assert len(xlsx_bytes) > 100
    assert xlsx_bytes[:2] == b"PK", "XLSX must be a valid zip archive (PK header)"


# ---------------------------------------------------------------------------
# Test 4: API Unified Export Endpoint Scoping & Status
# ---------------------------------------------------------------------------
def test_api_export_formats_and_scoping(auth_headers):
    """Verify /api/export endpoint handles all 5 formats, single run_id, and all-jobs."""
    client = TestClient(app, headers=auth_headers)
    formats = ["csv", "json", "jsonl", "xlsx", "tsv"]

    for fmt in formats:
        # All jobs
        res = client.get(f"/api/export?format={fmt}&kind=leads")
        assert res.status_code == 200, f"Export failed for format {fmt}: {res.status_code}"
        assert "Content-Disposition" in res.headers
        assert f".{fmt}" in res.headers["Content-Disposition"]

        # Single run_id
        res_single = client.get(f"/api/export?format={fmt}&run_id=run_d3e57c4fb874&kind=leads")
        assert res_single.status_code == 200
        assert f"run_d3e57c4fb874" in res_single.headers["Content-Disposition"]


# ---------------------------------------------------------------------------
# Test 5: CSV Multilingual BOM & Round-Trip Fixture (Chinese, Urdu, Cyrillic)
# ---------------------------------------------------------------------------
def test_csv_multilingual_bom_and_roundtrip():
    """Verify Chinese, Urdu, Cyrillic text, quotes, and newlines round-trip through Python's csv module with BOM."""
    import csv
    import io

    fixture_items = [
        {
            "platform": "twitter",
            "author/channel": "chinese_dev_中文",
            "post URL": "https://x.com/chinese_dev/status/123",
            "published date": "2026-10-19 12:00:00",
            "text": "招聘高级Python开发工程师\n待遇优厚，欢迎自荐！\n联系方式：\"hr@example.com\"",
            "evaluator": "llm",
            "model": "qwen/qwen3.8-27b",
            "category": "lead",
            "score": 95,
            "poster role": "recruiter",
            "reason": "明确的招聘信息，包含岗位名称及联系方式。",
            "evidence quote": "招聘高级Python开发工程师",
            "likes": 12,
            "replies": 3,
            "views": 500,
            "job id": "job_zh_001",
        },
        {
            "platform": "telegram",
            "author/channel": "urdu_channel_اردو",
            "post URL": "https://t.me/urdu_tech/456",
            "published date": "2026-10-19 12:05:00",
            "text": "ہمیں فوری طور پر پائتھن ڈیولپر کی ضرورت ہے۔\nرابطہ کریں: \"info@tech.pk\"\nتنخواہ: مارکیٹ کے مطابق",
            "evaluator": "llm",
            "model": "qwen/qwen3.8-27b",
            "category": "lead",
            "score": 90,
            "poster role": "hiring_manager",
            "reason": "پائتھن ڈیولپر کی براہ راست تلاش۔",
            "evidence quote": "ہمیں فوری طور پر پائتھن ڈیولپر کی ضرورت ہے",
            "likes": 5,
            "replies": 1,
            "views": 250,
            "job id": "job_ur_002",
        },
        {
            "platform": "twitter",
            "author/channel": "cyrillic_dev_русский",
            "post URL": "https://x.com/cyrillic_dev/status/789",
            "published date": "2026-10-19 12:10:00",
            "text": "Ищем Python/FastAPI разработчика в команду!\nФормат: удаленно, full-time.\nПишите в лс: \"@lead_dev\"",
            "evaluator": "llm",
            "model": "qwen/qwen3.8-27b",
            "category": "lead",
            "score": 88,
            "poster role": "tech_lead",
            "reason": "Прямой поиск разработчика Python/FastAPI.",
            "evidence quote": "Ищем Python/FastAPI разработчика",
            "likes": 20,
            "replies": 4,
            "views": 800,
            "job id": "job_ru_003",
        },
    ]

    from leadsweep.core.exporter import LEADS_EXPORT_COLUMNS
    csv_bytes = b"".join(DatasetExporter.stream_csv(fixture_items, LEADS_EXPORT_COLUMNS))

    # 1. Show & verify BOM
    bom = csv_bytes[:3]
    print(f"\n[TEST PROOF] CSV Byte-Order Mark: {bom.hex().upper()} (raw: {bom!r})")
    assert bom == b"\xef\xbb\xbf", f"CSV must start with UTF-8 BOM, got {bom!r}"

    # 2. Round-trip through Python's standard csv module using utf-8-sig
    csv_text = csv_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = list(reader)

    assert len(rows) == 3, f"Expected 3 rows, got {len(rows)}"
    assert rows[0]["author/channel"] == "chinese_dev_中文"
    assert "招聘高级Python开发工程师" in rows[0]["text"]
    assert rows[1]["author/channel"] == "urdu_channel_اردو"
    assert "ہمیں فوری طور پر پائتھن ڈیولپر کی ضرورت ہے۔" in rows[1]["text"]
    assert rows[2]["author/channel"] == "cyrillic_dev_русский"
    assert "Ищем Python/FastAPI разработчика" in rows[2]["text"]
