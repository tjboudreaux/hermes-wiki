"""Integration tests for the shared Hermes Wiki fixture factory."""

from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

from adapters.standalone import StandaloneHomeResolver, StandaloneKanbanReader
from fixtures.factory import OVERSIZED_SAMPLE_BYTES, build_clean_home, build_test_wiki
from fixtures.seed_data import (
    PAGE_TYPE_DIRECTORIES,
    PAGE_TYPES,
    SAMPLE_SOURCE_KINDS,
    sample_source_path,
)
from hermes_wiki import db
from hermes_wiki.lint import lint_wiki


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_sample_sources_cover_builtin_classifier_inputs() -> None:
    """Repository fixtures include representative article, paper, transcript, and unknown inputs."""
    assert SAMPLE_SOURCE_KINDS == ("article", "paper", "transcript", "unknown")
    for kind in SAMPLE_SOURCE_KINDS:
        source = sample_source_path(kind)
        assert source.exists()
        assert source.stat().st_size > 0

    assert "doi" in sample_source_path("paper").read_text(encoding="utf-8").lower()
    assert "abstract" in sample_source_path("paper").read_text(encoding="utf-8").lower()
    assert "Speaker 1:" in sample_source_path("transcript").read_text(encoding="utf-8")
    assert "article" in sample_source_path("article").read_text(encoding="utf-8").lower()


def test_factory_builds_isolated_populated_home_with_registry_and_wikis(tmp_path: Path) -> None:
    """The factory builds an isolated home with visible, archived, and private wikis."""
    fixture = build_test_wiki(tmp_path)

    assert fixture.home == tmp_path / "hermes-home"
    assert str(fixture.home).startswith(str(tmp_path))
    assert not str(fixture.home).startswith(str(Path.home() / ".hermes"))
    assert fixture.primary_slug == "ai-tooling"
    assert fixture.archived_slug == "ungodly-economy"
    assert fixture.private_slug == "private-lab"

    with db.connect_registry(fixture.registry_db) as conn:
        rows = {row["slug"]: row for row in db.list_wikis(conn, include_archived=True)}

    assert set(rows) == {"ai-tooling", "private-lab", "ungodly-economy"}
    assert rows["ai-tooling"]["archived"] == 0
    assert rows["ai-tooling"]["page_count"] == len(fixture.page_ids)
    assert rows["ai-tooling"]["source_count"] == 3
    assert rows["ungodly-economy"]["archived"] == 1
    assert "private: true" in (fixture.private_wiki_root / "SCHEMA.md").read_text(encoding="utf-8")
    assert (fixture.home / "wikis" / "default").read_text(encoding="utf-8").strip() == "ai-tooling"
    assert (fixture.home / "wikis" / "test-profile.current").read_text(
        encoding="utf-8"
    ).strip() == "ai-tooling"


def test_factory_populates_pages_sources_inbox_links_history_and_kanban(tmp_path: Path) -> None:
    """The primary wiki contains page/source/inbox coverage needed by later integration tests."""
    fixture = build_test_wiki(tmp_path)
    wiki_root = fixture.primary_wiki_root

    for page_type in PAGE_TYPES:
        directory = PAGE_TYPE_DIRECTORIES[page_type]
        assert any(page_id.startswith(f"{directory}/") for page_id in fixture.page_ids)

    with db.connect_wiki(fixture.primary_wiki_db) as conn:
        pages = {row["id"]: row for row in db.list_pages(conn)}
        sources = {row["id"]: row for row in conn.execute("SELECT * FROM sources")}
        ingest_log = db.list_ingest_log(conn)
        kanban_refs = db.list_kanban_refs(conn, page_id="concepts/agent-memory")
        search_results = db.search_pages(conn, "getCwd", limit=5)

    assert set(fixture.page_ids) == set(pages)
    assert {row["type"] for row in pages.values()} == {
        "comparison",
        "concept",
        "entity",
        "query",
        "source",
        "summary",
    }
    assert pages["concepts/agent-memory"]["inbound_links"] >= 2
    assert sorted(sources) == sorted(fixture.raw_source_paths)
    assert {row["classified_as"] for row in sources.values()} == {"article", "paper", "transcript"}
    assert len(ingest_log) >= 5
    assert kanban_refs == [
        {
            "page_id": "concepts/agent-memory",
            "task_id": "KB-123",
            "direction": "page->task",
            "created": "2026-06-05T09:30:00Z",
        }
    ]
    kanban_reader = StandaloneKanbanReader(home=StandaloneHomeResolver(home_path=fixture.home))
    linked_task = kanban_reader.get_task("KB-123")
    assert linked_task is not None
    assert linked_task["title"] == "Review agent memory dashboard linkage"
    assert not (fixture.home / "kanban.db").exists()
    assert search_results[0]["id"] == "concepts/agent-memory"

    agent_memory = (wiki_root / "concepts" / "agent-memory.md").read_text(encoding="utf-8")
    assert "../sources/2026-06-05-agent-memory-article.md" in agent_memory
    assert "kanban_refs:" in agent_memory
    assert "## Page History" not in agent_memory
    assert "edit | concepts/agent-memory" in (wiki_root / "log.md").read_text(encoding="utf-8")
    assert "wiki: edit concepts/agent-memory [fixture:agent]" in _git(
        wiki_root, "log", "--pretty=%s"
    )

    assert (wiki_root / "raw" / "inbox" / "unknown-sample.dat").is_file()
    oversized = wiki_root / "raw" / "inbox" / "oversized-sample.bin"
    assert oversized.is_file()
    assert oversized.stat().st_size == OVERSIZED_SAMPLE_BYTES
    assert oversized.stat().st_blocks * 512 < OVERSIZED_SAMPLE_BYTES
    assert os.path.samefile(fixture.inbox_paths["oversized"], oversized)


def test_factory_exposes_multi_severity_lint_conditions_and_valid_projection(
    tmp_path: Path,
) -> None:
    """Fixture metadata and on-disk content expose low/medium/high lint scenarios."""
    fixture = build_test_wiki(tmp_path)

    assert {finding.severity for finding in fixture.lint_findings} == {"high", "low", "medium"}
    assert any(finding.code == "broken-relative-link" for finding in fixture.lint_findings)
    assert any(finding.code == "oversized-inbox" for finding in fixture.lint_findings)
    assert any(finding.code == "page-over-200-lines" for finding in fixture.lint_findings)

    with sqlite3.connect(fixture.primary_wiki_db) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        active_projection_count = conn.execute(
            "SELECT COUNT(*) FROM projection_versions WHERE status='active'"
        ).fetchone()[0]
        assert active_projection_count == 1
        assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == len(fixture.page_ids)


def test_clean_fixture_lints_clean_with_max_health(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The clean fixture mode produces only valid pages and zero lint findings."""

    fixture = build_clean_home(tmp_path / "clean-hermes-home")
    monkeypatch.setenv("HERMES_HOME", str(fixture.home))

    report = lint_wiki(slug=fixture.primary_slug, profile=fixture.profile)

    assert report.status == "clean"
    assert report.findings == []
    assert report.health_score == 1.0
    assert fixture.lint_findings == ()
    assert fixture.inbox_paths == {}
    with db.connect_registry(fixture.registry_db) as conn:
        row = db.get_wiki(conn, fixture.primary_slug)
    assert row is not None
    assert float(row["health_score"]) == 1.0
