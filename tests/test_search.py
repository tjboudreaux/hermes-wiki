"""Search normalization, safety, visibility, and rebuild behavior."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from fixtures.factory import build_test_wiki
from hermes_wiki import db
from hermes_wiki.search import build_fts_query, normalize_search_text
from hermes_wiki_cli.cli import main


def _run_cli(home: Path, *argv: str, env: dict[str, str] | None = None) -> int:
    merged = {"HERMES_HOME": str(home), "USER": "search-tester", **(env or {})}
    old = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(merged)
        return main(list(argv))
    finally:
        os.environ.clear()
        os.environ.update(old)


def test_normalize_search_text_indexes_originals_and_split_identifiers() -> None:
    """Technical identifiers keep originals while adding camel/snake/kebab split forms."""
    text = normalize_search_text(
        "getCwd get_cwd get-cwd HTTPRequestParser GraphQL_API-client OAuthToken"
    )

    for original in (
        "getCwd",
        "get_cwd",
        "get-cwd",
        "HTTPRequestParser",
        "GraphQL_API-client",
        "OAuthToken",
    ):
        assert original in text
    assert "get Cwd" in text
    assert "get cwd" in text
    assert "HTTP Request Parser" in text
    assert "Graph QL API client" not in text
    assert "GraphQL API client" in text
    assert "OAuth Token" in text


def test_build_fts_query_treats_operators_and_special_chars_as_literals() -> None:
    """User input is converted to quoted terms and never exposed as FTS5 operator syntax."""
    assert build_fts_query("   ") is None
    assert build_fts_query('title:secret NEAR(memory tool) "unterminated -bar memory*') == (
        '"title" OR "secret" OR "NEAR" OR "memory" OR "tool" OR "unterminated" '
        'OR "bar" OR "memory"'
    )
    assert build_fts_query("get-cwd path/to-token café 東京") == (
        '"get-cwd" OR "path" OR "to-token" OR "café" OR "東京"'
    )


def test_db_search_is_non_stemmed_ranked_and_excludes_archived_pages(tmp_path: Path) -> None:
    """FTS5 search uses unicode61 without Porter stemming and hides archived pages."""
    with db.connect_wiki(tmp_path / "wiki.db") as conn:
        db.initialize_wiki(conn)
        db.upsert_page(
            conn,
            id="concepts/training-only",
            title="Training Only",
            type="concept",
            created="2026-06-05T00:00:00Z",
            updated="2026-06-05T00:00:00Z",
            tags=["ml"],
            body_text="This page says training but never the shorter stem.",
            snippet="training page",
        )
        db.upsert_page(
            conn,
            id="concepts/active-memory",
            title="Active Memory",
            type="concept",
            created="2026-06-05T00:00:00Z",
            updated="2026-06-05T00:00:00Z",
            tags=["memory"],
            body_text="memory memory memory memory",
            snippet="dense memory",
        )
        db.upsert_page(
            conn,
            id="concepts/passive-memory",
            title="Passive Memory",
            type="concept",
            created="2026-06-05T00:00:00Z",
            updated="2026-06-05T00:00:00Z",
            tags=["memory"],
            body_text="memory once",
            snippet="weak memory",
        )
        db.upsert_page(
            conn,
            id="concepts/archived-marker",
            title="Archived Marker",
            type="concept",
            created="2026-06-05T00:00:00Z",
            updated="2026-06-05T00:00:00Z",
            tags=[],
            body_text="deprecated-topic-marker",
            snippet="archived",
            archived=1,
        )

        assert [row["id"] for row in db.search_pages(conn, '"training"', limit=5)] == [
            "concepts/training-only"
        ]
        assert db.search_pages(conn, '"train"', limit=5) == []
        assert [row["id"] for row in db.search_pages(conn, '"memory"', limit=5)] == [
            "concepts/active-memory",
            "concepts/passive-memory",
        ]
        assert db.search_pages(conn, '"deprecated-topic-marker"', limit=5) == []
        assert db.search_pages(conn, "", limit=5) == []


def test_cli_search_safety_visibility_and_deleted_projection_rebuild(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI search surface is safe, scoped, non-disclosing, and rebuilds FTS."""
    fixture = build_test_wiki(tmp_path)

    assert _run_cli(fixture.home, "search", "getCwd") == 0
    getcwd_out = capsys.readouterr().out
    assert "concepts/agent-memory" in getcwd_out
    assert "get cwd" in getcwd_out.lower()

    assert _run_cli(fixture.home, "search", "get cwd", "--wiki", fixture.primary_slug) == 0
    assert "concepts/agent-memory" in capsys.readouterr().out

    assert _run_cli(fixture.home, "search", "memory", "--wiki", fixture.private_slug) == 1
    denied = capsys.readouterr()
    assert (denied.out + denied.err).strip() == "not found or not visible"

    assert _run_cli(fixture.home, "search", "memory", "--wiki", fixture.archived_slug) == 1
    denied = capsys.readouterr()
    assert (denied.out + denied.err).strip() == "not found or not visible"

    assert _run_cli(fixture.home, "search", 'title:memory NEAR(memory tool) "unterminated') == 0
    assert "Traceback" not in capsys.readouterr().err
    for special_query in (
        "attention AND",
        '"unterminated',
        "foo:bar",
        "trans*",
        "a NEAR/2 b",
        "memory OR NOT",
    ):
        assert _run_cli(fixture.home, "search", special_query) == 0
        special = capsys.readouterr()
        assert "Traceback" not in (special.out + special.err)
        assert "syntax error" not in (special.out + special.err).lower()

    assert _run_cli(fixture.home, "search", "") == 0
    assert capsys.readouterr().out.strip() == "No results."

    before_ids = _search_result_ids(fixture.home, "memory")
    fixture.primary_wiki_db.unlink()
    after_ids = _search_result_ids(fixture.home, "memory")

    assert before_ids == after_ids
    assert "concepts/agent-memory" in after_ids
    assert fixture.primary_wiki_db.exists()


def test_cli_open_prints_authoritative_page_content_and_denies_cleanly(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`wiki open` prints full Markdown for visible pages and hides denied lookups."""
    fixture = build_test_wiki(tmp_path)

    assert _run_cli(fixture.home, "open", "concepts/agent-memory") == 0
    opened = capsys.readouterr().out
    assert "id: concepts/agent-memory" in opened
    assert "type: concept" in opened
    assert "tags:" in opened
    assert "# Agent Memory" in opened
    assert "The getCwd helper appears in examples" in opened
    assert "Page History" not in opened
    assert "## History" not in opened

    assert _run_cli(fixture.home, "open", "concepts/does-not-exist") == 1
    missing = capsys.readouterr()
    assert "not found" in (missing.out + missing.err).lower()
    assert "Traceback" not in (missing.out + missing.err)

    assert _run_cli(
        fixture.home,
        "open",
        "concepts/agent-memory",
        "--wiki",
        fixture.private_slug,
    ) == 1
    denied = capsys.readouterr()
    assert (denied.out + denied.err).strip() == "not found or not visible"

    assert _run_cli(fixture.home, "open", "../outside", "--wiki", fixture.primary_slug) == 1
    unsafe = capsys.readouterr()
    assert "Traceback" not in (unsafe.out + unsafe.err)


def test_cli_list_pages_filters_scope_and_denies_invisible_wikis(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`wiki list-pages` supports type/tag/AND filters and read visibility scoping."""
    fixture = build_test_wiki(tmp_path)
    with db.connect_wiki(fixture.primary_wiki_db) as conn:
        db.upsert_page(
            conn,
            id="concepts/deprecated-topic",
            title="Deprecated Topic",
            type="concept",
            created="2026-06-05T00:00:00Z",
            updated="2026-06-05T00:00:00Z",
            tags=["memory"],
            body_text="# Deprecated Topic\n\nShould stay hidden.",
            archived=1,
        )
        conn.commit()

    assert _run_cli(fixture.home, "list-pages") == 0
    all_pages = capsys.readouterr().out
    assert "concepts/agent-memory" in all_pages
    assert "entities/hermes" in all_pages
    assert "sources/2026-06-05-agent-memory-article" in all_pages
    assert "raw/inbox" not in all_pages
    assert "unknown-sample.dat" not in all_pages
    assert "concepts/deprecated-topic" not in all_pages

    assert _run_cli(fixture.home, "list-pages", "--type", "concept") == 0
    concepts = capsys.readouterr().out
    assert "concepts/agent-memory" in concepts
    assert "entities/hermes" not in concepts
    assert "sources/2026-06-05-agent-memory-article" not in concepts

    assert _run_cli(fixture.home, "list-pages", "--type", "source") == 0
    sources = capsys.readouterr().out
    assert "sources/2026-06-05-agent-memory-article" in sources
    assert "raw/articles" not in sources
    assert "concepts/agent-memory" not in sources

    assert _run_cli(fixture.home, "list-pages", "--tag", "tooling") == 0
    tooling = capsys.readouterr().out
    assert "concepts/agent-memory" in tooling
    assert "entities/hermes" in tooling
    assert "queries/evaluate-agent-memory" not in tooling

    assert _run_cli(fixture.home, "list-pages", "--type", "concept", "--tag", "tooling") == 0
    concept_tooling = capsys.readouterr().out
    assert "concepts/agent-memory" in concept_tooling
    assert "entities/hermes" not in concept_tooling
    assert "summaries/agent-operations" not in concept_tooling

    assert _run_cli(fixture.home, "list-pages", "--type", "does-not-exist") == 0
    assert capsys.readouterr().out.strip() == "No pages."
    assert _run_cli(fixture.home, "list-pages", "--tag", "does-not-exist") == 0
    assert capsys.readouterr().out.strip() == "No pages."

    assert _run_cli(fixture.home, "list-pages", "--wiki", fixture.archived_slug) == 1
    archived = capsys.readouterr()
    assert (archived.out + archived.err).strip() == "not found or not visible"


def test_cli_list_pages_agrees_with_search_and_rebuilds_deleted_projection(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Listing and search expose the same visible page set after projection rebuild."""
    fixture = build_test_wiki(tmp_path)

    assert _run_cli(fixture.home, "search", "memory", "--wiki", fixture.primary_slug) == 0
    search_ids = _ids_from_cli_output(capsys.readouterr().out)
    assert search_ids

    assert _run_cli(fixture.home, "list-pages", "--wiki", fixture.primary_slug) == 0
    listed_ids = _ids_from_cli_output(capsys.readouterr().out)
    assert search_ids <= listed_ids

    fixture.primary_wiki_db.unlink()
    assert _run_cli(fixture.home, "list-pages", "--wiki", fixture.primary_slug) == 0
    rebuilt_out = capsys.readouterr().out
    assert "concepts/agent-memory" in rebuilt_out
    assert fixture.primary_wiki_db.exists()


def test_cli_search_matches_unicode_and_reflects_projection_refresh(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unicode content is searchable and refreshed FTS drops stale terms."""
    fixture = build_test_wiki(tmp_path)
    page_path = fixture.primary_wiki_root / "concepts" / "agent-memory.md"
    original = page_path.read_text(encoding="utf-8")
    page_path.write_text(
        original.replace(
            "The getCwd helper appears in examples so search normalization can match get cwd.",
            "Café 東京 notes now mention refreshedSearchToken for search refresh checks.",
        ),
        encoding="utf-8",
    )

    assert _run_cli(fixture.home, "lint", "--wiki", fixture.primary_slug) == 0
    capsys.readouterr()

    assert _run_cli(fixture.home, "search", "東京", "--wiki", fixture.primary_slug) == 0
    unicode_out = capsys.readouterr().out
    assert "concepts/agent-memory" in unicode_out
    assert "東京" in unicode_out

    assert (
        _run_cli(fixture.home, "search", "refreshedSearchToken", "--wiki", fixture.primary_slug)
        == 0
    )
    assert "concepts/agent-memory" in capsys.readouterr().out
    assert _run_cli(fixture.home, "search", "getCwd", "--wiki", fixture.primary_slug) == 0
    assert "concepts/agent-memory" not in capsys.readouterr().out


def _search_result_ids(home: Path, query: str) -> list[str]:
    old = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update({"HERMES_HOME": str(home), "USER": "search-tester"})
        from hermes_wiki.search import search_wiki

        return [str(row["id"]) for row in search_wiki(query)]
    finally:
        os.environ.clear()
        os.environ.update(old)


def _ids_from_cli_output(output: str) -> set[str]:
    ids: set[str] = set()
    for line in output.splitlines():
        first = line.split(":", 1)[0].strip()
        if "/" in first:
            ids.add(first)
    return ids
