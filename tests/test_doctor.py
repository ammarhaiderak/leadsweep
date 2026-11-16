from scripts.doctor import REQUIRED, pkg_name, status, sync_requirements


def test_status_cases():
    assert status("mcp>=1.10,<2", None) == "missing"
    assert status("mcp>=1.10,<2", "1.30.0") == "ok"
    assert status("mcp>=1.10,<2", "2.0.1").startswith("wrong version")


def test_pkg_name():
    assert [pkg_name(s) for s in ["mcp>=1.10,<2", "langchain-core>=1.0,<2", "pytest>=8.0"]] == ["mcp", "langchain-core", "pytest"]


def test_sync_requirements_appends_only_missing(tmp_path):
    f = tmp_path / "requirements.txt"
    f.write_text("playwright>=1.47\npydantic>=2.7")  # old file, no trailing newline
    added = sync_requirements(f)
    lines = f.read_text().splitlines()
    assert "langgraph>=1.0,<2" in added and "playwright>=1.47" in lines and len(lines) == len(REQUIRED)
    assert sync_requirements(f) == []  # idempotent
