"""Tests for versioned wiki projection rebuilds."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from hermes_wiki import db, projection


def _write_page(
    path: Path,
    *,
    title: str = "Agent Memory",
    page_type: str = "concept",
    body: str = "Agent memory systems retain context across sessions.",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "---",
                f"title: {title}",
                f"type: {page_type}",
                "created: 2026-06-05T00:00:00Z",
                "updated: 2026-06-05T00:00:00Z",
                "tags: [agents, memory]",
                "sources: [raw/articles/memory.md]",
                "author: tester",
                "author_kind: human",
                "---",
                "",
                f"# {title}",
                body,
                "",
            ]
        ),
        encoding="utf-8",
    )


def _seed_prior_db(wiki_root: Path) -> bytes:
    wiki_db = wiki_root / "wiki.db"
    with db.connect_wiki(wiki_db) as conn:
        db.initialize_wiki(conn)
        db.upsert_page(
            conn,
            id="concepts/old-page",
            title="Old Page",
            type="concept",
            created="2026-06-04T00:00:00Z",
            updated="2026-06-04T00:00:00Z",
            body_text="old projection content",
        )
        db.upsert_projection_version(
            conn,
            version_id="old-active",
            created="2026-06-04T00:00:00Z",
            schema_version=db.SCHEMA_VERSION,
            source_tree_sha256="old-tree",
            db_sha256="old-db",
            previous_version_id=None,
            rebuild_reason="initial",
            status="active",
        )
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return wiki_db.read_bytes()


def _manifest_rows(wiki_root: Path) -> list[dict[str, object]]:
    manifest = wiki_root / "db_versions" / "manifest.jsonl"
    return [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]


def test_successful_rebuild_snapshots_manifest_versions_and_atomically_swaps(
    tmp_path: Path,
) -> None:
    """A valid rebuild snapshots the old DB and swaps in a versioned active projection."""
    wiki_root = tmp_path / "wiki"
    wiki_root.mkdir()
    prior_bytes = _seed_prior_db(wiki_root)
    _write_page(wiki_root / "concepts" / "agent-memory.md")

    result = projection.rebuild_projection(
        wiki_root,
        rebuild_reason="manual",
        author="tester",
        author_kind="human",
    )

    assert result.status == "active"
    assert result.previous_version_id == "old-active"
    assert result.snapshot_path is not None
    assert result.snapshot_path.read_bytes() == prior_bytes
    assert not (wiki_root / "wiki.db.tmp").exists()

    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        page = db.get_page(conn, "concepts/agent-memory")
        assert page is not None
        assert page["title"] == "Agent Memory"
        assert page["tags"] == ["agents", "memory"]
        assert page["sha256"] == projection.sha256_file(wiki_root / "concepts" / "agent-memory.md")
        assert db.get_page(conn, "concepts/old-page") is None
        versions = {row["version_id"]: row for row in db.list_projection_versions(conn)}

    assert versions["old-active"]["status"] == "superseded"
    active = versions[result.version_id]
    assert active["status"] == "active"
    assert active["rebuild_reason"] == "manual"
    assert active["previous_version_id"] == "old-active"
    assert active["source_tree_sha256"] == result.source_tree_sha256
    assert active["db_sha256"] == result.db_sha256

    manifest_rows = _manifest_rows(wiki_root)
    assert manifest_rows == [
        {
            "version_id": result.version_id,
            "created": result.created,
            "schema_version": db.SCHEMA_VERSION,
            "source_tree_sha256": result.source_tree_sha256,
            "db_sha256": result.db_sha256,
            "previous_version_id": "old-active",
            "rebuild_reason": "manual",
            "status": "active",
            "notes": None,
            "author": "tester",
            "author_kind": "human",
            "snapshot_path": result.snapshot_path.relative_to(wiki_root).as_posix(),
        }
    ]

    gitignore = (wiki_root / ".gitignore").read_text(encoding="utf-8")
    assert "wiki.db\n" in gitignore
    assert "wiki.db.tmp\n" in gitignore
    assert "db_versions/*.db\n" in gitignore
    assert "!db_versions/manifest.jsonl\n" in gitignore


def test_rebuild_reprojects_source_rows_from_page_frontmatter_without_prior_db(
    tmp_path: Path,
) -> None:
    """A missing projection rebuild keeps source metadata derived from durable files."""

    wiki_root = tmp_path / "wiki"
    wiki_root.mkdir()
    raw_source = wiki_root / "raw" / "articles" / "memory.md"
    raw_source.parent.mkdir(parents=True)
    raw_source.write_text("# Memory\n\nSource bytes.", encoding="utf-8")
    _write_page(wiki_root / "concepts" / "agent-memory.md")

    result = projection.rebuild_projection(wiki_root, rebuild_reason="initial")

    assert result.status == "active"
    with sqlite3.connect(wiki_root / "wiki.db") as conn:
        conn.row_factory = sqlite3.Row
        source = conn.execute("SELECT * FROM sources").fetchone()
    assert source is not None
    assert source["id"] == "raw/articles/memory.md"
    assert source["source_path"] == "raw/articles/memory.md"
    assert source["classified_as"] == "article"
    assert source["version"] == 1
    assert source["is_latest"] == 1
    assert source["sha256"] == projection.sha256_file(raw_source)


def test_failed_validation_retains_prior_db_and_records_failed_version(tmp_path: Path) -> None:
    """Validation failures keep the prior projection current and append a failed version row."""
    wiki_root = tmp_path / "wiki"
    wiki_root.mkdir()
    _seed_prior_db(wiki_root)
    broken_page = wiki_root / "concepts" / "broken.md"
    broken_page.parent.mkdir(parents=True, exist_ok=True)
    broken_page.write_text(
        "\n".join(
            [
                "---",
                "title: Broken Page",
                "created: 2026-06-05T00:00:00Z",
                "updated: 2026-06-05T00:00:00Z",
                "---",
                "",
                "# Broken Page",
                "This page is missing its required type field.",
            ]
        ),
        encoding="utf-8",
    )

    result = projection.rebuild_projection(wiki_root, rebuild_reason="manual")

    assert result.status == "failed"
    assert result.previous_version_id == "old-active"
    assert result.snapshot_path is not None
    assert result.snapshot_path.exists()
    assert "missing required frontmatter field: type" in (result.notes or "")
    assert not (wiki_root / "wiki.db.tmp").exists()

    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        assert db.get_page(conn, "concepts/old-page") is not None
        assert db.get_page(conn, "concepts/broken") is None
        versions = {row["version_id"]: row for row in db.list_projection_versions(conn)}

    assert versions["old-active"]["status"] == "active"
    failed = versions[result.version_id]
    assert failed["status"] == "failed"
    assert failed["rebuild_reason"] == "manual"
    assert failed["previous_version_id"] == "old-active"
    assert failed["db_sha256"] is None

    manifest_rows = _manifest_rows(wiki_root)
    assert len(manifest_rows) == 1
    assert manifest_rows[0]["version_id"] == result.version_id
    assert manifest_rows[0]["status"] == "failed"
    assert manifest_rows[0]["previous_version_id"] == "old-active"
    assert manifest_rows[0]["snapshot_path"] == result.snapshot_path.relative_to(
        wiki_root
    ).as_posix()


def test_rebuild_initializes_failed_version_db_when_no_prior_db_exists(tmp_path: Path) -> None:
    """An initial validation failure still creates a schema DB with a failed version row."""
    wiki_root = tmp_path / "wiki"
    wiki_root.mkdir()
    _write_page(wiki_root / "concepts" / "broken.md", title="", page_type="concept")

    result = projection.rebuild_projection(wiki_root, rebuild_reason="initial")

    assert result.status == "failed"
    assert result.previous_version_id is None
    with sqlite3.connect(wiki_root / "wiki.db") as conn:
        row = conn.execute(
            "SELECT status FROM projection_versions WHERE version_id = ?",
            (result.version_id,),
        ).fetchone()
    assert row == ("failed",)
