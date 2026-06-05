"""Health/lint checks for rebuildable wiki projections."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hermes_wiki import db, git_ops, projection
from hermes_wiki.management import WikiManagementError, ensure_wiki_mutable, resolved_author


@dataclass(frozen=True, slots=True)
class LintReport:
    """Structured lint result for CLI/API consumers."""

    wiki: str
    status: str
    findings: list[dict[str, Any]]
    rebuild: dict[str, Any] | None
    commit_id: str | None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable report."""

        return {
            "wiki": self.wiki,
            "status": self.status,
            "findings": self.findings,
            "rebuild": self.rebuild,
            "commit_id": self.commit_id,
        }

    def to_json(self) -> str:
        """Serialize the report as deterministic JSON."""

        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def lint_wiki(
    *,
    slug: str | None = None,
    profile: str | None = None,
    author: str | None = None,
) -> LintReport:
    """Inspect and repair a wiki projection, reporting any pre-repair drift."""

    resolved = ensure_wiki_mutable(slug=slug, profile=profile)
    acting_author = resolved_author(author)
    findings = projection_findings(resolved.path)
    rebuild_result: projection.ProjectionRebuildResult | None = None
    commit_id: str | None = None

    if findings:
        rebuild_result = projection.rebuild_projection(
            resolved.path,
            rebuild_reason="lint-repair",
            author=acting_author,
            author_kind="human",
        )
        if rebuild_result.status == "failed":
            findings.append(
                _finding(
                    "projection_rebuild_failed",
                    "high",
                    f"projection rebuild failed: {rebuild_result.notes}",
                )
            )
        commit_id = _commit_rebuild_if_needed(resolved.path, author=acting_author)

    if rebuild_result is not None and rebuild_result.status == "failed":
        status = "failed"
    elif findings:
        status = "repaired"
    else:
        status = "clean"
    return LintReport(
        wiki=resolved.slug,
        status=status,
        findings=findings,
        rebuild=None if rebuild_result is None else _rebuild_dict(rebuild_result),
        commit_id=commit_id,
    )


def projection_findings(wiki_root: Path | str) -> list[dict[str, Any]]:
    """Return projection/file cross-consistency findings before repair."""

    root = Path(wiki_root)
    wiki_db = root / "wiki.db"
    if not wiki_db.exists():
        return [_finding("projection_missing", "high", "wiki.db is missing; rebuilding from files")]

    try:
        with db.connect_wiki(wiki_db) as conn:
            db.initialize_wiki(conn)
            integrity_row = conn.execute("PRAGMA integrity_check").fetchone()
            if integrity_row is None or integrity_row[0] != "ok":
                return [
                    _finding(
                        "projection_corrupt",
                        "high",
                        f"wiki.db failed PRAGMA integrity_check: {integrity_row}",
                    )
                ]
            return _compare_projection_to_files(root, conn)
    except sqlite3.DatabaseError as exc:
        return [
            _finding(
                "projection_corrupt",
                "high",
                f"wiki.db is not a readable SQLite projection; rebuilding from files: {exc}",
            )
        ]


def ensure_projection_current(
    wiki_root: Path | str,
    *,
    author: str | None = None,
) -> projection.ProjectionRebuildResult | None:
    """Repair a missing/corrupt projection for read commands without printing lint output."""

    root = Path(wiki_root)
    findings = [
        finding
        for finding in projection_findings(root)
        if finding["code"] in {"projection_missing", "projection_corrupt"}
    ]
    if not findings:
        return None
    acting_author = resolved_author(author)
    result = projection.rebuild_projection(
        root,
        rebuild_reason="lint-repair",
        author=acting_author,
        author_kind="human",
    )
    _commit_rebuild_if_needed(root, author=acting_author)
    if result.status != "active":
        raise WikiManagementError(f"projection rebuild failed: {result.notes}")
    return result


def _compare_projection_to_files(
    wiki_root: Path,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    try:
        file_pages = {
            page.id: page for page in (
                projection._page_projection_from_file(wiki_root, page_file)
                for page_file in projection._iter_page_files(wiki_root)
            )
        }
    except projection.ProjectionValidationError as exc:
        return [_finding("projection_invalid_file", "high", str(exc))]

    db_pages = {str(row["id"]): row for row in db.list_pages(conn, include_archived=True)}
    file_ids = set(file_pages)
    db_ids = set(db_pages)
    for page_id in sorted(file_ids - db_ids):
        findings.append(
            _finding(
                "projection_mismatch",
                "high",
                f"page {page_id} exists on disk but is missing from wiki.db",
                page_id=page_id,
                field="id",
            )
        )
    for page_id in sorted(db_ids - file_ids):
        findings.append(
            _finding(
                "projection_mismatch",
                "high",
                f"page {page_id} exists in wiki.db but has no Markdown file",
                page_id=page_id,
                field="id",
            )
        )
    for page_id in sorted(file_ids & db_ids):
        page = file_pages[page_id]
        row = db_pages[page_id]
        checks = {
            "title": page.title,
            "type": page.type,
            "created": page.created,
            "updated": page.updated,
            "tags": page.tags,
            "sources": page.sources,
            "sha256": page.sha256,
            "body_text": page.body_text,
        }
        for field, expected in checks.items():
            if row.get(field) != expected:
                findings.append(
                    _finding(
                        "projection_mismatch",
                        "high",
                        f"page {page_id} field {field} differs between files and wiki.db",
                        page_id=page_id,
                        field=field,
                    )
                )
                break

    findings.extend(_version_findings(wiki_root, conn))
    return findings


def _version_findings(wiki_root: Path, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    active_rows = conn.execute(
        "SELECT * FROM projection_versions WHERE status='active' ORDER BY created, version_id"
    ).fetchall()
    if len(active_rows) != 1:
        return [
            _finding(
                "projection_version_mismatch",
                "high",
                f"expected exactly one active projection version, found {len(active_rows)}",
            )
        ]
    active = active_rows[0]
    findings: list[dict[str, Any]] = []
    expected_tree = projection.source_tree_sha256(wiki_root)
    if active["source_tree_sha256"] != expected_tree:
        findings.append(
            _finding(
                "projection_version_mismatch",
                "high",
                "active projection source_tree_sha256 does not match files",
                field="source_tree_sha256",
            )
        )
    db_hash = active["db_sha256"]
    if not db_hash:
        findings.append(
            _finding(
                "projection_version_mismatch",
                "high",
                "active projection db_sha256 is missing",
                field="db_sha256",
            )
        )
    else:
        expected_db_hash = projection.projection_db_sha256(wiki_root / "wiki.db")
        if db_hash != expected_db_hash:
            findings.append(
                _finding(
                    "projection_version_mismatch",
                    "high",
                    "active projection db_sha256 does not match finalized DB contents",
                    field="db_sha256",
                )
            )
    return findings


def _finding(
    code: str,
    severity: str,
    message: str,
    *,
    page_id: str | None = None,
    field: str | None = None,
) -> dict[str, Any]:
    finding: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    if page_id is not None:
        finding["page_id"] = page_id
    if field is not None:
        finding["field"] = field
    return finding


def _rebuild_dict(result: projection.ProjectionRebuildResult) -> dict[str, Any]:
    return {
        "version_id": result.version_id,
        "created": result.created,
        "status": result.status,
        "rebuild_reason": result.rebuild_reason,
        "source_tree_sha256": result.source_tree_sha256,
        "db_sha256": result.db_sha256,
        "previous_version_id": result.previous_version_id,
        "snapshot_path": None
        if result.snapshot_path is None
        else result.snapshot_path.relative_to(result.manifest_path.parent.parent).as_posix(),
        "manifest_path": result.manifest_path.as_posix(),
        "notes": result.notes,
    }


def _commit_rebuild_if_needed(wiki_root: Path, *, author: str) -> str | None:
    try:
        commit = git_ops.commit_change(
            wiki_root,
            action="rebuild",
            what="projection",
            author=author,
        )
    except git_ops.GitOpsError as exc:
        if "nothing to commit" in str(exc):
            return None
        raise
    return commit.commit_id


__all__ = [
    "LintReport",
    "ensure_projection_current",
    "lint_wiki",
    "projection_findings",
]
