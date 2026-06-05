from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from fixtures.factory import build_test_wiki


class RecordingRegistry:
    def __init__(self) -> None:
        self.registrations: dict[str, tuple[Any, Any, dict[str, Any] | None]] = {}

    def register(
        self,
        name: str,
        fn: Any,
        check_fn: Any = None,
        *,
        schema: Mapping[str, Any] | None = None,
    ) -> None:
        self.registrations[name] = (fn, check_fn, dict(schema) if schema is not None else None)


def _use_fixture_home(monkeypatch: Any, tmp_path: Path) -> Any:
    fixture = build_test_wiki(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture.home))
    monkeypatch.delenv("HERMES_WIKI", raising=False)
    return fixture


def _rows(value: Any) -> list[dict[str, Any]]:
    assert isinstance(value, list)
    return cast(list[dict[str, Any]], value)


def _mapping(value: Any) -> dict[str, Any]:
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def test_tool_sets_and_registration_gates() -> None:
    from hermes_wiki import tools

    assert tools.READ_TOOLS == {
        "wiki_list",
        "wiki_search",
        "wiki_show",
        "wiki_health_check",
        "wiki_inbox",
    }
    assert tools.WRITE_TOOLS == {"wiki_ingest", "wiki_create_page", "wiki_link_kanban"}
    assert not (tools.READ_TOOLS & tools.WRITE_TOOLS)

    registry = RecordingRegistry()
    tools.register_tools(registry)

    assert set(registry.registrations) == tools.READ_TOOLS | tools.WRITE_TOOLS
    for name in tools.READ_TOOLS:
        _fn, check_fn, schema = registry.registrations[name]
        assert check_fn is None
        assert schema is not None
    for name in tools.WRITE_TOOLS:
        _fn, check_fn, schema = registry.registrations[name]
        assert check_fn is not None
        assert schema is not None


def test_wiki_list_returns_visible_wikis_or_pages(monkeypatch: Any, tmp_path: Path) -> None:
    fixture = _use_fixture_home(monkeypatch, tmp_path)
    from hermes_wiki.tools import NOT_FOUND_OR_NOT_VISIBLE, wiki_list

    visible_wikis = _rows(wiki_list())
    visible_slugs = {row["slug"] for row in visible_wikis}
    assert fixture.primary_slug in visible_slugs
    assert fixture.archived_slug not in visible_slugs
    assert fixture.private_slug not in visible_slugs

    pages = _rows(wiki_list(wiki=fixture.primary_slug))
    assert {row["id"] for row in pages} >= set(fixture.page_ids)
    assert all(row["wiki"] == fixture.primary_slug for row in pages)

    assert wiki_list(wiki=fixture.private_slug) == NOT_FOUND_OR_NOT_VISIBLE


def test_wiki_search_scopes_visible_wikis_and_limit(monkeypatch: Any, tmp_path: Path) -> None:
    fixture = _use_fixture_home(monkeypatch, tmp_path)
    from hermes_wiki.tools import wiki_search

    results = _rows(wiki_search("agent memory"))
    assert 0 < len(results) <= 5
    assert all(row["wiki"] == fixture.primary_slug for row in results)
    assert [row["rank"] for row in results] == sorted(row["rank"] for row in results)

    limited = _rows(wiki_search("agent memory", wiki=fixture.primary_slug, limit=1))
    assert len(limited) == 1
    assert limited[0]["wiki"] == fixture.primary_slug

    assert wiki_search("agent memory", wiki=fixture.private_slug) == "not found or not visible"


def test_wiki_show_returns_body_frontmatter_and_kanban_refs(
    monkeypatch: Any, tmp_path: Path
) -> None:
    fixture = _use_fixture_home(monkeypatch, tmp_path)
    from hermes_wiki.tools import NOT_FOUND_OR_NOT_VISIBLE, wiki_show

    shown = _mapping(wiki_show("concepts/agent-memory", wiki=fixture.primary_slug))
    assert shown["wiki"] == fixture.primary_slug
    assert shown["page_id"] == "concepts/agent-memory"
    assert "Agent memory" in shown["content"]
    assert shown["frontmatter"]["id"] == "concepts/agent-memory"
    assert shown["frontmatter"]["title"] == "Agent Memory"
    assert shown["kanban_refs"] == [
        {
            "page_id": "concepts/agent-memory",
            "task_id": "KB-123",
            "direction": "page->task",
            "created": "2026-06-05T09:30:00Z",
            "task": None,
        }
    ]

    assert wiki_show("concepts/agent-memory", wiki=fixture.private_slug) == NOT_FOUND_OR_NOT_VISIBLE
    assert wiki_show("concepts/nope", wiki=fixture.primary_slug) == NOT_FOUND_OR_NOT_VISIBLE


def test_wiki_health_check_and_inbox_are_structured_reads(
    monkeypatch: Any, tmp_path: Path
) -> None:
    fixture = _use_fixture_home(monkeypatch, tmp_path)
    from hermes_wiki.tools import NOT_FOUND_OR_NOT_VISIBLE, wiki_health_check, wiki_inbox

    report = _mapping(wiki_health_check(wiki=fixture.primary_slug))
    json.dumps(report)
    assert report["wiki"] == fixture.primary_slug
    assert isinstance(report["checks"], list)
    assert all("severity" in check for check in report["checks"])

    inbox = _rows(wiki_inbox(wiki=fixture.primary_slug))
    by_name = {row["name"]: row for row in inbox}
    assert by_name["unknown-sample.dat"]["suggested_class"] == "unknown"
    assert by_name["oversized-sample.bin"]["suggested_class"] == "oversized"
    assert by_name["oversized-sample.bin"]["status"] == "oversized"

    assert wiki_health_check(wiki=fixture.private_slug) == NOT_FOUND_OR_NOT_VISIBLE
    assert wiki_inbox(wiki=fixture.private_slug) == NOT_FOUND_OR_NOT_VISIBLE


def test_write_tools_deny_without_grant_and_do_not_mutate(
    monkeypatch: Any, tmp_path: Path
) -> None:
    fixture = _use_fixture_home(monkeypatch, tmp_path)
    from hermes_wiki import db
    from hermes_wiki.tools import WRITE_PERMISSION_DENIED, wiki_create_page, wiki_ingest

    page_path = fixture.primary_wiki_root / "concepts/denied.md"
    with db.connect_wiki(fixture.primary_wiki_db) as conn:
        before_ingest_rows = conn.execute("SELECT COUNT(*) FROM ingest_log").fetchone()[0]

    assert (
        wiki_create_page(
            title="Denied",
            body="Should not be written",
            type="concept",
            tags=[],
            sources=[],
            wiki=fixture.primary_slug,
        )
        == WRITE_PERMISSION_DENIED
    )
    assert not page_path.exists()

    assert (
        wiki_ingest(
            path_or_url=str(fixture.inbox_paths["unknown"]),
            wiki=fixture.primary_slug,
        )
        == WRITE_PERMISSION_DENIED
    )
    with db.connect_wiki(fixture.primary_wiki_db) as conn:
        after_ingest_rows = conn.execute("SELECT COUNT(*) FROM ingest_log").fetchone()[0]
    assert after_ingest_rows == before_ingest_rows
