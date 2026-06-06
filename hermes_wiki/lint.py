"""Health/lint checks for rebuildable wiki projections."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from hermes_wiki import db, git_ops, projection
from hermes_wiki.attribution import history_block_in_body
from hermes_wiki.frontmatter import FrontmatterError, read_markdown
from hermes_wiki.management import WikiManagementError, ensure_wiki_mutable, resolved_author
from hermes_wiki.pipeline import INBOX_STATUS_REL, MAX_INGEST_BYTES
from hermes_wiki.trust import read_schema_trust_records


@dataclass(frozen=True, slots=True)
class LintReport:
    """Structured lint result for CLI/API consumers."""

    wiki: str
    status: str
    findings: list[dict[str, Any]]
    rebuild: dict[str, Any] | None
    commit_id: str | None
    health_score: float

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable report."""

        return {
            "wiki": self.wiki,
            "status": self.status,
            "findings": self.findings,
            "summary": _summary(self.findings),
            "health_score": self.health_score,
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

    if _should_attempt_rebuild(findings):
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
    elif rebuild_result is not None and findings:
        status = "repaired"
    elif findings:
        status = "issues"
    else:
        status = "clean"
    health_score = _health_score(findings)
    _record_lint_result(resolved.home, resolved.slug, health_score=health_score)
    return LintReport(
        wiki=resolved.slug,
        status=status,
        findings=findings,
        rebuild=None if rebuild_result is None else _rebuild_dict(rebuild_result),
        commit_id=commit_id,
        health_score=health_score,
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
    page_files = list(projection._iter_page_files(wiki_root))
    parsed_pages = [_parse_page_for_lint(wiki_root, page_file) for page_file in page_files]
    for page in parsed_pages:
        findings.extend(_frontmatter_findings(page))
    file_pages = {
        page["id"]: page
        for page in parsed_pages
        if page["id"] and not page.get("invalid_for_projection")
    }

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
        findings.append(
            _finding(
                "cross_consistency",
                "high",
                f"page {page_id} exists on disk but is missing from wiki.db",
                page_id=page_id,
                path=file_pages[page_id]["rel_path"],
            )
        )
    for page_id in sorted(db_ids - file_ids):
        row = db_pages[page_id]
        expected_path = wiki_root / f"{page_id}.md"
        findings.append(
            _finding(
                "projection_mismatch",
                "high",
                f"page {page_id} exists in wiki.db but has no Markdown file",
                page_id=page_id,
                path=expected_path.relative_to(wiki_root).as_posix(),
                field="id",
            )
        )
        findings.append(
            _finding(
                "cross_consistency",
                "high",
                f"page {page_id} exists in wiki.db but has no Markdown file",
                page_id=page_id,
                path=str(row.get("id") or page_id),
            )
        )
    for page_id in sorted(file_ids & db_ids):
        page = file_pages[page_id]
        row = db_pages[page_id]
        checks = {
            "title": page["metadata"].get("title"),
            "type": page["metadata"].get("type"),
            "created": page["metadata"].get("created"),
            "updated": page["metadata"].get("updated"),
            "tags": _string_list(page["metadata"].get("tags")),
            "sources": _string_list(page["metadata"].get("sources")),
            "sha256": projection.sha256_file(page["path"]),
            "body_text": page["body"],
        }
        for field, expected in checks.items():
            if row.get(field) != expected:
                findings.append(
                    _finding(
                        "projection_mismatch",
                        "high",
                        f"page {page_id} field {field} differs between files and wiki.db",
                        page_id=page_id,
                        path=page["rel_path"],
                        field=field,
                    )
                )
                break

    findings.extend(_page_content_findings(wiki_root, parsed_pages, conn))
    findings.extend(_index_findings(wiki_root, parsed_pages, conn))
    findings.extend(_log_findings(wiki_root))
    findings.extend(_source_findings(wiki_root, conn, parsed_pages))
    findings.extend(_kanban_findings(parsed_pages, conn))
    findings.extend(_plugin_findings(wiki_root, conn))
    findings.extend(_inbox_findings(wiki_root))
    findings.extend(_version_findings(wiki_root, conn))
    return findings


def _parse_page_for_lint(wiki_root: Path, path: Path) -> dict[str, Any]:
    rel_path = path.relative_to(wiki_root).as_posix()
    inferred_id = path.relative_to(wiki_root).with_suffix("").as_posix()
    try:
        metadata, body = read_markdown(path)
        frontmatter_error = None
    except FrontmatterError as exc:
        metadata = {}
        body = ""
        frontmatter_error = str(exc)
    page_id = str(metadata.get("id") or inferred_id)
    return {
        "id": page_id,
        "path": path,
        "rel_path": rel_path,
        "metadata": metadata,
        "body": body,
        "frontmatter_error": frontmatter_error,
        "invalid_for_projection": bool(frontmatter_error)
        or any(
            _is_blank(metadata.get(field))
            for field in ("title", "type", "created", "updated")
        ),
    }


def _frontmatter_findings(page: dict[str, Any]) -> list[dict[str, Any]]:
    if page["frontmatter_error"] is not None:
        return [
            _finding(
                "missing_frontmatter_field",
                "high",
                page["frontmatter_error"],
                page_id=page["id"],
                path=page["rel_path"],
                field="frontmatter",
            )
        ]
    findings: list[dict[str, Any]] = []
    for field in ("id", "title", "type", "created", "updated", "author", "author_kind"):
        if _is_blank(page["metadata"].get(field)):
            findings.append(
                _finding(
                    "missing_frontmatter_field",
                    "high",
                    f"page {page['id']} is missing required frontmatter field {field}",
                    page_id=page["id"],
                    path=page["rel_path"],
                    field=field,
                )
            )
    return findings


def _page_content_findings(
    wiki_root: Path,
    pages: list[dict[str, Any]],
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    existing_files = {page["path"].resolve() for page in pages}
    link_counts = {page["id"]: 0 for page in pages if page["id"]}
    for page in pages:
        for target in _markdown_links(page["body"]):
            if _is_external_or_anchor(target):
                continue
            resolved_target = (page["path"].parent / target.split("#", 1)[0]).resolve()
            if resolved_target.suffix != ".md":
                continue
            # Raw Source Snapshots are legitimate non-page markdown evidence files
            # inside the wiki root, so do not flag links to them as broken/orphaned.
            if resolved_target not in existing_files and resolved_target.is_file():
                try:
                    resolved_target.relative_to(wiki_root.resolve())
                except ValueError:
                    pass
                else:
                    continue
            if resolved_target not in existing_files:
                findings.append(
                    _finding(
                        "broken_link",
                        "high",
                        f"page {page['id']} links to missing relative target {target}",
                        page_id=page["id"],
                        path=page["rel_path"],
                        target=target,
                    )
                )
                continue
            target_id = resolved_target.relative_to(wiki_root).with_suffix("").as_posix()
            link_counts[target_id] = link_counts.get(target_id, 0) + 1

    for page in pages:
        if page["frontmatter_error"] is not None:
            continue
        if page["id"] and link_counts.get(page["id"], 0) == 0:
            findings.append(
                _finding(
                    "orphan_page",
                    "medium",
                    f"page {page['id']} has no inbound links",
                    page_id=page["id"],
                    path=page["rel_path"],
                )
            )
        if _has_factual_body(page["body"]) and not _string_list(page["metadata"].get("sources")):
            findings.append(
                _finding(
                    "missing_citation",
                    "high",
                    f"page {page['id']} has factual content but no source citations",
                    page_id=page["id"],
                    path=page["rel_path"],
                )
            )
        stale_marker = _stale_unverified_marker(page["body"])
        if stale_marker is not None:
            findings.append(
                _finding(
                    "stale_unverified",
                    "medium",
                    f"page {page['id']} has an [unverified] marker older than 14 days",
                    page_id=page["id"],
                    path=page["rel_path"],
                    marker_date=stale_marker,
                )
            )
        if len(page["body"].splitlines()) > 200:
            findings.append(
                _finding(
                    "page_too_long",
                    "low",
                    f"page {page['id']} exceeds 200 body lines",
                    page_id=page["id"],
                    path=page["rel_path"],
                    lines=len(page["body"].splitlines()),
                )
            )
        if history_block_in_body(page["body"]):
            findings.append(
                _finding(
                    "history_in_body",
                    "high",
                    f"page {page['id']} embeds Page History in the body",
                    page_id=page["id"],
                    path=page["rel_path"],
                )
            )
        if bool(page["metadata"].get("contested")):
            findings.append(
                _finding(
                    "unresolved_contested",
                    "medium",
                    f"page {page['id']} is contested and unresolved",
                    page_id=page["id"],
                    path=page["rel_path"],
                )
            )

    taxonomy = {str(row["tag"]) for row in db.list_taxonomy(conn)}
    if taxonomy:
        for page in pages:
            for tag in _string_list(page["metadata"].get("tags")):
                if tag not in taxonomy:
                    findings.append(
                        _finding(
                            "invalid_tag",
                            "high",
                            f"page {page['id']} uses tag {tag!r} outside the taxonomy",
                            page_id=page["id"],
                            path=page["rel_path"],
                            tag=tag,
                        )
                    )
    return findings


def _index_findings(
    wiki_root: Path,
    pages: list[dict[str, Any]],
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    indexed_ids = _index_page_ids(wiki_root)
    file_ids = {page["id"] for page in pages if page["id"]}
    for page in pages:
        if page["id"] and page["id"] not in indexed_ids:
            findings.append(
                _finding(
                    "missing_from_index",
                    "medium",
                    f"page {page['id']} is not listed in index.md",
                    page_id=page["id"],
                    path=page["rel_path"],
                )
            )
    db_ids = {str(row["id"]) for row in db.list_pages(conn, include_archived=True)}
    for page_id in sorted(indexed_ids - file_ids):
        findings.append(
            _finding(
                "cross_consistency",
                "high",
                f"index.md lists missing page {page_id}",
                page_id=page_id,
                path="index.md",
            )
        )
    for page_id in sorted(file_ids - db_ids):
        findings.append(
            _finding(
                "cross_consistency",
                "high",
                f"page {page_id} exists on disk but has no pages row",
                page_id=page_id,
                path=f"{page_id}.md",
            )
        )
    return findings


def _log_findings(wiki_root: Path) -> list[dict[str, Any]]:
    log_path = wiki_root / "log.md"
    if not log_path.exists():
        return []
    entries = [
        line
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("|") and "---" not in line and "Timestamp" not in line
    ]
    if len(entries) <= 500:
        return []
    return [
        _finding(
            "log_too_long",
            "low",
            f"log.md has {len(entries)} entries, exceeding the 500-entry threshold",
            path="log.md",
            entries=len(entries),
        )
    ]


def _source_findings(
    wiki_root: Path,
    conn: sqlite3.Connection,
    pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    source_rows = {
        str(row["id"]): row
        for row in conn.execute("SELECT * FROM sources ORDER BY id").fetchall()
    }
    for source_id, row in source_rows.items():
        rel = str(row["source_path"] or source_id)
        raw_path = wiki_root / rel
        if (
            raw_path.is_file()
            and row["sha256"]
            and projection.sha256_file(raw_path) != row["sha256"]
        ):
            findings.append(
                _finding(
                    "raw_snapshot_mutation",
                    "high",
                    f"raw snapshot {rel} sha256 differs from sources projection",
                    path=rel,
                    expected_sha256=str(row["sha256"]),
                    actual_sha256=projection.sha256_file(raw_path),
                )
            )
        elif not raw_path.is_file():
            findings.append(
                _finding(
                    "cross_consistency",
                    "high",
                    f"sources row {source_id} references missing raw snapshot {rel}",
                    path=rel,
                )
            )
    drift_rows = conn.execute(
        """
        SELECT DISTINCT source_url, source_path
        FROM ingest_log
        WHERE drift_detected = 1
        ORDER BY source_url, source_path
        """
    ).fetchall()
    for row in drift_rows:
        findings.append(
            _finding(
                "external_source_drift",
                "medium",
                f"external source drift recorded for {row['source_url'] or row['source_path']}",
                path=str(row["source_path"] or ""),
                source_url=row["source_url"],
            )
        )
    latest_by_source_path = {
        str(row["source_path"] or row["id"]): row
        for row in source_rows.values()
        if int(row["is_latest"] or 0) == 1
    }
    for page in pages:
        updated = _parse_time(page["metadata"].get("updated"))
        if updated is None:
            continue
        related = [
            latest_by_source_path[source]
            for source in _string_list(page["metadata"].get("sources"))
            if source in latest_by_source_path
        ]
        if not related:
            continue
        source_times = [
            parsed
            for row in related
            if (parsed := _parse_time(row["ingested_at"])) is not None
        ]
        newest_source = max(source_times, default=None)
        if newest_source is not None and newest_source - updated > timedelta(days=90):
            findings.append(
                _finding(
                    "stale_content",
                    "medium",
                    f"page {page['id']} is >90 days older than a related source snapshot",
                    page_id=page["id"],
                    path=page["rel_path"],
                )
            )
    return findings


def _kanban_findings(
    pages: list[dict[str, Any]],
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    frontmatter_refs = {
        (
            page["id"],
            str(ref.get("task_id") or ""),
            str(ref.get("direction") or "page->task"),
        )
        for page in pages
        for ref in _dict_list(page["metadata"].get("kanban_refs"))
        if ref.get("task_id")
    }
    db_refs = {
        (str(row["page_id"]), str(row["task_id"]), str(row["direction"]))
        for row in db.list_kanban_refs(conn)
    }
    findings: list[dict[str, Any]] = []
    for page_id, task_id, direction in sorted(frontmatter_refs ^ db_refs):
        findings.append(
            _finding(
                "kanban_projection_drift",
                "medium",
                f"kanban ref {page_id} {task_id} {direction} differs between "
                "frontmatter and wiki.db",
                page_id=page_id,
                path=f"{page_id}.md",
                task_id=task_id,
                direction=direction,
            )
        )
    findings.extend(_dangling_kanban_findings(frontmatter_refs | db_refs))
    return findings


def _dangling_kanban_findings(
    refs: set[tuple[str, str, str]],
) -> list[dict[str, Any]]:
    if not refs:
        return []
    try:
        from hermes_wiki.kanban_link import KanbanUnavailableError, read_task
    except Exception:
        return []
    findings: list[dict[str, Any]] = []
    for page_id, task_id, direction in sorted(refs):
        try:
            task = read_task(task_id)
        except KanbanUnavailableError:
            return []
        if task is not None:
            continue
        findings.append(
            _finding(
                "dangling_kanban_ref",
                "medium",
                f"kanban ref {page_id} points to missing task {task_id}",
                page_id=page_id,
                path=f"{page_id}.md",
                task_id=task_id,
                direction=direction,
            )
        )
    return findings


def _plugin_findings(wiki_root: Path, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    trusted: dict[tuple[str, str], dict[str, Any]] = {
        (str(row["kind"]), str(row["name"])): row for row in db.list_trusted_plugins(conn)
    }
    for record in read_schema_trust_records(wiki_root):
        trusted.setdefault((str(record["kind"]), str(record["name"])), record)
    findings: list[dict[str, Any]] = []
    plugin_files: set[tuple[str, str]] = set()
    for kind, dirname in (("classifier", "classifiers"), ("processor", "processors")):
        for path in sorted((wiki_root / "plugins" / dirname).glob("*.py")):
            key = (kind, path.stem)
            plugin_files.add(key)
            current = projection.sha256_file(path)
            trusted_row = trusted.get(key)
            rel = path.relative_to(wiki_root).as_posix()
            if trusted_row is None:
                findings.append(
                    _finding(
                        "untrusted_plugin_present",
                        "medium",
                        f"plugin file {rel} is present but not trusted",
                        path=rel,
                        name=path.stem,
                        kind=kind,
                    )
                )
            elif str(trusted_row.get("sha256") or "") != current:
                findings.append(
                    _finding(
                        "trusted_plugin_hash_mismatch",
                        "high",
                        f"trusted plugin {kind} {path.stem} hash differs from trust record",
                        path=rel,
                        name=path.stem,
                        kind=kind,
                        expected_sha256=str(trusted_row.get("sha256") or ""),
                        actual_sha256=current,
                    )
                )
    for key, row in sorted(trusted.items()):
        if key in plugin_files:
            continue
        rel = str(row.get("path") or "")
        if rel:
            findings.append(
                _finding(
                    "trusted_plugin_hash_mismatch",
                    "high",
                    f"trusted plugin {key[0]} {key[1]} is missing from disk",
                    path=rel,
                    name=key[1],
                    kind=key[0],
                    expected_sha256=str(row.get("sha256") or ""),
                    actual_sha256=None,
                )
            )
    return findings


def _inbox_findings(wiki_root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    inbox = wiki_root / "raw" / "inbox"
    statuses = _load_inbox_status(wiki_root)
    if inbox.exists():
        for path in sorted(item for item in inbox.iterdir() if item.is_file()):
            rel = path.relative_to(wiki_root).as_posix()
            status = statuses.get(path.name, {}).get("status")
            if status == "oversized" or path.stat().st_size > MAX_INGEST_BYTES:
                findings.append(
                    _finding(
                        "oversized_inbox_item",
                        "medium",
                        f"inbox file {rel} exceeds the 50MB Phase-1 ingest cap",
                        path=rel,
                        bytes=path.stat().st_size,
                    )
                )
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
                path="wiki.db",
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
                path="wiki.db",
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
                path="wiki.db",
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
                    path="wiki.db",
                    field="db_sha256",
                )
            )
    return findings


def _markdown_links(body: str) -> list[str]:
    return [
        match.group("target").strip()
        for match in re.finditer(r"(?<!!)\[[^\]]+\]\((?P<target>[^)]+)\)", body)
    ]


def _is_external_or_anchor(target: str) -> bool:
    clean = target.strip()
    return (
        not clean
        or clean.startswith("#")
        or clean.startswith("http://")
        or clean.startswith("https://")
        or clean.startswith("mailto:")
    )


def _has_factual_body(body: str) -> bool:
    text = re.sub(r"^#.*$", "", body, flags=re.MULTILINE).strip()
    return bool(re.search(r"[A-Za-z]{3,}", text))


def _stale_unverified_marker(body: str) -> str | None:
    for match in re.finditer(r"\[unverified(?::|\])[\s(]*(?P<date>\d{4}-\d{2}-\d{2})", body):
        try:
            marker_date = datetime.fromisoformat(match.group("date")).replace(tzinfo=UTC)
        except ValueError:
            continue
        if datetime.now(UTC) - marker_date > timedelta(days=14):
            return match.group("date")
    return None


def _index_page_ids(wiki_root: Path) -> set[str]:
    index = wiki_root / "index.md"
    if not index.exists():
        return set()
    text = index.read_text(encoding="utf-8")
    ids: set[str] = set(re.findall(r"`([^`]+/[^`]+)`", text))
    for target in re.findall(r"\[[^\]]+\]\(([^)]+\.md)(?:#[^)]+)?\)", text):
        if _is_external_or_anchor(target):
            continue
        ids.add(Path(target.split("#", 1)[0]).with_suffix("").as_posix())
    return ids


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value]
    return []


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _load_inbox_status(wiki_root: Path) -> dict[str, dict[str, str]]:
    status_path = wiki_root / INBOX_STATUS_REL
    if not status_path.exists():
        return {}
    try:
        loaded = json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    statuses: dict[str, dict[str, str]] = {}
    for key, value in loaded.items():
        if isinstance(value, dict):
            statuses[str(key)] = {str(k): str(v) for k, v in value.items()}
    return statuses


def _should_attempt_rebuild(findings: list[dict[str, Any]]) -> bool:
    rebuild_codes = {
        "projection_missing",
        "projection_corrupt",
        "projection_mismatch",
        "projection_version_mismatch",
    }
    return any(str(finding.get("code")) in rebuild_codes for finding in findings)


def _summary(findings: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(findings),
        "high": sum(1 for finding in findings if finding.get("severity") == "high"),
        "medium": sum(1 for finding in findings if finding.get("severity") == "medium"),
        "low": sum(1 for finding in findings if finding.get("severity") == "low"),
    }


def _health_score(findings: list[dict[str, Any]]) -> float:
    penalties = {"high": 0.2, "medium": 0.08, "low": 0.03}
    score = 1.0 - sum(penalties.get(str(finding.get("severity")), 0.0) for finding in findings)
    return round(max(0.0, score), 3)


def _record_lint_result(home: Path, slug: str, *, health_score: float) -> None:
    registry = home / "wikis" / "wikis.db"
    if not registry.exists():
        return
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with db.connect_registry(registry) as conn:
        conn.execute(
            """
            UPDATE wikis
            SET last_lint = ?, health_score = ?, updated = ?
            WHERE slug = ?
            """,
            (now, health_score, now, slug),
        )
        conn.commit()


def _finding(
    code: str,
    severity: str,
    message: str,
    *,
    page_id: str | None = None,
    field: str | None = None,
    path: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "code": code,
        "check": code,
        "severity": severity,
        "message": message,
    }
    if page_id is not None:
        finding["page_id"] = page_id
        finding["page"] = page_id
    if path is not None:
        finding["path"] = path
    elif page_id is None:
        finding["path"] = "wiki.db" if code.startswith("projection") else "."
    if field is not None:
        finding["field"] = field
    for key, value in extra.items():
        if value is not None:
            finding[key] = value
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
