"""Dashboard plugin API contract tests."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException

from fixtures import build_populated_home
from hermes_wiki.attribution import append_log_entry


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


def test_wikis_route_mounts_and_returns_empty_for_fresh_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "empty-home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_PROFILE", "test-profile")
    monkeypatch.delenv("HERMES_WIKI", raising=False)

    plugin_api = _load_plugin_api()
    registry = home / "wikis" / "wikis.db"
    assert not registry.exists(), "plugin import must not touch home state"

    app = FastAPI()
    app.include_router(plugin_api.router, prefix="/api/plugins/wiki")
    assert "/api/plugins/wiki/wikis" in {getattr(route, "path", "") for route in app.routes}

    assert plugin_api.list_wikis() == []
    assert registry.is_file()


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
    assert any(link["id"] == "entities/hermes" for link in page["outbound_pages"])
    assert any(
        link["id"] == "sources/2026-06-05-agent-memory-article"
        for link in page["inbound_pages"]
    )
    assert isinstance(page["kanban_refs"], list)
    assert any(
        ref["task_id"] == "KB-123"
        and ref["task_title"] == "Review agent memory dashboard linkage"
        for ref in page["kanban_refs"]
    )
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


def test_filter_facets_return_unique_values_without_row_payload(plugin_api: Any) -> None:
    page_facets = plugin_api.get_page_facets("ai-tooling")

    assert page_facets["wiki"] == "ai-tooling"
    assert "concept" in page_facets["types"]
    assert "memory" in page_facets["tags"]
    assert "items" not in page_facets
    assert "pagination" not in page_facets

    log_facets = plugin_api.get_log_facets("ai-tooling")

    assert log_facets["wiki"] == "ai-tooling"
    assert "agent" in log_facets["kinds"]
    assert log_facets["authors"]
    assert "items" not in log_facets
    assert "pagination" not in log_facets


def test_page_inbound_pages_use_projection_without_scanning_page_files(
    plugin_api: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_read_markdown = plugin_api.read_markdown

    def read_only_requested_page(path: Path) -> tuple[dict[str, Any], str]:
        if path.as_posix().endswith("concepts/agent-memory.md"):
            return real_read_markdown(path)
        raise AssertionError(f"unexpected inbound candidate file read: {path}")

    monkeypatch.setattr(plugin_api, "read_markdown", read_only_requested_page)

    page = plugin_api.get_page("ai-tooling", "concepts/agent-memory")

    assert any(
        link["id"] == "sources/2026-06-05-agent-memory-article"
        for link in page["inbound_pages"]
    )


def test_health_report_exposes_all_severities_for_dashboard_filters(plugin_api: Any) -> None:
    health = plugin_api.get_health("ai-tooling")

    severities = {finding["severity"] for finding in health["findings"]}

    assert {"high", "medium", "low"} <= severities
    assert health["summary"]["high"] >= 1
    assert health["summary"]["medium"] >= 1
    assert health["summary"]["low"] >= 1


def test_log_filters_combine_and_paginate(plugin_api: Any) -> None:
    wiki_root = Path(plugin_api.get_wiki("ai-tooling")["path"])
    append_log_entry(
        wiki_root,
        timestamp="2026-06-05T03:00:00Z",
        action="create-page",
        target="concepts/agent-a",
        author="claude-dashboard",
        author_kind="agent",
        details="agent row one",
    )
    append_log_entry(
        wiki_root,
        timestamp="2026-06-05T03:01:00Z",
        action="edit",
        target="concepts/agent-b",
        author="claude-dashboard",
        author_kind="agent",
        details="agent row two",
    )
    append_log_entry(
        wiki_root,
        timestamp="2026-06-05T03:02:00Z",
        action="edit",
        target="concepts/human",
        author="claude-dashboard",
        author_kind="human",
        details="same author different kind",
    )

    first = plugin_api.get_log(
        "ai-tooling",
        page=1,
        page_size=1,
        author="claude-dashboard",
        kind="agent",
    )
    second = plugin_api.get_log(
        "ai-tooling",
        page=2,
        page_size=1,
        author="claude-dashboard",
        kind="agent",
    )

    assert first["pagination"]["total"] == 2
    assert first["pagination"]["has_next"] is True
    assert first["items"][0]["target"] == "concepts/agent-a"
    assert second["pagination"]["has_previous"] is True
    assert second["items"][0]["target"] == "concepts/agent-b"
    assert all(item["author"] == "claude-dashboard" for item in first["items"] + second["items"])
    assert all(item["author_kind"] == "agent" for item in first["items"] + second["items"])


def test_global_and_scoped_search_rank_visibility_and_click_payload(
    plugin_api: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hermes_wiki.tools import wiki_create_page

    monkeypatch.setenv("HERMES_WIKI", "ai-tooling")
    dense = wiki_create_page(
        title="Dense Rank Beacon",
        body="# Dense Rank Beacon\n\nrankbeacon rankbeacon rankbeacon rankbeacon rankbeacon.",
        type="concept",
        tags=["memory"],
        sources=[],
    )
    assert isinstance(dense, dict)

    asyncio.run(
        plugin_api.create_wiki(
            plugin_api.CreateWikiRequest(slug="second-visible", domain="Search test wiki")
        )
    )
    monkeypatch.setenv("HERMES_WIKI", "second-visible")
    sparse = wiki_create_page(
        title="Sparse Rank Beacon",
        body="# Sparse Rank Beacon\n\nrankbeacon.",
        type="concept",
        tags=["memory"],
        sources=[],
    )
    assert isinstance(sparse, dict)

    global_results = plugin_api.global_search(q="rankbeacon", limit=10)
    assert global_results["query"] == "rankbeacon"
    assert {row["wiki"] for row in global_results["results"]} >= {
        "ai-tooling",
        "second-visible",
    }
    assert global_results["results"][0]["id"] == dense["id"]
    assert {
        "wiki",
        "id",
        "title",
        "rank",
        "score",
        "href",
    } <= set(global_results["results"][0])
    assert "private-lab" not in json.dumps(global_results)
    assert "ungodly-economy" not in json.dumps(global_results)

    scoped = plugin_api.search("second-visible", q="rankbeacon", limit=10)
    assert scoped["results"]
    assert {row["wiki"] for row in scoped["results"]} == {"second-visible"}

    empty = plugin_api.global_search(q="no-such-dashboard-term", limit=10)
    assert empty["results"] == []


def test_inbox_reclassify_override_persists(
    plugin_api: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = plugin_api.get_inbox("ai-tooling")
    unknown = next(row for row in before if row["filename"] == "unknown-sample.dat")
    assert unknown["classifier"] == "unknown"
    monkeypatch.setenv("HERMES_WIKI", "ai-tooling")

    updated = plugin_api.reclassify_inbox_item(
        "ai-tooling",
        "unknown-sample.dat",
        plugin_api.InboxClassifyRequest(classifier="article"),
    )

    assert updated["filename"] == "unknown-sample.dat"
    assert updated["classifier"] == "article"
    assert updated["status"] == "override"

    after = plugin_api.get_inbox("ai-tooling")
    overridden = next(row for row in after if row["filename"] == "unknown-sample.dat")
    assert overridden["classifier"] == "article"
    assert overridden["status"] == "override"

    status_path = Path(plugin_api.get_wiki("ai-tooling")["path"]) / "raw" / "inbox_status.json"
    statuses = json.loads(status_path.read_text(encoding="utf-8"))
    assert statuses["unknown-sample.dat"]["classified_as"] == "article"
    assert statuses["unknown-sample.dat"]["status"] == "override"

    oversized = next(row for row in after if row["filename"] == "oversized-sample.bin")
    assert oversized["status"] == "oversized"


def test_create_archive_ingest_and_delete_are_non_destructive(
    plugin_api: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = asyncio.run(
        plugin_api.create_wiki(plugin_api.CreateWikiRequest(slug="dashboard-created", domain="UI"))
    )
    assert created["slug"] == "dashboard-created"
    assert any(row["slug"] == "dashboard-created" for row in plugin_api.list_wikis())
    monkeypatch.setenv("HERMES_WIKI", "dashboard-created")

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


def test_dashboard_existing_wiki_mutations_require_write_grant(
    plugin_api: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hermes_wiki import db

    source = tmp_path / "dashboard-denied.md"
    source.write_text(
        "# Dashboard Denied\n\nDashboard denied mutation unique term.",
        encoding="utf-8",
    )
    wiki_root = Path(plugin_api.get_wiki("ai-tooling")["path"])
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        before = conn.execute("SELECT COUNT(*) FROM ingest_log").fetchone()[0]

    with pytest.raises(HTTPException) as denied:
        asyncio.run(
            plugin_api.ingest(
                "ai-tooling",
                plugin_api.IngestRequest(path_or_url=str(source)),
            )
        )

    assert denied.value.status_code == 403
    assert denied.value.detail == "wiki write permission denied"
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        after = conn.execute("SELECT COUNT(*) FROM ingest_log").fetchone()[0]
    assert after == before

    monkeypatch.setenv("HERMES_WIKI", "ai-tooling")
    allowed = asyncio.run(
        plugin_api.ingest(
            "ai-tooling",
            plugin_api.IngestRequest(path_or_url=str(source)),
        )
    )

    assert allowed["status"] == "ok"
    assert allowed["result"]["pages_created"]


def test_inbox_file_read_returns_content(plugin_api: Any) -> None:
    detail = plugin_api.get_inbox_file("ai-tooling", "unknown-sample.dat")

    assert detail["filename"] == "unknown-sample.dat"
    assert detail["name"] == "unknown-sample.dat"
    assert detail["path"] == "raw/inbox/unknown-sample.dat"
    assert detail["content"]
    assert detail["size_bytes"] == len(detail["content"].encode("utf-8"))
    assert detail["status"] == "not yet attempted"
    assert detail["classifier"] == "unknown"


def test_inbox_file_oversized_read_refused(plugin_api: Any) -> None:
    with pytest.raises(HTTPException) as refused:
        plugin_api.get_inbox_file("ai-tooling", "oversized-sample.bin")

    assert refused.value.status_code == 413


def test_inbox_file_non_utf8_read_refused(plugin_api: Any) -> None:
    wiki_root = Path(plugin_api.get_wiki("ai-tooling")["path"])
    binary_path = wiki_root / "raw" / "inbox" / "binary-sample.bin"
    binary_path.write_bytes(b"\xff\xfe\x00binary payload")

    with pytest.raises(HTTPException) as refused:
        plugin_api.get_inbox_file("ai-tooling", "binary-sample.bin")

    assert refused.value.status_code == 415


def test_inbox_file_write_round_trips(
    plugin_api: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERMES_WIKI", "ai-tooling")
    wiki_root = Path(plugin_api.get_wiki("ai-tooling")["path"])
    status_path = wiki_root / "raw" / "inbox_status.json"

    updated = plugin_api.update_inbox_file(
        "ai-tooling",
        "unknown-sample.dat",
        plugin_api.InboxFileUpdateRequest(content="Edited inbox body.\n"),
    )

    assert updated["filename"] == "unknown-sample.dat"
    assert updated["content"] == "Edited inbox body.\n"
    assert updated["status"] == "edited"

    reread = plugin_api.get_inbox_file("ai-tooling", "unknown-sample.dat")
    assert reread["content"] == "Edited inbox body.\n"
    on_disk = (wiki_root / "raw" / "inbox" / "unknown-sample.dat").read_text(encoding="utf-8")
    assert on_disk == "Edited inbox body.\n"

    statuses = json.loads(status_path.read_text(encoding="utf-8"))
    assert statuses["unknown-sample.dat"]["status"] == "edited"
    assert statuses["unknown-sample.dat"]["sha256"]


def test_inbox_file_delete_removes_file_and_status(
    plugin_api: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERMES_WIKI", "ai-tooling")
    wiki_root = Path(plugin_api.get_wiki("ai-tooling")["path"])
    status_path = wiki_root / "raw" / "inbox_status.json"
    plugin_api.reclassify_inbox_item(
        "ai-tooling",
        "unknown-sample.dat",
        plugin_api.InboxClassifyRequest(classifier="article"),
    )
    assert "unknown-sample.dat" in json.loads(status_path.read_text(encoding="utf-8"))

    deleted = plugin_api.delete_inbox_file_route("ai-tooling", "unknown-sample.dat")

    assert deleted["filename"] == "unknown-sample.dat"
    assert deleted["status"] == "deleted"
    assert not (wiki_root / "raw" / "inbox" / "unknown-sample.dat").exists()
    assert "unknown-sample.dat" not in json.loads(status_path.read_text(encoding="utf-8"))
    remaining = plugin_api.get_inbox("ai-tooling")
    assert all(row["filename"] != "unknown-sample.dat" for row in remaining)


def test_inbox_file_traversal_rejected(
    plugin_api: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERMES_WIKI", "ai-tooling")
    wiki_root = Path(plugin_api.get_wiki("ai-tooling")["path"])

    for hostile in ("../wiki.db", "sub/dir.txt", "/etc/passwd", "..\\escape.md", "  "):
        with pytest.raises(HTTPException) as read_exc:
            plugin_api.get_inbox_file("ai-tooling", hostile)
        assert read_exc.value.status_code == 400

        with pytest.raises(HTTPException) as write_exc:
            plugin_api.update_inbox_file(
                "ai-tooling",
                hostile,
                plugin_api.InboxFileUpdateRequest(content="overwritten"),
            )
        assert write_exc.value.status_code == 400

        with pytest.raises(HTTPException) as delete_exc:
            plugin_api.delete_inbox_file_route("ai-tooling", hostile)
        assert delete_exc.value.status_code == 400

    assert (wiki_root / "wiki.db").is_file()


def test_inbox_file_write_requires_write_grant(
    plugin_api: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HERMES_WIKI", raising=False)
    wiki_root = Path(plugin_api.get_wiki("ai-tooling")["path"])
    original = (wiki_root / "raw" / "inbox" / "unknown-sample.dat").read_bytes()

    with pytest.raises(HTTPException) as write_denied:
        plugin_api.update_inbox_file(
            "ai-tooling",
            "unknown-sample.dat",
            plugin_api.InboxFileUpdateRequest(content="denied"),
        )
    assert write_denied.value.status_code == 403
    assert write_denied.value.detail == "wiki write permission denied"

    with pytest.raises(HTTPException) as delete_denied:
        plugin_api.delete_inbox_file_route("ai-tooling", "unknown-sample.dat")
    assert delete_denied.value.status_code == 403

    assert (wiki_root / "raw" / "inbox" / "unknown-sample.dat").read_bytes() == original


def test_wiki_skills_get_returns_defaults(plugin_api: Any) -> None:
    result = plugin_api.get_wiki_skills("ai-tooling")

    assert result["wiki"] == "ai-tooling"
    assert result["skills"] == {
        "ingestion": "wiki:wiki-ingestion",
        "writing": "wiki:wiki-writing",
        "media": "wiki:wiki-media-ingestion",
    }
    assert result["defaults"]["ingestion"] == "wiki:wiki-ingestion"


def test_wiki_skills_put_round_trips(
    plugin_api: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERMES_WIKI", "ai-tooling")

    updated = plugin_api.update_wiki_skills(
        "ai-tooling",
        plugin_api.WikiSkillsUpdateRequest(ingestion="research-ingest"),
    )

    assert updated["skills"]["ingestion"] == "research-ingest"
    assert updated["skills"]["writing"] == "wiki:wiki-writing"

    reread = plugin_api.get_wiki_skills("ai-tooling")
    assert reread["skills"]["ingestion"] == "research-ingest"

    schema = Path(plugin_api.get_wiki("ai-tooling")["path"]) / "SCHEMA.md"
    assert "ingestion: research-ingest" in schema.read_text(encoding="utf-8")


def test_wiki_skills_put_updates_both_kinds(
    plugin_api: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERMES_WIKI", "ai-tooling")

    updated = plugin_api.update_wiki_skills(
        "ai-tooling",
        plugin_api.WikiSkillsUpdateRequest(
            ingestion="a-ingest", writing="b-writer", media="c-media"
        ),
    )

    assert updated["skills"] == {
        "ingestion": "a-ingest",
        "writing": "b-writer",
        "media": "c-media",
    }


def test_wiki_skills_put_requires_write_grant_and_payload(
    plugin_api: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HERMES_WIKI", raising=False)
    with pytest.raises(HTTPException) as denied:
        plugin_api.update_wiki_skills(
            "ai-tooling",
            plugin_api.WikiSkillsUpdateRequest(ingestion="denied-skill"),
        )
    assert denied.value.status_code == 403

    monkeypatch.setenv("HERMES_WIKI", "ai-tooling")
    with pytest.raises(HTTPException) as empty:
        plugin_api.update_wiki_skills("ai-tooling", plugin_api.WikiSkillsUpdateRequest())
    assert empty.value.status_code == 400

    with pytest.raises(HTTPException) as bad_name:
        plugin_api.update_wiki_skills(
            "ai-tooling",
            plugin_api.WikiSkillsUpdateRequest(ingestion="two words"),
        )
    assert bad_name.value.status_code == 400


def test_wiki_skills_invisible_wiki_hidden(plugin_api: Any) -> None:
    for slug in ("private-lab", "ungodly-economy"):
        with pytest.raises(HTTPException) as read_exc:
            plugin_api.get_wiki_skills(slug)
        assert read_exc.value.status_code == 404
        assert read_exc.value.detail == "not found or not visible"

        with pytest.raises(HTTPException) as write_exc:
            plugin_api.update_wiki_skills(
                slug,
                plugin_api.WikiSkillsUpdateRequest(ingestion="x"),
            )
        assert write_exc.value.status_code == 404


def test_inbox_file_invisible_wiki_hidden(
    plugin_api: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERMES_WIKI", "private-lab")
    for slug in ("private-lab", "ungodly-economy"):
        with pytest.raises(HTTPException) as read_exc:
            plugin_api.get_inbox_file(slug, "anything.md")
        assert read_exc.value.status_code == 404
        assert read_exc.value.detail == "not found or not visible"

        with pytest.raises(HTTPException) as write_exc:
            plugin_api.update_inbox_file(
                slug,
                "anything.md",
                plugin_api.InboxFileUpdateRequest(content="nope"),
            )
        assert write_exc.value.status_code == 404

        with pytest.raises(HTTPException) as delete_exc:
            plugin_api.delete_inbox_file_route(slug, "anything.md")
        assert delete_exc.value.status_code == 404


class _FakeUpload:
    """Minimal stand-in for a Starlette UploadFile in a multipart form."""

    def __init__(self, filename: str, content: bytes) -> None:
        self.filename = filename
        self._content = content

    async def read(self) -> bytes:
        return self._content


class _FakeMultipartRequest:
    """Minimal stand-in for a Starlette Request carrying one uploaded file."""

    def __init__(self, form: dict[str, Any]) -> None:
        self.headers = {"content-type": "multipart/form-data; boundary=x"}
        self._form = form

    async def form(self) -> dict[str, Any]:
        return self._form


def test_multipart_upload_temp_file_is_unlinked_after_ingest(
    plugin_api: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uploaded-file ingest must not leak its NamedTemporaryFile on disk."""

    monkeypatch.setenv("HERMES_WIKI", "ai-tooling")

    created_paths: list[str] = []
    real_named_temporary_file = plugin_api.tempfile.NamedTemporaryFile

    def recording_named_temporary_file(*args: Any, **kwargs: Any) -> Any:
        handle = real_named_temporary_file(*args, **kwargs)
        created_paths.append(handle.name)
        return handle

    monkeypatch.setattr(
        plugin_api.tempfile, "NamedTemporaryFile", recording_named_temporary_file
    )

    upload = _FakeUpload(
        "uploaded-note.md",
        b"# Uploaded Note\n\nDashboard-uploaded source about agent memory hygiene.",
    )
    request = _FakeMultipartRequest({"file": upload})

    result = asyncio.run(plugin_api.ingest("ai-tooling", payload=None, request=request))

    assert result["status"] == "ok"
    assert result["result"]["pages_created"]
    assert created_paths, "multipart upload should be staged through a temp file"
    for path in created_paths:
        assert not Path(path).exists(), f"upload temp file leaked: {path}"
