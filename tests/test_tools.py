from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from fixtures.factory import build_test_wiki
from fixtures.seed_data import sample_source_path


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


def _write_config(home: Path, text: str) -> None:
    (home / "config.yaml").write_text(text, encoding="utf-8")


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
            "task": {
                "id": "KB-123",
                "status": "todo",
                "title": "Review agent memory dashboard linkage",
            },
        }
    ]

    assert wiki_show("concepts/agent-memory", wiki=fixture.private_slug) == NOT_FOUND_OR_NOT_VISIBLE
    assert wiki_show("concepts/nope", wiki=fixture.primary_slug) == "page not found: concepts/nope"


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


def test_write_gate_allows_env_toolset_slug_and_wildcard_grants(
    monkeypatch: Any, tmp_path: Path
) -> None:
    fixture = _use_fixture_home(monkeypatch, tmp_path)
    from hermes_wiki.tools import _check_wiki_write_mode

    monkeypatch.setenv("HERMES_WIKI", fixture.primary_slug)
    assert _check_wiki_write_mode(fixture.primary_slug)
    assert _check_wiki_write_mode(None)
    assert not _check_wiki_write_mode(fixture.private_slug)

    monkeypatch.delenv("HERMES_WIKI", raising=False)
    _write_config(fixture.home, "toolsets: [wiki]\nwiki:\n  write_grants: []\n")
    assert _check_wiki_write_mode(fixture.primary_slug)
    assert _check_wiki_write_mode(fixture.private_slug)

    _write_config(fixture.home, f"wiki:\n  write_grants: [{fixture.primary_slug}]\n")
    assert _check_wiki_write_mode(fixture.primary_slug)
    assert not _check_wiki_write_mode(fixture.private_slug)
    assert _check_wiki_write_mode(None)

    _write_config(fixture.home, 'wiki:\n  write_grants: ["*"]\n')
    assert _check_wiki_write_mode(fixture.primary_slug)
    assert _check_wiki_write_mode(fixture.private_slug)


def test_write_gate_falls_through_on_env_mismatch_and_fails_closed(
    monkeypatch: Any, tmp_path: Path
) -> None:
    fixture = _use_fixture_home(monkeypatch, tmp_path)
    from hermes_wiki.tools import _check_wiki_write_mode

    monkeypatch.setenv("HERMES_WIKI", fixture.primary_slug)
    _write_config(fixture.home, "wiki:\n  write_grants: []\n")
    assert not _check_wiki_write_mode(fixture.private_slug)

    monkeypatch.delenv("HERMES_WIKI", raising=False)
    _write_config(fixture.home, "wiki: [")
    assert not _check_wiki_write_mode(fixture.primary_slug)


def test_write_grant_does_not_override_visibility_and_visible_denial_is_distinct(
    monkeypatch: Any, tmp_path: Path
) -> None:
    fixture = _use_fixture_home(monkeypatch, tmp_path)
    from hermes_wiki.tools import (
        NOT_FOUND_OR_NOT_VISIBLE,
        WRITE_PERMISSION_DENIED,
        wiki_create_page,
    )

    _write_config(fixture.home, 'wiki:\n  write_grants: ["*"]\n')
    assert (
        wiki_create_page(
            title="Private Write",
            body="Should not be written",
            type="concept",
            wiki=fixture.private_slug,
        )
        == NOT_FOUND_OR_NOT_VISIBLE
    )
    assert not (fixture.private_wiki_root / "concepts" / "private-write.md").exists()

    _write_config(fixture.home, "wiki:\n  write_grants: []\n")
    assert (
        wiki_create_page(
            title="Visible No Grant",
            body="Should not be written",
            type="concept",
            wiki=fixture.primary_slug,
        )
        == WRITE_PERMISSION_DENIED
    )
    assert not (fixture.primary_wiki_root / "concepts" / "visible-no-grant.md").exists()


def test_wiki_ingest_requires_exactly_one_source_or_inbox(
    monkeypatch: Any, tmp_path: Path
) -> None:
    fixture = _use_fixture_home(monkeypatch, tmp_path)
    source_path = sample_source_path("article")
    from hermes_wiki import db
    from hermes_wiki.tools import wiki_ingest

    monkeypatch.setenv("HERMES_WIKI", fixture.primary_slug)
    with db.connect_wiki(fixture.primary_wiki_db) as conn:
        before_rows = conn.execute("SELECT COUNT(*) FROM ingest_log").fetchone()[0]

    assert (
        wiki_ingest(wiki=fixture.primary_slug)
        == "wiki_ingest requires exactly one of path_or_url or inbox=True"
    )
    assert (
        wiki_ingest(str(source_path), wiki=fixture.primary_slug, inbox=True)
        == "wiki_ingest requires exactly one of path_or_url or inbox=True"
    )

    with db.connect_wiki(fixture.primary_wiki_db) as conn:
        after_rows = conn.execute("SELECT COUNT(*) FROM ingest_log").fetchone()[0]
    assert after_rows == before_rows


def test_wiki_create_page_writes_attributed_page_index_projection_and_commit(
    monkeypatch: Any, tmp_path: Path
) -> None:
    fixture = _use_fixture_home(monkeypatch, tmp_path)
    from hermes_wiki import db
    from hermes_wiki.frontmatter import read_markdown
    from hermes_wiki.tools import wiki_create_page

    monkeypatch.setenv("HERMES_WIKI", fixture.primary_slug)
    monkeypatch.setenv("HERMES_MODEL", "claude-test")

    result = _mapping(
        wiki_create_page(
            title="Field Notes",
            body="# Field Notes\n\nAgent-authored synthesis.",
            type="concept",
            tags=["agents", "notes"],
            sources=["raw/articles/2026-06-05-v1-agent-memory-article.md"],
            wiki=fixture.primary_slug,
        )
    )
    assert result["id"] == "concepts/field-notes"
    assert result["author"] == "claude-test"
    assert result["author_kind"] == "agent"

    page_path = fixture.primary_wiki_root / "concepts" / "field-notes.md"
    frontmatter, body = read_markdown(page_path)
    assert frontmatter["author"] == "claude-test"
    assert frontmatter["author_kind"] == "agent"
    assert frontmatter["tags"] == ["agents", "notes"]
    assert "Agent-authored synthesis." in body
    assert "concepts/field-notes" in (fixture.primary_wiki_root / "index.md").read_text(
        encoding="utf-8"
    )
    assert "| create-page | concepts/field-notes | claude-test | agent |" in (
        fixture.primary_wiki_root / "log.md"
    ).read_text(encoding="utf-8")
    with db.connect_wiki(fixture.primary_wiki_db) as conn:
        page = db.get_page(conn, "concepts/field-notes")
        assert page is not None
        assert page["author"] == "claude-test"
        assert page["author_kind"] == "agent"
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM pages WHERE id = 'concepts/field-notes'"
            ).fetchone()[0]
            == 1
        )

    git_log = subprocess.run(
        ["git", "-C", str(fixture.primary_wiki_root), "log", "-1", "--stat", "--oneline"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    assert "wiki: create-page concepts/field-notes [claude-test]" in git_log
    assert "concepts/field-notes.md" in git_log
    assert "index.md" in git_log

    update = _mapping(
        wiki_create_page(
            title="Field Notes",
            body="# Field Notes\n\nUpdated body.",
            type="concept",
            tags=["agents"],
            sources=[],
            wiki=fixture.primary_slug,
        )
    )
    assert update["id"] == "concepts/field-notes"
    assert "Updated body." in read_markdown(page_path)[1]
    assert len(list((fixture.primary_wiki_root / "concepts").glob("field-notes*.md"))) == 1
    with db.connect_wiki(fixture.primary_wiki_db) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM pages WHERE id = 'concepts/field-notes'"
            ).fetchone()[0]
            == 1
        )


def test_wiki_create_page_under_cron_env_uses_cron_attribution(
    monkeypatch: Any, tmp_path: Path
) -> None:
    fixture = _use_fixture_home(monkeypatch, tmp_path)
    from hermes_wiki import db
    from hermes_wiki.frontmatter import read_markdown
    from hermes_wiki.tools import _check_wiki_write_mode, wiki_create_page

    job_name = "wiki:ai-tooling:weekly-arxiv-sweep"
    monkeypatch.setenv("HERMES_WIKI", fixture.primary_slug)
    monkeypatch.setenv("HERMES_CRON_JOB", job_name)
    monkeypatch.delenv("HERMES_MODEL", raising=False)

    assert _check_wiki_write_mode(fixture.primary_slug)
    assert not _check_wiki_write_mode(fixture.private_slug)

    result = _mapping(
        wiki_create_page(
            title="Cron Notes",
            body="# Cron Notes\n\nCron-authored synthesis.",
            type="concept",
            tags=["cron"],
            sources=[],
            wiki=fixture.primary_slug,
        )
    )

    assert result["author"] == f"cron:{job_name}"
    assert result["author_kind"] == "cron"
    page_path = fixture.primary_wiki_root / "concepts" / "cron-notes.md"
    frontmatter, _body = read_markdown(page_path)
    assert frontmatter["author"] == f"cron:{job_name}"
    assert frontmatter["author_kind"] == "cron"
    with db.connect_wiki(fixture.primary_wiki_db) as conn:
        page = db.get_page(conn, "concepts/cron-notes")
        assert page is not None
        assert page["author"] == f"cron:{job_name}"
        assert page["author_kind"] == "cron"
    assert f"| create-page | concepts/cron-notes | cron:{job_name} | cron |" in (
        fixture.primary_wiki_root / "log.md"
    ).read_text(encoding="utf-8")
    git_log = subprocess.run(
        ["git", "-C", str(fixture.primary_wiki_root), "log", "-1", "--pretty=%s"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    assert f"wiki: create-page concepts/cron-notes [cron:{job_name}]" in git_log


def test_wiki_link_kanban_updates_wiki_side_only(monkeypatch: Any, tmp_path: Path) -> None:
    fixture = _use_fixture_home(monkeypatch, tmp_path)
    from hermes_wiki import db
    from hermes_wiki.frontmatter import read_markdown
    from hermes_wiki.tools import wiki_link_kanban

    monkeypatch.setenv("HERMES_WIKI", fixture.primary_slug)
    monkeypatch.setenv("HERMES_MODEL", "claude-test")
    kanban_db = fixture.home / "kanban.db"
    kanban_db.write_text("read-only sentinel", encoding="utf-8")
    (fixture.home / "kanban_tasks.json").write_text(
        json.dumps({"KB-999": {"id": "KB-999", "title": "Agent-side task"}}),
        encoding="utf-8",
    )
    before_bytes = kanban_db.read_bytes()
    before_mtime = kanban_db.stat().st_mtime_ns

    result = _mapping(
        wiki_link_kanban(
            "concepts/agent-memory",
            "KB-999",
            wiki=fixture.primary_slug,
        )
    )
    assert result["wiki"] == fixture.primary_slug
    assert result["page_id"] == "concepts/agent-memory"
    assert result["task_id"] == "KB-999"
    assert result["direction"] == "page->task"
    assert result["author"] == "claude-test"
    assert result["author_kind"] == "agent"
    assert result["commit_id"]

    frontmatter, _body = read_markdown(fixture.primary_wiki_root / "concepts/agent-memory.md")
    assert {
        "task_id": "KB-999",
        "direction": "page->task",
        "created": result["created"],
    } in frontmatter["kanban_refs"]
    with db.connect_wiki(fixture.primary_wiki_db) as conn:
        refs = db.list_kanban_refs(conn, page_id="concepts/agent-memory")
    assert any(ref["task_id"] == "KB-999" for ref in refs)
    assert kanban_db.read_bytes() == before_bytes
    assert kanban_db.stat().st_mtime_ns == before_mtime


def test_wiki_ingest_agent_attribution_inbox_and_forced_classifier(
    monkeypatch: Any, tmp_path: Path
) -> None:
    fixture = _use_fixture_home(monkeypatch, tmp_path)
    from hermes_wiki import db
    from hermes_wiki.frontmatter import read_markdown
    from hermes_wiki.tools import wiki_ingest

    monkeypatch.setenv("HERMES_WIKI", fixture.primary_slug)
    monkeypatch.setenv("HERMES_MODEL", "claude-test")
    source = tmp_path / "forced-article.md"
    source.write_text(
        "# Forced Article\n\nThis article discusses durable agent memory and Hermes workflows.",
        encoding="utf-8",
    )

    result = _mapping(
        wiki_ingest(str(source), wiki=fixture.primary_slug, classifier="paper")
    )
    assert result["classified_as"] == "paper"
    assert result["raw_snapshot"].startswith("raw/papers/")
    assert result["pages_created"]
    source_page = fixture.primary_wiki_root / f"{result['pages_created'][0]}.md"
    frontmatter, _body = read_markdown(source_page)
    assert frontmatter["author"] == "claude-test"
    assert frontmatter["author_kind"] == "agent"
    with db.connect_wiki(fixture.primary_wiki_db) as conn:
        newest_log = conn.execute(
            "SELECT source_type, author, author_kind FROM ingest_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert dict(newest_log) == {
        "source_type": "paper",
        "author": "claude-test",
        "author_kind": "agent",
    }

    inbox_source = fixture.primary_wiki_root / "raw" / "inbox" / "batch-article.md"
    inbox_source.write_text(
        "# Batch Article\n\nA blog article about agent wiki inbox ingestion.",
        encoding="utf-8",
    )
    inbox_results = _rows(wiki_ingest(wiki=fixture.primary_slug, inbox=True))
    processed = [row for row in inbox_results if row.get("message") == "batch-article.md"]
    assert processed and processed[0]["classified_as"] == "article"
    assert not inbox_source.exists()
    assert processed[0]["raw_snapshot"].startswith("raw/articles/")
    with db.connect_wiki(fixture.primary_wiki_db) as conn:
        rows = list(
            conn.execute(
                "SELECT author_kind FROM ingest_log WHERE source_path = ?",
                (processed[0]["raw_snapshot"],),
            )
        )
    assert [row["author_kind"] for row in rows] == ["agent"]
