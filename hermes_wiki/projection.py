"""Versioned rebuild/swap support for per-wiki SQLite projections."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from hermes_wiki import db, git_ops

ALLOWED_REBUILD_REASONS = {"initial", "ingest", "lint-repair", "migration", "manual"}
PAGE_DIR_TYPES = {
    "entities": "entity",
    "concepts": "concept",
    "comparisons": "comparison",
    "queries": "query",
    "sources": "source",
    "summaries": "summary",
}
PROJECTION_GITIGNORE_MARKER = git_ops.GITIGNORE_MARKER
PROJECTION_GITIGNORE_ENTRIES = git_ops.GITIGNORE_ENTRIES


@dataclass(frozen=True, slots=True)
class ProjectionRebuildResult:
    """Outcome metadata for a projection rebuild attempt."""

    version_id: str
    created: str
    status: str
    rebuild_reason: str
    source_tree_sha256: str
    db_sha256: str | None
    previous_version_id: str | None
    snapshot_path: Path | None
    manifest_path: Path
    notes: str | None


@dataclass(frozen=True, slots=True)
class _PageProjection:
    id: str
    path: Path
    metadata: dict[str, Any]
    title: str
    type: str
    created: str
    updated: str
    tags: list[str]
    sources: list[str]
    confidence: str
    contested: int
    contradictions: str | None
    author: str | None
    author_kind: str | None
    sha256: str
    inbound_links: int
    snippet: str | None
    body_text: str


class ProjectionValidationError(ValueError):
    """Raised when a rebuilt projection does not match the filesystem."""


def rebuild_projection(
    wiki_root: Path | str,
    *,
    rebuild_reason: str,
    author: str | None = None,
    author_kind: str | None = None,
) -> ProjectionRebuildResult:
    """Rebuild ``wiki.db`` through a validated tmp DB and atomic swap.

    Validation failures do not raise: the prior ``wiki.db`` remains the active
    projection and receives a ``projection_versions`` row with ``status='failed'``.
    Unexpected filesystem/SQLite errors are allowed to raise because they may
    require operator intervention.
    """

    if rebuild_reason not in ALLOWED_REBUILD_REASONS:
        allowed = ", ".join(sorted(ALLOWED_REBUILD_REASONS))
        raise ValueError(
            f"unsupported rebuild_reason {rebuild_reason!r}; expected one of {allowed}"
        )

    root = Path(wiki_root)
    root.mkdir(parents=True, exist_ok=True)
    with _rebuild_lock(root):
        return _rebuild_projection_locked(
            root,
            rebuild_reason=rebuild_reason,
            author=author,
            author_kind=author_kind,
        )


def _rebuild_projection_locked(
    root: Path,
    *,
    rebuild_reason: str,
    author: str | None,
    author_kind: str | None,
) -> ProjectionRebuildResult:
    db_versions_dir = root / "db_versions"
    db_versions_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = db_versions_dir / "manifest.jsonl"
    ensure_projection_gitignore(root)

    created_dt = datetime.now(UTC)
    timestamp = created_dt.strftime("%Y%m%dT%H%M%S%fZ")
    created = created_dt.isoformat(timespec="microseconds").replace("+00:00", "Z")
    version_id = f"projection-{timestamp}"
    wiki_db_path = root / "wiki.db"
    tmp_db_path = root / "wiki.db.tmp"
    previous_version_id = _latest_active_version_id(wiki_db_path)
    source_tree_hash = source_tree_sha256(root)

    _remove_sqlite_file(tmp_db_path)
    try:
        expected_pages = _build_tmp_projection(
            root,
            tmp_db_path,
            previous_version_id=previous_version_id,
        )
        _validate_tmp_projection(tmp_db_path, expected_pages)
    except ProjectionValidationError as exc:
        _remove_sqlite_file(tmp_db_path)
        notes = str(exc)
        _record_projection_version(
            wiki_db_path,
            version_id=version_id,
            created=created,
            source_tree_sha256=source_tree_hash,
            db_sha256=None,
            previous_version_id=previous_version_id,
            rebuild_reason=rebuild_reason,
            status="failed",
            notes=notes,
            author=author,
            author_kind=author_kind,
        )
        snapshot_path = _snapshot_current_db(wiki_db_path, db_versions_dir, timestamp)
        result = ProjectionRebuildResult(
            version_id=version_id,
            created=created,
            status="failed",
            rebuild_reason=rebuild_reason,
            source_tree_sha256=source_tree_hash,
            db_sha256=None,
            previous_version_id=previous_version_id,
            snapshot_path=snapshot_path,
            manifest_path=manifest_path,
            notes=notes,
        )
        _append_manifest_row(
            result,
            schema_version=db.SCHEMA_VERSION,
            author=author,
            author_kind=author_kind,
        )
        return result

    snapshot_path = _snapshot_current_db(wiki_db_path, db_versions_dir, timestamp)
    db_hash = _finalize_success_version(
        tmp_db_path,
        version_id=version_id,
        created=created,
        source_tree_sha256=source_tree_hash,
        previous_version_id=previous_version_id,
        rebuild_reason=rebuild_reason,
        author=author,
        author_kind=author_kind,
    )

    os.replace(tmp_db_path, wiki_db_path)
    _remove_sqlite_sidecars(tmp_db_path)
    if snapshot_path is None:
        snapshot_path = _snapshot_current_db(wiki_db_path, db_versions_dir, timestamp)
    result = ProjectionRebuildResult(
        version_id=version_id,
        created=created,
        status="active",
        rebuild_reason=rebuild_reason,
        source_tree_sha256=source_tree_hash,
        db_sha256=db_hash,
        previous_version_id=previous_version_id,
        snapshot_path=snapshot_path,
        manifest_path=manifest_path,
        notes=None,
    )
    _append_manifest_row(
        result,
        schema_version=db.SCHEMA_VERSION,
        author=author,
        author_kind=author_kind,
    )
    return result


def ensure_projection_gitignore(wiki_root: Path | str) -> Path:
    """Ensure a per-wiki ``.gitignore`` ignores projection binaries only."""

    return git_ops.ensure_gitignore(wiki_root)


def sha256_file(path: Path | str) -> str:
    """Return the SHA-256 digest of a file's bytes."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def projection_db_sha256(path: Path | str) -> str:
    """Return a verifiable checksum of finalized projection DB contents.

    The checksum intentionally excludes the ``projection_versions.db_sha256``
    column values to avoid a self-referential hash. All other projected table
    content and column names are included deterministically, so the stored value
    can be recomputed after the DB has been finalized.
    """

    db_path = Path(path)
    digest = hashlib.sha256()
    tables = (
        "pages",
        "ingest_log",
        "sources",
        "taxonomy",
        "trusted_plugins",
        "kanban_refs",
        "projection_versions",
    )
    with _readonly_sqlite(db_path) as conn:
        for table in tables:
            columns = [str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")]
            if table == "projection_versions":
                selected_columns = [column for column in columns if column != "db_sha256"]
            else:
                selected_columns = columns
            digest.update(table.encode("utf-8"))
            digest.update(b"\0")
            digest.update(json.dumps(selected_columns, separators=(",", ":")).encode("utf-8"))
            digest.update(b"\0")
            order_by = selected_columns[0] if selected_columns else "rowid"
            quoted = ", ".join(f'"{column}"' for column in selected_columns)
            for row in conn.execute(f'SELECT {quoted} FROM "{table}" ORDER BY "{order_by}"'):
                digest.update(
                    json.dumps(
                        [row[column] for column in selected_columns],
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                digest.update(b"\0")
    return digest.hexdigest()


def source_tree_sha256(wiki_root: Path | str) -> str:
    """Hash durable wiki source files, excluding projection artifacts and git internals."""

    root = Path(wiki_root)
    digest = hashlib.sha256()
    source_files = sorted(
        _iter_source_tree_files(root),
        key=lambda item: item.relative_to(root).as_posix(),
    )
    for path in source_files:
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _build_tmp_projection(
    wiki_root: Path,
    tmp_db_path: Path,
    *,
    previous_version_id: str | None,
) -> list[_PageProjection]:
    expected_pages: list[_PageProjection] = []
    with db.connect_wiki(tmp_db_path) as conn:
        db.initialize_wiki(conn)
        _copy_projection_versions(conn, wiki_root / "wiki.db", previous_version_id)
        _copy_support_tables(conn, wiki_root / "wiki.db")
        _project_trusted_plugins_from_schema(conn, wiki_root)
        for page_file in _iter_page_files(wiki_root):
            page = _page_projection_from_file(wiki_root, page_file)
            expected_pages.append(page)
            db.upsert_page(
                conn,
                id=page.id,
                title=page.title,
                type=page.type,
                created=page.created,
                updated=page.updated,
                tags=page.tags,
                sources=page.sources,
                confidence=page.confidence,
                contested=page.contested,
                contradictions=page.contradictions,
                author=page.author,
                author_kind=page.author_kind,
                sha256=page.sha256,
                inbound_links=page.inbound_links,
                snippet=page.snippet,
                body_text=page.body_text,
            )
            _project_kanban_refs_from_page(conn, page)
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return expected_pages


def _copy_support_tables(target: sqlite3.Connection, old_db_path: Path) -> None:
    """Preserve non-page projection rows across page/file rebuilds when possible."""

    if not old_db_path.exists():
        return
    try:
        with db.connect_wiki(old_db_path) as old:
            for row in old.execute("SELECT * FROM sources ORDER BY id"):
                db.upsert_source(
                    target,
                    id=str(row["id"]),
                    ingested_at=row["ingested_at"],
                    sha256=row["sha256"],
                    source_url=row["source_url"],
                    source_path=row["source_path"],
                    version=int(row["version"] or 1),
                    previous_source_id=row["previous_source_id"],
                    is_latest=int(row["is_latest"] or 0),
                    classified_as=row["classified_as"],
                )
            for row in old.execute("SELECT * FROM ingest_log ORDER BY id"):
                target.execute(
                    """
                    INSERT OR REPLACE INTO ingest_log (
                        id, ingested_at, source_type, source_url, source_path, sha256,
                        pages_created, pages_updated, drift_detected, author, author_kind
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"],
                        row["ingested_at"],
                        row["source_type"],
                        row["source_url"],
                        row["source_path"],
                        row["sha256"],
                        row["pages_created"],
                        row["pages_updated"],
                        row["drift_detected"],
                        row["author"],
                        row["author_kind"],
                    ),
                )
            for row in old.execute("SELECT * FROM taxonomy ORDER BY tag"):
                db.add_taxonomy_tag(target, tag=str(row["tag"]), created=row["created"])
    except sqlite3.DatabaseError:
        return


def _project_trusted_plugins_from_schema(target: sqlite3.Connection, wiki_root: Path) -> None:
    from hermes_wiki.trust import project_schema_trust_records

    project_schema_trust_records(wiki_root, target)


def _project_kanban_refs_from_page(
    target: sqlite3.Connection,
    page: _PageProjection,
) -> None:
    for ref in _frontmatter_kanban_refs(page.metadata.get("kanban_refs")):
        task_id = str(ref.get("task_id") or "").strip()
        if not task_id:
            continue
        direction = str(ref.get("direction") or "page->task").strip() or "page->task"
        db.upsert_kanban_ref(
            target,
            page_id=page.id,
            task_id=task_id,
            direction=direction,
            created=str(ref.get("created") or ""),
        )


def _frontmatter_kanban_refs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("task_id") or "").strip()
        direction = str(item.get("direction") or "page->task").strip() or "page->task"
        key = (task_id, direction)
        if not task_id or key in seen:
            continue
        seen.add(key)
        refs.append(dict(item))
    return refs


def _validate_tmp_projection(tmp_db_path: Path, expected_pages: list[_PageProjection]) -> None:
    with db.connect_wiki(tmp_db_path) as conn:
        expected_ids = {page.id for page in expected_pages}
        actual_rows = db.list_pages(conn, include_archived=True)
        actual_ids = {str(row["id"]) for row in actual_rows}
        if actual_ids != expected_ids:
            missing = sorted(expected_ids - actual_ids)
            extra = sorted(actual_ids - expected_ids)
            raise ProjectionValidationError(
                f"page projection mismatch: missing={missing!r} extra={extra!r}"
            )
        for page in expected_pages:
            row = db.get_page(conn, page.id)
            if row is None:
                raise ProjectionValidationError(f"missing projected page row: {page.id}")
            _validate_page_row(page, row)
        fts_count = conn.execute("SELECT count(*) FROM pages_fts").fetchone()[0]
        if fts_count != len(expected_pages):
            raise ProjectionValidationError(
                f"FTS row count mismatch: expected {len(expected_pages)}, got {fts_count}"
            )


def _validate_page_row(page: _PageProjection, row: dict[str, Any]) -> None:
    checks = {
        "title": page.title,
        "type": page.type,
        "created": page.created,
        "updated": page.updated,
        "sha256": page.sha256,
        "inbound_links": page.inbound_links,
        "body_text": page.body_text,
    }
    for key, expected_value in checks.items():
        if row.get(key) != expected_value:
            raise ProjectionValidationError(
                f"{page.id} {key} mismatch: expected {expected_value!r}, got {row.get(key)!r}"
            )
    if row.get("tags") != page.tags:
        raise ProjectionValidationError(f"{page.id} tags mismatch")
    if row.get("sources") != page.sources:
        raise ProjectionValidationError(f"{page.id} sources mismatch")


def _page_projection_from_file(wiki_root: Path, path: Path) -> _PageProjection:
    rel = path.relative_to(wiki_root)
    page_id = rel.with_suffix("").as_posix()
    metadata, body = _read_frontmatter(path)
    title = _required_text(metadata, "title", path)
    page_type = _required_text(metadata, "type", path)
    created = _required_text(metadata, "created", path)
    updated = _required_text(metadata, "updated", path)
    return _PageProjection(
        id=page_id,
        path=path,
        metadata=metadata,
        title=title,
        type=page_type,
        created=created,
        updated=updated,
        tags=_string_list(metadata.get("tags"), field="tags", path=path),
        sources=_string_list(metadata.get("sources"), field="sources", path=path),
        confidence=str(metadata.get("confidence") or "medium"),
        contested=1 if bool(metadata.get("contested", False)) else 0,
        contradictions=_optional_text(metadata.get("contradictions")),
        author=_optional_text(metadata.get("author")),
        author_kind=_optional_text(metadata.get("author_kind")),
        sha256=sha256_file(path),
        inbound_links=_integer(metadata.get("inbound_links"), default=0),
        snippet=_snippet(body),
        body_text=body,
    )


def _read_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ProjectionValidationError(f"{path}: missing required YAML frontmatter")
    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        raise ProjectionValidationError(f"{path}: unterminated YAML frontmatter")
    yaml_text = "\n".join(lines[1:closing_index])
    try:
        loaded = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as exc:
        raise ProjectionValidationError(f"{path}: invalid YAML frontmatter: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ProjectionValidationError(f"{path}: YAML frontmatter must be a mapping")
    body = "\n".join(lines[closing_index + 1 :]).strip()
    return loaded, body


def _required_text(metadata: dict[str, Any], field: str, path: Path) -> str:
    value = metadata.get(field)
    if value is None or str(value).strip() == "":
        raise ProjectionValidationError(f"{path}: missing required frontmatter field: {field}")
    return str(value)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    return str(value)


def _integer(value: Any, *, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ProjectionValidationError(f"frontmatter integer field is invalid: {value!r}") from exc


def _string_list(value: Any, *, field: str, path: Path) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return [str(item) for item in value]
    raise ProjectionValidationError(f"{path}: frontmatter field {field} must be a list or string")


def _snippet(body: str) -> str | None:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:240]
    return None


def _iter_page_files(wiki_root: Path) -> Iterable[Path]:
    for dirname in PAGE_DIR_TYPES:
        directory = wiki_root / dirname
        if directory.exists():
            yield from sorted(directory.rglob("*.md"))


def _iter_source_tree_files(wiki_root: Path) -> Iterable[Path]:
    if not wiki_root.exists():
        return
    for path in wiki_root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(wiki_root)
        if _is_source_tree_excluded(rel):
            continue
        yield path


def _is_source_tree_excluded(rel: Path) -> bool:
    parts = rel.parts
    if not parts:
        return True
    if any(part in {".git", "__pycache__", ".pytest_cache", ".ruff_cache"} for part in parts):
        return True
    if parts[0] == "db_versions":
        return True
    name = parts[-1]
    return name in {
        ".DS_Store",
        ".gitignore",
        "wiki.db.tmp.lock",
        "wiki.db",
        "wiki.db-shm",
        "wiki.db-wal",
        "wiki.db.tmp",
        "wiki.db.tmp-shm",
        "wiki.db.tmp-wal",
    }


def _latest_active_version_id(wiki_db_path: Path) -> str | None:
    if not wiki_db_path.exists():
        return None
    try:
        with _readonly_sqlite(wiki_db_path) as conn:
            row = conn.execute(
                """
                SELECT version_id
                FROM projection_versions
                WHERE status = 'active'
                ORDER BY created DESC, version_id DESC
                LIMIT 1
                """
            ).fetchone()
    except sqlite3.DatabaseError:
        return None
    return None if row is None else str(row["version_id"])


def _copy_projection_versions(
    target_conn: sqlite3.Connection,
    source_db_path: Path,
    previous_version_id: str | None,
) -> None:
    if not source_db_path.exists():
        return
    try:
        with _readonly_sqlite(source_db_path) as source_conn:
            rows = source_conn.execute("SELECT * FROM projection_versions").fetchall()
    except sqlite3.DatabaseError:
        return
    for row in rows:
        status = str(row["status"])
        if previous_version_id is not None and row["version_id"] == previous_version_id:
            status = "superseded"
        db.upsert_projection_version(
            target_conn,
            version_id=str(row["version_id"]),
            created=str(row["created"]),
            schema_version=str(row["schema_version"]),
            source_tree_sha256=str(row["source_tree_sha256"]),
            db_sha256=row["db_sha256"],
            previous_version_id=row["previous_version_id"],
            rebuild_reason=row["rebuild_reason"],
            status=status,
            notes=row["notes"],
            author=row["author"],
            author_kind=row["author_kind"],
        )


def _readonly_sqlite(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _record_projection_version(
    wiki_db_path: Path,
    *,
    version_id: str,
    created: str,
    source_tree_sha256: str,
    db_sha256: str | None,
    previous_version_id: str | None,
    rebuild_reason: str,
    status: str,
    notes: str | None,
    author: str | None,
    author_kind: str | None,
) -> None:
    with db.connect_wiki(wiki_db_path) as conn:
        db.initialize_wiki(conn)
        db.upsert_projection_version(
            conn,
            version_id=version_id,
            created=created,
            schema_version=db.SCHEMA_VERSION,
            source_tree_sha256=source_tree_sha256,
            db_sha256=db_sha256,
            previous_version_id=previous_version_id,
            rebuild_reason=rebuild_reason,
            status=status,
            notes=notes,
            author=author,
            author_kind=author_kind,
        )
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _finalize_success_version(
    tmp_db_path: Path,
    *,
    version_id: str,
    created: str,
    source_tree_sha256: str,
    previous_version_id: str | None,
    rebuild_reason: str,
    author: str | None,
    author_kind: str | None,
) -> str:
    _record_projection_version(
        tmp_db_path,
        version_id=version_id,
        created=created,
        source_tree_sha256=source_tree_sha256,
        db_sha256=None,
        previous_version_id=previous_version_id,
        rebuild_reason=rebuild_reason,
        status="active",
        notes=None,
        author=author,
        author_kind=author_kind,
    )
    db_hash = projection_db_sha256(tmp_db_path)
    _record_projection_version(
        tmp_db_path,
        version_id=version_id,
        created=created,
        source_tree_sha256=source_tree_sha256,
        db_sha256=db_hash,
        previous_version_id=previous_version_id,
        rebuild_reason=rebuild_reason,
        status="active",
        notes=None,
        author=author,
        author_kind=author_kind,
    )
    return db_hash


@contextmanager
def _rebuild_lock(wiki_root: Path) -> Iterator[None]:
    """Serialize projection rebuilds with an advisory file lock."""

    lock_path = wiki_root / "wiki.db.tmp.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _snapshot_current_db(wiki_db_path: Path, db_versions_dir: Path, timestamp: str) -> Path | None:
    if not wiki_db_path.exists():
        return None
    _checkpoint_db_file(wiki_db_path)
    snapshot = _unique_path(db_versions_dir / f"wiki-{timestamp}.db")
    shutil.copy2(wiki_db_path, snapshot)
    return snapshot


def _checkpoint_db_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        with db.connect_wiki(path) as conn:
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.DatabaseError:
        return


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for counter in range(1, 1000):
        candidate = path.with_name(f"{stem}-{counter}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not allocate unique path for {path}")


def _append_manifest_row(
    result: ProjectionRebuildResult,
    *,
    schema_version: str,
    author: str | None,
    author_kind: str | None,
) -> None:
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "version_id": result.version_id,
        "created": result.created,
        "schema_version": schema_version,
        "source_tree_sha256": result.source_tree_sha256,
        "db_sha256": result.db_sha256,
        "previous_version_id": result.previous_version_id,
        "rebuild_reason": result.rebuild_reason,
        "status": result.status,
        "notes": result.notes,
        "author": author,
        "author_kind": author_kind,
        "snapshot_path": None
        if result.snapshot_path is None
        else result.snapshot_path.relative_to(result.manifest_path.parent.parent).as_posix(),
    }
    with result.manifest_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _remove_sqlite_file(path: Path) -> None:
    if path.exists():
        path.unlink()
    _remove_sqlite_sidecars(path)


def _remove_sqlite_sidecars(path: Path) -> None:
    for sidecar in (path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        if sidecar.exists():
            sidecar.unlink()


__all__ = [
    "ALLOWED_REBUILD_REASONS",
    "ProjectionRebuildResult",
    "ProjectionValidationError",
    "ensure_projection_gitignore",
    "projection_db_sha256",
    "rebuild_projection",
    "sha256_file",
    "source_tree_sha256",
]
