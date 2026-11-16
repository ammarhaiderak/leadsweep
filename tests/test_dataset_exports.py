"""Unit and API integration tests for Phase G: Storage & Multi-Format Exports."""
import pytest
from fastapi.testclient import TestClient

from leadsweep.api import app
from leadsweep.core.datasets import DatasetEngine
from leadsweep.core.exporter import DatasetExporter
from leadsweep.pipeline.store import Store


@pytest.fixture
def export_setup(tmp_path):
    db_file = tmp_path / "test_export.db"
    s = Store(db_file)
    s.close()
    engine = DatasetEngine(db_file)
    return engine


def test_exporter_formats():
    items = [
        {"id": "t1", "author": "karpathy", "text": "Deep learning models", "followers": 1000},
        {"id": "t2", "author": "sama", "text": "Compute and intelligence", "followers": 2000},
    ]

    # JSON
    js = DatasetExporter.to_json(items)
    assert '"karpathy"' in js

    # JSONL
    jl = DatasetExporter.to_jsonl(items)
    assert len(jl.splitlines()) == 2
    assert "t1" in jl.splitlines()[0]

    # CSV
    csv_str = DatasetExporter.to_csv(items)
    assert "author" in csv_str
    assert "karpathy" in csv_str
    assert "sama" in csv_str

    # XML
    xml_str = DatasetExporter.to_xml(items)
    assert "<item>" in xml_str
    assert "<author>karpathy</author>" in xml_str


def test_deduplication_and_vacuum(export_setup):
    engine = export_setup
    ds_id = "ds_test_dedup"

    # Insert first time -> Success (True)
    ins1 = engine.append_item(ds_id, "item_1", "tweet", {"id": "item_1", "text": "Unique AI post"}, dedup=True)
    assert ins1 is True

    # Insert duplicate -> Skipped (False)
    ins2 = engine.append_item(ds_id, "item_1", "tweet", {"id": "item_1", "text": "Duplicate AI post"}, dedup=True)
    assert ins2 is False

    # Check total items in dataset is exactly 1
    items = engine.get_dataset_items(ds_id)
    assert len(items) == 1

    # Database vacuum executes without error
    engine.vacuum_database()


def test_dataset_api_export_and_search(auth_headers, tmp_db):
    client = TestClient(app, headers=auth_headers)

    # Populate item into dataset via engine (tmp_db keeps the real repo DB untouched)
    from leadsweep.config import get_settings
    engine = DatasetEngine(get_settings().db_path)
    test_ds = "ds_api_test_export"
    engine.append_item(test_ds, "tw_api_1", "tweet", {"id": "tw_api_1", "text": "Autonomous Agent framework in Python"})

    # Test GET items
    res_items = client.get(f"/api/datasets/{test_ds}/items")
    assert res_items.status_code == 200
    assert len(res_items.json()) >= 1

    # Test GET export json
    res_json = client.get(f"/api/datasets/{test_ds}/export?format=json")
    assert res_json.status_code == 200
    assert "Autonomous Agent" in res_json.text

    # Test GET export csv
    res_csv = client.get(f"/api/datasets/{test_ds}/export?format=csv")
    assert res_csv.status_code == 200
    assert "text" in res_csv.text

    # Test FTS5 search endpoint
    res_search = client.get(f"/api/datasets/{test_ds}/search?q=Autonomous")
    assert res_search.status_code == 200
    assert len(res_search.json()) >= 1
