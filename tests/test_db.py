"""Tests for the Hermes Wiki SQLite registry and projection schema."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from hermes_wiki import db


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]


def test_registry_schema_and_wiki_crud_use_wal(tmp_path: Path) -> None:
    """The registry DB contains only the SPEC wikis table and supports CRUD."""
    registry_path = tmp_path / "wikis.db"

    with db.connect_registry(registry_path) as conn:
        db.initialize_registry(conn)

        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert db.registry_tables(conn) == ["wikis"]
        assert _table_columns(conn, "wikis") == [
            "slug",
            "path",
            "domain",
            "created",
            "updated",
            "page_count",
            "source_count",
            "last_ingest",
            "last_lint",
            "health_score",
            "archived",
            "archived_at",
        ]

        wiki = db.upsert_wiki(
            conn,
            slug="ai-tooling",
            path=tmp_path / "ai-tooling",
            domain="AI agents, coding tools, research",
        )
        db.update_wiki_counts(conn, slug="ai-tooling", page_count=2, source_count=1)
        db.archive_wiki(conn, slug="ai-tooling", archived_at="2026-06-05T00:00:00Z")

        assert wiki["slug"] == "ai-tooling"
        stored = db.get_wiki(conn, "ai-tooling")
        assert stored is not None
        assert stored["path"] == str(tmp_path / "ai-tooling")
        assert stored["page_count"] == 2
        assert stored["source_count"] == 1
        assert stored["archived"] == 1
        assert [row["slug"] for row in db.list_wikis(conn, include_archived=True)] == ["ai-tooling"]
        assert db.list_wikis(conn) == []


def test_wiki_schema_matches_spec_tables_and_columns(tmp_path: Path) -> None:
    """The per-wiki DB creates the SPEC tables, pages_fts, indexes, and triggers."""
    wiki_db_path = tmp_path / "wiki.db"

    with db.connect_wiki(wiki_db_path) as conn:
        db.initialize_wiki(conn)

        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert db.wiki_tables(conn) == [
            "ingest_log",
            "kanban_refs",
            "page_links",
            "pages",
            "pages_fts",
            "pages_fts_config",
            "pages_fts_data",
            "pages_fts_docsize",
            "pages_fts_idx",
            "projection_versions",
            "sources",
            "taxonomy",
            "trusted_plugins",
        ]
        assert _table_columns(conn, "pages") == [
            "id",
            "title",
            "type",
            "created",
            "updated",
            "tags",
            "sources",
            "confidence",
            "contested",
            "contradictions",
            "author",
            "author_kind",
            "sha256",
            "word_count",
            "inbound_links",
            "snippet",
            "body_text",
            "search_text",
            "archived",
        ]
        assert _table_columns(conn, "pages_fts") == [
            "id",
            "title",
            "tags",
            "snippet",
            "search_text",
        ]
        assert _table_columns(conn, "page_links") == [
            "source_page_id",
            "target_page_id",
        ]
        assert _table_columns(conn, "sources") == [
            "id",
            "ingested_at",
            "sha256",
            "source_url",
            "source_path",
            "version",
            "previous_source_id",
            "is_latest",
            "classified_as",
        ]

        fts_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'pages_fts'"
        ).fetchone()["sql"]
        assert "USING fts5" in fts_sql
        assert "content='pages'" in fts_sql
        assert "content_rowid='rowid'" in fts_sql
        assert "tokenize='unicode61'" in fts_sql

        triggers = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'pages'"
            )
        }
        assert triggers == {"pages_ai", "pages_ad", "pages_au"}


def test_page_link_projection_helpers_track_inbound_refs(tmp_path: Path) -> None:
    """The projection has a lightweight page-link index for inbound page lookups."""

    with db.connect_wiki(tmp_path / "wiki.db") as conn:
        db.initialize_wiki(conn)
        db.upsert_page(
            conn,
            id="sources/article",
            title="Article",
            type="source",
            created="2026-06-05T00:00:00Z",
            updated="2026-06-05T00:00:00Z",
            body_text="Article body",
        )
        db.upsert_page(
            conn,
            id="concepts/agent-memory",
            title="Agent Memory",
            type="concept",
            created="2026-06-05T00:00:00Z",
            updated="2026-06-05T00:00:00Z",
            body_text="Concept body",
        )
        db.replace_page_links(
            conn,
            source_page_id="sources/article",
            target_page_ids=["concepts/agent-memory", "concepts/agent-memory.md"],
        )

        inbound = db.list_inbound_page_links(conn, target_page_id="concepts/agent-memory")

        assert [row["id"] for row in inbound] == ["sources/article"]


def test_page_crud_keeps_fts_in_sync_and_returns_bm25_ranked_results(tmp_path: Path) -> None:
    """Page upserts/deletes update external-content FTS and search returns BM25 order."""
    with db.connect_wiki(tmp_path / "wiki.db") as conn:
        db.initialize_wiki(conn)

        db.upsert_page(
            conn,
            id="concepts/agent-memory",
            title="Agent Memory",
            type="concept",
            created="2026-06-05T00:00:00Z",
            updated="2026-06-05T00:00:00Z",
            tags=["memory", "agents"],
            sources=["raw/articles/memory.md"],
            body_text=(
                "Agent memory systems help agents retain memory. "
                "Durable memory improves recall across sessions."
            ),
            search_text="agent memory systems retain durable memory recall",
            snippet="Durable agent memory",
            author="tester",
            author_kind="human",
        )
        db.upsert_page(
            conn,
            id="concepts/tool-use",
            title="Tool Use",
            type="concept",
            created="2026-06-05T00:00:00Z",
            updated="2026-06-05T00:00:00Z",
            tags=["tools"],
            sources=[],
            body_text="Agents use tools for coding and search.",
            search_text="agents tools coding search",
            snippet="Tool-using agents",
        )

        rows = db.search_pages(conn, "memory", limit=5)
        assert [row["id"] for row in rows] == ["concepts/agent-memory"]
        assert rows[0]["rank"] < 0
        memory_page = db.get_page(conn, "concepts/agent-memory")
        assert memory_page is not None
        assert memory_page["tags"] == ["memory", "agents"]

        db.upsert_page(
            conn,
            id="concepts/tool-use",
            title="Memory Memory Memory Tool Use",
            type="concept",
            created="2026-06-05T00:00:00Z",
            updated="2026-06-06T00:00:00Z",
            tags=["tools", "memory"],
            sources=[],
            body_text="Tool use with memory memory memory memory memory for agents.",
            search_text="tool use memory memory memory memory memory agents",
            snippet="Memory Memory Tool memory",
        )
        rows = db.search_pages(conn, "memory", limit=5)
        assert [row["id"] for row in rows] == ["concepts/tool-use", "concepts/agent-memory"]

        db.delete_page(conn, "concepts/tool-use")
        assert [row["id"] for row in db.search_pages(conn, "memory", limit=5)] == [
            "concepts/agent-memory"
        ]


def test_operational_crud_primitives(tmp_path: Path) -> None:
    """Non-page metadata tables have small CRUD helpers for later features."""
    with db.connect_wiki(tmp_path / "wiki.db") as conn:
        db.initialize_wiki(conn)

        db.insert_ingest_log(
            conn,
            ingested_at="2026-06-05T00:00:00Z",
            source_type="article",
            source_url="https://example.com/memory",
            source_path=None,
            sha256="abc123",
            pages_created=["concepts/agent-memory"],
            pages_updated=[],
            author="tester",
            author_kind="human",
        )
        db.upsert_source(
            conn,
            id="raw/articles/memory-v1.md",
            ingested_at="2026-06-05T00:00:00Z",
            sha256="abc123",
            source_url="https://example.com/memory",
            source_path=None,
            version=1,
            classified_as="article",
        )
        db.add_taxonomy_tag(conn, tag="memory", created="2026-06-05")
        db.upsert_trusted_plugin(
            conn,
            name="article-plus",
            kind="classifier",
            path="plugins/classifiers/article-plus.py",
            sha256="def456",
            trusted_at="2026-06-05T00:00:00Z",
            author="tester",
            author_kind="human",
        )
        db.upsert_kanban_ref(
            conn,
            page_id="concepts/agent-memory",
            task_id="KB-123",
            direction="page->task",
            created="2026-06-05T00:00:00Z",
        )
        db.upsert_projection_version(
            conn,
            version_id="initial",
            created="2026-06-05T00:00:00Z",
            schema_version=db.SCHEMA_VERSION,
            source_tree_sha256="tree123",
            db_sha256="db123",
            previous_version_id=None,
            rebuild_reason="initial",
            status="active",
            notes="created in test",
            author="tester",
            author_kind="human",
        )

        assert db.list_ingest_log(conn)[0]["pages_created"] == ["concepts/agent-memory"]
        source = db.get_source(conn, "raw/articles/memory-v1.md")
        assert source is not None
        assert source["is_latest"] == 1
        assert db.list_taxonomy(conn) == [{"tag": "memory", "created": "2026-06-05"}]
        assert db.list_trusted_plugins(conn)[0]["name"] == "article-plus"
        assert db.list_kanban_refs(conn, page_id="concepts/agent-memory")[0]["task_id"] == "KB-123"
        assert db.list_projection_versions(conn)[0]["version_id"] == "initial"


def test_initialize_wiki_only_rebuilds_fts_when_table_is_created(tmp_path: Path) -> None:
    """Re-running initialize_wiki on a live DB must not rebuild the FTS index."""

    def _page_kwargs(page_id: str) -> dict[str, object]:
        return {
            "id": page_id,
            "title": page_id.rsplit("/", 1)[-1].replace("-", " ").title(),
            "type": "concept",
            "created": "2026-06-05T00:00:00Z",
            "updated": "2026-06-05T00:00:00Z",
            "tags": ("agents",),
            "sources": (),
            "confidence": "medium",
            "contested": 0,
            "contradictions": None,
            "author": "db-tester",
            "author_kind": "human",
            "sha256": "0" * 64,
            "inbound_links": 0,
            "snippet": "alpha concept snippet",
            "body_text": "alpha concept body",
        }

    def _search_ids(conn: object) -> list[str]:
        rows = db.search_pages(conn, '"alpha"', limit=5)  # type: ignore[arg-type]
        return [str(row["id"]) for row in rows]

    with db.connect_wiki(tmp_path / "wiki.db") as conn:
        db.initialize_wiki(conn)
        db.upsert_page(conn, **_page_kwargs("concepts/alpha"))
        conn.commit()
        assert _search_ids(conn) == ["concepts/alpha"]

        # Second init on an already-initialized DB: no FTS rebuild statement.
        statements: list[str] = []
        conn.set_trace_callback(statements.append)
        db.initialize_wiki(conn)
        conn.set_trace_callback(None)
        rebuilds = [s for s in statements if "values ('rebuild')" in s.lower()]
        assert rebuilds == [], f"unexpected FTS rebuild on re-init: {rebuilds}"
        assert _search_ids(conn) == ["concepts/alpha"]

        # Migration path: pages_fts missing over a populated pages table —
        # initialize_wiki must create it AND rebuild so rows are indexed.
        conn.executescript(
            """
            DROP TRIGGER pages_ai; DROP TRIGGER pages_ad; DROP TRIGGER pages_au;
            DROP TABLE pages_fts;
            """
        )
        db.initialize_wiki(conn)
        conn.commit()
        assert _search_ids(conn) == ["concepts/alpha"]
