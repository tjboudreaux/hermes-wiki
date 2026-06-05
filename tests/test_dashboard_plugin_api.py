"""Dashboard plugin API contract tests."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

from fixtures import build_populated_home


def _load_plugin_api() -> Any:
    path = Path(__file__).resolve().parents[1] / "dashboard" / "plugin_api.py"
    spec = importlib.util.spec_from_file_location("hermes_wiki_dashboard_plugin_api", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def plugin_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    home = tmp_path / "home"
    build_populated_home(home)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_PROFILE", "test-profile")
    return _load_plugin_api()


def test_wikis_endpoint_excludes_archived_and_private(plugin_api: Any) -> None:
    rows = plugin_api.list_wikis()

    assert [row["slug"] for row in rows] == ["ai-tooling"]
    assert rows[0]["domain"] == "AI agents, coding tools, and research workflows"
    assert {"slug", "domain", "page_count", "health_score", "last_ingest"} <= set(rows[0])


def test_wiki_subroutes_deny_invisible_and_archived_without_disclosure(plugin_api: Any) -> None:
    for slug in ("private-lab", "ungodly-economy"):
        with pytest.raises(HTTPException) as summary_exc:
            plugin_api.get_wiki(slug)
        assert summary_exc.value.status_code == 404
        assert summary_exc.value.detail == "not found or not visible"

        with pytest.raises(HTTPException) as pages_exc:
            plugin_api.list_pages(slug)
        assert pages_exc.value.status_code == 404
        assert pages_exc.value.detail == "not found or not visible"

        with pytest.raises(HTTPException) as search_exc:
            plugin_api.search(slug, q="memory")
        assert search_exc.value.status_code == 404
        assert search_exc.value.detail == "not found or not visible"


def test_pages_page_search_inbox_health_and_log_shapes(plugin_api: Any) -> None:
    pages = plugin_api.list_pages("ai-tooling", page_type="concept", tag="memory")
    assert pages["pagination"]["total"] >= 1
    assert all(item["type"] == "concept" for item in pages["items"])
    assert all("memory" in item["tags"] for item in pages["items"])

    page = plugin_api.get_page("ai-tooling", "concepts/agent-memory")
    assert page["id"] == "concepts/agent-memory"
    assert page["markdown"] == page["body"]
    assert page["frontmatter"]["id"] == "concepts/agent-memory"
    assert isinstance(page["inbound_links"], int)
    assert isinstance(page["outbound_links"], list)
    assert isinstance(page["kanban_refs"], list)
    assert isinstance(page["history"], list)

    results = plugin_api.search("ai-tooling", q="memory")
    assert results["query"] == "memory"
    assert results["results"]
    assert {"id", "title", "score", "rank"} <= set(results["results"][0])

    inbox = plugin_api.get_inbox("ai-tooling")
    assert inbox
    assert {"filename", "classifier", "status"} <= set(inbox[0])

    health = plugin_api.get_health("ai-tooling")
    assert {"findings", "summary", "health_score"} <= set(health)
    assert all({"check", "severity", "message"} <= set(finding) for finding in health["findings"])

    log = plugin_api.get_log("ai-tooling", kind="agent")
    assert log["items"]
    assert log["pagination"]["total"] >= len(log["items"])
    assert all(item["author_kind"] == "agent" for item in log["items"])


def test_create_archive_ingest_and_delete_are_non_destructive(
    plugin_api: Any,
    tmp_path: Path,
) -> None:
    created = asyncio.run(
        plugin_api.create_wiki(plugin_api.CreateWikiRequest(slug="dashboard-created", domain="UI"))
    )
    assert created["slug"] == "dashboard-created"
    assert any(row["slug"] == "dashboard-created" for row in plugin_api.list_wikis())

    source = tmp_path / "source.md"
    source.write_text(
        "# Dashboard Source\n\nHermes dashboard source about agent memory.",
        encoding="utf-8",
    )
    ingested = asyncio.run(
        plugin_api.ingest(
            "dashboard-created",
            plugin_api.IngestRequest(path_or_url=str(source)),
        )
    )
    assert ingested["status"] == "ok"
    assert ingested["result"]["pages_created"]

    archived = asyncio.run(plugin_api.archive_wiki("dashboard-created"))
    assert archived["archived"] is True
    assert not any(row["slug"] == "dashboard-created" for row in plugin_api.list_wikis())

    wiki_dir = Path(created["path"])
    refused = asyncio.run(plugin_api.delete_wiki("dashboard-created", confirm=False))
    assert refused["status"] == "refused"
    assert wiki_dir.is_dir()
