"""SQLite registry and per-wiki projection helpers.

The database is a rebuildable projection over Markdown wiki files and raw
sources. This module owns the exact M0 schema from ``SPEC.md §3.2`` plus the
``pages.archived`` column called out in the foundation architecture.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hermes_wiki.search import normalize_search_text as _normalize_search_text

SCHEMA_VERSION = "1"

JsonList = Sequence[str] | None
RowDict = dict[str, Any]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def connect_registry(db_path: Path | str) -> sqlite3.Connection:
    """Open a registry ``wikis.db`` connection with WAL enabled."""

    return _connect(db_path)


def connect_wiki(db_path: Path | str) -> sqlite3.Connection:
    """Open a per-wiki ``wiki.db`` projection connection with WAL enabled."""

    return _connect(db_path)


def _names(conn: sqlite3.Connection, *, kind: str) -> list[str]:
    return [
        str(row["name"])
        for row in conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = ? AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """,
            (kind,),
        )
    ]


def registry_tables(conn: sqlite3.Connection) -> list[str]:
    """Return non-internal registry table names."""

    return _names(conn, kind="table")


def wiki_tables(conn: sqlite3.Connection) -> list[str]:
    """Return non-internal wiki table names, including FTS5 shadow tables."""

    return _names(conn, kind="table")


def initialize_registry(conn: sqlite3.Connection) -> None:
    """Create the registry schema from ``SPEC.md §3.2``."""

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS wikis (
            slug TEXT PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            domain TEXT,
            created TEXT,
            updated TEXT,
            page_count INTEGER DEFAULT 0,
            source_count INTEGER DEFAULT 0,
            last_ingest TEXT,
            last_lint TEXT,
            health_score REAL DEFAULT 1.0,
            archived INTEGER DEFAULT 0,
            archived_at TEXT
        );
        """
    )


def initialize_wiki(conn: sqlite3.Connection) -> None:
    """Create the per-wiki projection schema from ``SPEC.md §3.2``."""

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pages (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            type TEXT NOT NULL,
            created TEXT NOT NULL,
            updated TEXT NOT NULL,
            tags TEXT,
            sources TEXT,
            confidence TEXT DEFAULT 'medium',
            contested INTEGER DEFAULT 0,
            contradictions TEXT,
            author TEXT,
            author_kind TEXT,
            sha256 TEXT,
            word_count INTEGER,
            inbound_links INTEGER DEFAULT 0,
            snippet TEXT,
            body_text TEXT,
            search_text TEXT,
            archived INTEGER DEFAULT 0
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
            id, title, tags, snippet, search_text,
            content='pages',
            content_rowid='rowid',
            tokenize='unicode61'
        );

        CREATE TABLE IF NOT EXISTS ingest_log (
            id INTEGER PRIMARY KEY,
            ingested_at TEXT,
            source_type TEXT,
            source_url TEXT,
            source_path TEXT,
            sha256 TEXT,
            pages_created TEXT,
            pages_updated TEXT,
            drift_detected INTEGER DEFAULT 0,
            author TEXT,
            author_kind TEXT
        );

        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY,
            ingested_at TEXT,
            sha256 TEXT,
            source_url TEXT,
            source_path TEXT,
            version INTEGER DEFAULT 1,
            previous_source_id TEXT,
            is_latest INTEGER DEFAULT 1,
            classified_as TEXT
        );

        CREATE TABLE IF NOT EXISTS taxonomy (
            tag TEXT PRIMARY KEY,
            created TEXT
        );

        CREATE TABLE IF NOT EXISTS trusted_plugins (
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            trusted_at TEXT NOT NULL,
            author TEXT,
            author_kind TEXT,
            PRIMARY KEY (name, kind)
        );

        CREATE TABLE IF NOT EXISTS kanban_refs (
            page_id TEXT,
            task_id TEXT,
            direction TEXT,
            created TEXT,
            PRIMARY KEY (page_id, task_id, direction)
        );

        CREATE TABLE IF NOT EXISTS page_links (
            source_page_id TEXT NOT NULL,
            target_page_id TEXT NOT NULL,
            PRIMARY KEY (source_page_id, target_page_id)
        );

        CREATE TABLE IF NOT EXISTS projection_versions (
            version_id TEXT PRIMARY KEY,
            created TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            source_tree_sha256 TEXT NOT NULL,
            db_sha256 TEXT,
            previous_version_id TEXT,
            rebuild_reason TEXT,
            status TEXT NOT NULL,
            notes TEXT,
            author TEXT,
            author_kind TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_pages_type ON pages(type);
        CREATE INDEX IF NOT EXISTS idx_pages_updated ON pages(updated);
        CREATE INDEX IF NOT EXISTS idx_pages_archived ON pages(archived);
        CREATE INDEX IF NOT EXISTS idx_ingest_log_ingested_at ON ingest_log(ingested_at);
        CREATE INDEX IF NOT EXISTS idx_sources_latest ON sources(source_url, is_latest);
        CREATE INDEX IF NOT EXISTS idx_kanban_refs_task_id ON kanban_refs(task_id);
        CREATE INDEX IF NOT EXISTS idx_page_links_target ON page_links(target_page_id);

        CREATE TRIGGER IF NOT EXISTS pages_ai AFTER INSERT ON pages BEGIN
            INSERT INTO pages_fts(rowid, id, title, tags, snippet, search_text)
            VALUES (new.rowid, new.id, new.title, new.tags, new.snippet, new.search_text);
        END;

        CREATE TRIGGER IF NOT EXISTS pages_ad AFTER DELETE ON pages BEGIN
            INSERT INTO pages_fts(pages_fts, rowid, id, title, tags, snippet, search_text)
            VALUES ('delete', old.rowid, old.id, old.title, old.tags, old.snippet, old.search_text);
        END;

        CREATE TRIGGER IF NOT EXISTS pages_au AFTER UPDATE ON pages BEGIN
            INSERT INTO pages_fts(pages_fts, rowid, id, title, tags, snippet, search_text)
            VALUES ('delete', old.rowid, old.id, old.title, old.tags, old.snippet, old.search_text);
            INSERT INTO pages_fts(rowid, id, title, tags, snippet, search_text)
            VALUES (new.rowid, new.id, new.title, new.tags, new.snippet, new.search_text);
        END;
        """
    )
    rebuild_pages_fts(conn)


def rebuild_pages_fts(conn: sqlite3.Connection) -> None:
    """Explicitly rebuild the external-content FTS index from ``pages``."""

    conn.execute("INSERT INTO pages_fts(pages_fts) VALUES ('rebuild')")


def _json_dump(value: JsonList) -> str | None:
    if value is None:
        return None
    return json.dumps(list(value), separators=(",", ":"), sort_keys=True)


def _json_load(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _row_dict(row: sqlite3.Row | None, *, json_fields: set[str] | None = None) -> RowDict | None:
    if row is None:
        return None
    data = dict(row)
    for field in json_fields or set():
        if field in data:
            data[field] = _json_load(data[field])
    return data


def _rows(
    cursor: sqlite3.Cursor,
    *,
    json_fields: set[str] | None = None,
) -> list[RowDict]:
    return [
        converted
        for row in cursor
        if (converted := _row_dict(row, json_fields=json_fields)) is not None
    ]


def normalize_search_text(*parts: str | Sequence[str] | None) -> str:
    """Normalize technical terms while preserving originals for FTS indexing."""

    return _normalize_search_text(*parts)


def _word_count(text: str | None) -> int | None:
    if text is None:
        return None
    words = re.findall(r"\b\w+\b", text)
    return len(words)


def upsert_wiki(
    conn: sqlite3.Connection,
    *,
    slug: str,
    path: Path | str,
    domain: str | None = None,
    created: str | None = None,
    updated: str | None = None,
    page_count: int = 0,
    source_count: int = 0,
    last_ingest: str | None = None,
    last_lint: str | None = None,
    health_score: float = 1.0,
    archived: int = 0,
    archived_at: str | None = None,
) -> RowDict:
    """Create or update a registry wiki row and return it."""

    now = _utc_now()
    created_at = created or now
    updated_at = updated or now
    conn.execute(
        """
        INSERT INTO wikis (
            slug, path, domain, created, updated, page_count, source_count,
            last_ingest, last_lint, health_score, archived, archived_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET
            path = excluded.path,
            domain = excluded.domain,
            updated = excluded.updated,
            page_count = excluded.page_count,
            source_count = excluded.source_count,
            last_ingest = excluded.last_ingest,
            last_lint = excluded.last_lint,
            health_score = excluded.health_score,
            archived = excluded.archived,
            archived_at = excluded.archived_at
        """,
        (
            slug,
            str(path),
            domain,
            created_at,
            updated_at,
            page_count,
            source_count,
            last_ingest,
            last_lint,
            health_score,
            archived,
            archived_at,
        ),
    )
    wiki = get_wiki(conn, slug)
    if wiki is None:  # pragma: no cover - SQLite would have raised first
        raise RuntimeError(f"failed to upsert wiki {slug!r}")
    return wiki


def get_wiki(conn: sqlite3.Connection, slug: str) -> RowDict | None:
    """Return a registry wiki row."""

    return _row_dict(conn.execute("SELECT * FROM wikis WHERE slug = ?", (slug,)).fetchone())


def list_wikis(conn: sqlite3.Connection, *, include_archived: bool = False) -> list[RowDict]:
    """List registry wikis, hiding archived rows by default."""

    if include_archived:
        cursor = conn.execute("SELECT * FROM wikis ORDER BY slug")
    else:
        cursor = conn.execute("SELECT * FROM wikis WHERE archived = 0 ORDER BY slug")
    return _rows(cursor)


def update_wiki_counts(
    conn: sqlite3.Connection,
    *,
    slug: str,
    page_count: int,
    source_count: int,
    updated: str | None = None,
) -> None:
    """Update projected page/source counters in the registry."""

    conn.execute(
        """
        UPDATE wikis
        SET page_count = ?, source_count = ?, updated = ?
        WHERE slug = ?
        """,
        (page_count, source_count, updated or _utc_now(), slug),
    )


def archive_wiki(
    conn: sqlite3.Connection,
    *,
    slug: str,
    archived_at: str | None = None,
) -> None:
    """Mark a wiki archived without deleting any files."""

    at = archived_at or _utc_now()
    conn.execute(
        "UPDATE wikis SET archived = 1, archived_at = ?, updated = ? WHERE slug = ?",
        (at, at, slug),
    )


def unarchive_wiki(conn: sqlite3.Connection, *, slug: str) -> None:
    """Reverse a registry archive marker."""

    conn.execute(
        "UPDATE wikis SET archived = 0, archived_at = NULL, updated = ? WHERE slug = ?",
        (_utc_now(), slug),
    )


def upsert_page(
    conn: sqlite3.Connection,
    *,
    id: str,
    title: str,
    type: str,
    created: str,
    updated: str,
    tags: JsonList = None,
    sources: JsonList = None,
    confidence: str = "medium",
    contested: int = 0,
    contradictions: str | None = None,
    author: str | None = None,
    author_kind: str | None = None,
    sha256: str | None = None,
    word_count: int | None = None,
    inbound_links: int = 0,
    snippet: str | None = None,
    body_text: str | None = None,
    search_text: str | None = None,
    archived: int = 0,
) -> RowDict:
    """Create or update a projected Wiki Page row."""

    tags_json = _json_dump(tags)
    sources_json = _json_dump(sources)
    projected_search_text = search_text or normalize_search_text(title, tags or [], body_text)
    conn.execute(
        """
        INSERT INTO pages (
            id, title, type, created, updated, tags, sources, confidence,
            contested, contradictions, author, author_kind, sha256, word_count,
            inbound_links, snippet, body_text, search_text, archived
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title,
            type = excluded.type,
            created = excluded.created,
            updated = excluded.updated,
            tags = excluded.tags,
            sources = excluded.sources,
            confidence = excluded.confidence,
            contested = excluded.contested,
            contradictions = excluded.contradictions,
            author = excluded.author,
            author_kind = excluded.author_kind,
            sha256 = excluded.sha256,
            word_count = excluded.word_count,
            inbound_links = excluded.inbound_links,
            snippet = excluded.snippet,
            body_text = excluded.body_text,
            search_text = excluded.search_text,
            archived = excluded.archived
        """,
        (
            id,
            title,
            type,
            created,
            updated,
            tags_json,
            sources_json,
            confidence,
            contested,
            contradictions,
            author,
            author_kind,
            sha256,
            word_count if word_count is not None else _word_count(body_text),
            inbound_links,
            snippet,
            body_text,
            projected_search_text,
            archived,
        ),
    )
    page = get_page(conn, id)
    if page is None:  # pragma: no cover - SQLite would have raised first
        raise RuntimeError(f"failed to upsert page {id!r}")
    return page


def get_page(conn: sqlite3.Connection, page_id: str) -> RowDict | None:
    """Return a projected Wiki Page row."""

    return _row_dict(
        conn.execute("SELECT * FROM pages WHERE id = ?", (page_id,)).fetchone(),
        json_fields={"tags", "sources"},
    )


def list_pages(
    conn: sqlite3.Connection,
    *,
    page_type: str | None = None,
    tag: str | None = None,
    include_archived: bool = False,
) -> list[RowDict]:
    """List projected pages with optional type/tag filtering."""

    clauses: list[str] = []
    params: list[Any] = []
    if not include_archived:
        clauses.append("archived = 0")
    if page_type is not None:
        clauses.append("type = ?")
        params.append(page_type)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = _rows(
        conn.execute(f"SELECT * FROM pages {where} ORDER BY id", params),
        json_fields={"tags", "sources"},
    )
    if tag is None:
        return rows
    return [row for row in rows if tag in (row.get("tags") or [])]


def delete_page(conn: sqlite3.Connection, page_id: str) -> None:
    """Delete a projected Wiki Page row and its FTS entry via trigger."""

    conn.execute("DELETE FROM pages WHERE id = ?", (page_id,))


def replace_page_links(
    conn: sqlite3.Connection,
    *,
    source_page_id: str,
    target_page_ids: Sequence[str],
) -> None:
    """Replace one source page's projected outgoing page-link index rows."""

    conn.execute("DELETE FROM page_links WHERE source_page_id = ?", (source_page_id,))
    seen: set[str] = set()
    for target_page_id in target_page_ids:
        clean_target = str(target_page_id).strip().removesuffix(".md")
        if not clean_target or clean_target in seen or clean_target == source_page_id:
            continue
        seen.add(clean_target)
        conn.execute(
            """
            INSERT OR IGNORE INTO page_links (source_page_id, target_page_id)
            VALUES (?, ?)
            """,
            (source_page_id, clean_target),
        )


def list_inbound_page_links(
    conn: sqlite3.Connection,
    *,
    target_page_id: str,
    include_archived: bool = False,
) -> list[RowDict]:
    """Return projected page rows that link to ``target_page_id``."""

    archived_clause = "" if include_archived else "AND pages.archived = 0"
    return _rows(
        conn.execute(
            f"""
            SELECT pages.*
            FROM page_links
            JOIN pages ON pages.id = page_links.source_page_id
            WHERE page_links.target_page_id = ? {archived_clause}
            ORDER BY pages.id
            """,
            (target_page_id,),
        ),
        json_fields={"tags", "sources"},
    )


def page_facets(conn: sqlite3.Connection, *, include_archived: bool = False) -> RowDict:
    """Return unique page filter values from projected columns without row payloads."""

    archived_clause = "" if include_archived else "WHERE archived = 0"
    types = [
        str(row["type"])
        for row in conn.execute(
            f"""
            SELECT DISTINCT type
            FROM pages
            {archived_clause}
            ORDER BY type
            """
        )
        if row["type"]
    ]
    tag_rows = conn.execute(f"SELECT tags FROM pages {archived_clause}").fetchall()
    tags = sorted(
        {
            str(tag)
            for row in tag_rows
            for tag in (_json_load(row["tags"]) or [])
            if str(tag).strip()
        }
    )
    return {"types": types, "tags": tags}


def search_pages(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 5,
    include_archived: bool = False,
) -> list[RowDict]:
    """Search projected pages with FTS5 BM25 ranking."""

    if limit <= 0 or not query.strip():
        return []
    archived_clause = "" if include_archived else "AND pages.archived = 0"
    rows = _rows(
        conn.execute(
            f"""
            SELECT
                pages.*,
                bm25(pages_fts) AS rank,
                snippet(pages_fts, 4, '', '', '…', 32) AS context
            FROM pages_fts
            JOIN pages ON pages.rowid = pages_fts.rowid
            WHERE pages_fts MATCH ? {archived_clause}
            ORDER BY rank ASC, pages.id ASC
            LIMIT ?
            """,
            (query, limit),
        ),
        json_fields={"tags", "sources"},
    )
    return rows


def insert_ingest_log(
    conn: sqlite3.Connection,
    *,
    ingested_at: str,
    source_type: str | None,
    source_url: str | None,
    source_path: str | Path | None,
    sha256: str | None,
    pages_created: JsonList,
    pages_updated: JsonList,
    drift_detected: int = 0,
    author: str | None = None,
    author_kind: str | None = None,
) -> RowDict:
    """Insert an ingest log row and return it."""

    cursor = conn.execute(
        """
        INSERT INTO ingest_log (
            ingested_at, source_type, source_url, source_path, sha256,
            pages_created, pages_updated, drift_detected, author, author_kind
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ingested_at,
            source_type,
            source_url,
            str(source_path) if source_path is not None else None,
            sha256,
            _json_dump(pages_created),
            _json_dump(pages_updated),
            drift_detected,
            author,
            author_kind,
        ),
    )
    return _row_dict(
        conn.execute("SELECT * FROM ingest_log WHERE id = ?", (cursor.lastrowid,)).fetchone(),
        json_fields={"pages_created", "pages_updated"},
    ) or {}


def list_ingest_log(conn: sqlite3.Connection) -> list[RowDict]:
    """Return ingest log rows in insertion order."""

    return _rows(
        conn.execute("SELECT * FROM ingest_log ORDER BY id"),
        json_fields={"pages_created", "pages_updated"},
    )


def upsert_source(
    conn: sqlite3.Connection,
    *,
    id: str,
    ingested_at: str | None,
    sha256: str | None,
    source_url: str | None,
    source_path: str | Path | None,
    version: int = 1,
    previous_source_id: str | None = None,
    is_latest: int = 1,
    classified_as: str | None = None,
) -> RowDict:
    """Create or update a versioned raw-source projection row."""

    conn.execute(
        """
        INSERT INTO sources (
            id, ingested_at, sha256, source_url, source_path, version,
            previous_source_id, is_latest, classified_as
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            ingested_at = excluded.ingested_at,
            sha256 = excluded.sha256,
            source_url = excluded.source_url,
            source_path = excluded.source_path,
            version = excluded.version,
            previous_source_id = excluded.previous_source_id,
            is_latest = excluded.is_latest,
            classified_as = excluded.classified_as
        """,
        (
            id,
            ingested_at,
            sha256,
            source_url,
            str(source_path) if source_path is not None else None,
            version,
            previous_source_id,
            is_latest,
            classified_as,
        ),
    )
    source = get_source(conn, id)
    if source is None:  # pragma: no cover - SQLite would have raised first
        raise RuntimeError(f"failed to upsert source {id!r}")
    return source


def get_source(conn: sqlite3.Connection, source_id: str) -> RowDict | None:
    """Return a source projection row."""

    return _row_dict(conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone())


def mark_source_not_latest(conn: sqlite3.Connection, source_id: str) -> None:
    """Mark an existing source version as superseded."""

    conn.execute("UPDATE sources SET is_latest = 0 WHERE id = ?", (source_id,))


def add_taxonomy_tag(conn: sqlite3.Connection, *, tag: str, created: str | None = None) -> RowDict:
    """Add a taxonomy tag projection row."""

    conn.execute(
        """
        INSERT INTO taxonomy (tag, created)
        VALUES (?, ?)
        ON CONFLICT(tag) DO UPDATE SET created = excluded.created
        """,
        (tag, created or _utc_now()),
    )
    return _row_dict(conn.execute("SELECT * FROM taxonomy WHERE tag = ?", (tag,)).fetchone()) or {}


def list_taxonomy(conn: sqlite3.Connection) -> list[RowDict]:
    """List taxonomy rows."""

    return _rows(conn.execute("SELECT * FROM taxonomy ORDER BY tag"))


def upsert_trusted_plugin(
    conn: sqlite3.Connection,
    *,
    name: str,
    kind: str,
    path: str | Path,
    sha256: str,
    trusted_at: str,
    author: str | None = None,
    author_kind: str | None = None,
) -> RowDict:
    """Create or update a trusted plugin projection row."""

    conn.execute(
        """
        INSERT INTO trusted_plugins (
            name, kind, path, sha256, trusted_at, author, author_kind
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name, kind) DO UPDATE SET
            path = excluded.path,
            sha256 = excluded.sha256,
            trusted_at = excluded.trusted_at,
            author = excluded.author,
            author_kind = excluded.author_kind
        """,
        (name, kind, str(path), sha256, trusted_at, author, author_kind),
    )
    return _row_dict(
        conn.execute(
            "SELECT * FROM trusted_plugins WHERE name = ? AND kind = ?",
            (name, kind),
        ).fetchone()
    ) or {}


def list_trusted_plugins(conn: sqlite3.Connection) -> list[RowDict]:
    """List trusted plugin projection rows."""

    return _rows(conn.execute("SELECT * FROM trusted_plugins ORDER BY kind, name"))


def upsert_kanban_ref(
    conn: sqlite3.Connection,
    *,
    page_id: str,
    task_id: str,
    direction: str,
    created: str | None = None,
) -> RowDict:
    """Create or update a wiki-owned kanban reference projection row."""

    conn.execute(
        """
        INSERT INTO kanban_refs (page_id, task_id, direction, created)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(page_id, task_id, direction) DO UPDATE SET
            created = excluded.created
        """,
        (page_id, task_id, direction, created or _utc_now()),
    )
    return _row_dict(
        conn.execute(
            """
            SELECT * FROM kanban_refs
            WHERE page_id = ? AND task_id = ? AND direction = ?
            """,
            (page_id, task_id, direction),
        ).fetchone()
    ) or {}


def list_kanban_refs(
    conn: sqlite3.Connection,
    *,
    page_id: str | None = None,
    task_id: str | None = None,
) -> list[RowDict]:
    """List kanban reference projection rows."""

    clauses: list[str] = []
    params: list[str] = []
    if page_id is not None:
        clauses.append("page_id = ?")
        params.append(page_id)
    if task_id is not None:
        clauses.append("task_id = ?")
        params.append(task_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return _rows(
        conn.execute(
            f"SELECT * FROM kanban_refs {where} ORDER BY page_id, task_id, direction",
            params,
        )
    )


def upsert_projection_version(
    conn: sqlite3.Connection,
    *,
    version_id: str,
    created: str,
    schema_version: str,
    source_tree_sha256: str,
    db_sha256: str | None = None,
    previous_version_id: str | None = None,
    rebuild_reason: str | None = None,
    status: str,
    notes: str | None = None,
    author: str | None = None,
    author_kind: str | None = None,
) -> RowDict:
    """Create or update a projection version row."""

    conn.execute(
        """
        INSERT INTO projection_versions (
            version_id, created, schema_version, source_tree_sha256, db_sha256,
            previous_version_id, rebuild_reason, status, notes, author, author_kind
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(version_id) DO UPDATE SET
            created = excluded.created,
            schema_version = excluded.schema_version,
            source_tree_sha256 = excluded.source_tree_sha256,
            db_sha256 = excluded.db_sha256,
            previous_version_id = excluded.previous_version_id,
            rebuild_reason = excluded.rebuild_reason,
            status = excluded.status,
            notes = excluded.notes,
            author = excluded.author,
            author_kind = excluded.author_kind
        """,
        (
            version_id,
            created,
            schema_version,
            source_tree_sha256,
            db_sha256,
            previous_version_id,
            rebuild_reason,
            status,
            notes,
            author,
            author_kind,
        ),
    )
    return _row_dict(
        conn.execute(
            "SELECT * FROM projection_versions WHERE version_id = ?",
            (version_id,),
        ).fetchone()
    ) or {}


def list_projection_versions(conn: sqlite3.Connection) -> list[RowDict]:
    """List projection versions in creation order."""

    return _rows(conn.execute("SELECT * FROM projection_versions ORDER BY created, version_id"))


__all__ = [
    "SCHEMA_VERSION",
    "add_taxonomy_tag",
    "archive_wiki",
    "connect_registry",
    "connect_wiki",
    "delete_page",
    "get_page",
    "get_source",
    "get_wiki",
    "initialize_registry",
    "initialize_wiki",
    "insert_ingest_log",
    "list_inbound_page_links",
    "list_ingest_log",
    "list_kanban_refs",
    "list_pages",
    "list_projection_versions",
    "list_taxonomy",
    "list_trusted_plugins",
    "list_wikis",
    "mark_source_not_latest",
    "normalize_search_text",
    "page_facets",
    "rebuild_pages_fts",
    "registry_tables",
    "replace_page_links",
    "search_pages",
    "unarchive_wiki",
    "update_wiki_counts",
    "upsert_kanban_ref",
    "upsert_page",
    "upsert_projection_version",
    "upsert_source",
    "upsert_trusted_plugin",
    "upsert_wiki",
    "wiki_tables",
]
