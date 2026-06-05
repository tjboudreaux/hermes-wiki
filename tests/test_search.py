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
