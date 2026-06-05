"""Agent tool surface for Hermes Wiki read and write operations."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from adapters.base import ToolRegistry, create_adapters
from hermes_wiki import db, git_ops, projection
from hermes_wiki.classifiers import classify_source
from hermes_wiki.frontmatter import FrontmatterError, read_markdown, write_markdown
from hermes_wiki.lint import ensure_projection_current, projection_findings
from hermes_wiki.management import NOT_FOUND_OR_NOT_VISIBLE
from hermes_wiki.navigation import WikiNavigationError, list_wiki_pages, validate_page_id
from hermes_wiki.pipeline import MAX_INGEST_BYTES, IngestError, ingest_inbox, ingest_source
from hermes_wiki.projection import PAGE_DIR_TYPES
from hermes_wiki.search import search_wiki as search_one_wiki
from hermes_wiki.visibility import WikiVisibilityError, require_visible_wiki, visible_wikis

READ_TOOLS = frozenset(
    {
        "wiki_list",
        "wiki_search",
        "wiki_show",
        "wiki_health_check",
        "wiki_inbox",
    }
)
WRITE_TOOLS = frozenset({"wiki_ingest", "wiki_create_page", "wiki_link_kanban"})

WRITE_PERMISSION_DENIED = "wiki write permission denied"

ToolResult = dict[str, Any] | list[dict[str, Any]] | str
ToolCallable = Callable[..., ToolResult]


def wiki_list(wiki: str | None = None) -> ToolResult:
    """List visible Wikis, or page navigation entries for one visible Wiki."""

    if wiki is None:
        return [_wiki_nav_row(row) for row in visible_wikis()]
    try:
        pages = list_wiki_pages(wiki=wiki)
    except WikiNavigationError:
        return NOT_FOUND_OR_NOT_VISIBLE
    return [_page_nav_row(row, wiki=wiki) for row in pages]


def wiki_search(query: str, wiki: str | None = None, limit: int = 5) -> ToolResult:
    """Search visible Wiki Pages with FTS5/BM25 ranking."""

    if limit <= 0:
        return []
    if wiki is not None:
        try:
            wiki_rows = search_one_wiki(query, wiki=wiki, limit=limit)
            return [_search_row(row, wiki=wiki) for row in wiki_rows]
        except Exception:
            return NOT_FOUND_OR_NOT_VISIBLE

    rows: list[dict[str, Any]] = []
    for visible in visible_wikis():
        slug = str(visible["slug"])
        try:
            wiki_rows = search_one_wiki(query, wiki=slug, limit=limit)
            rows.extend(_search_row(row, wiki=slug) for row in wiki_rows)
        except Exception:
            continue
    rows.sort(
        key=lambda row: (
            float(row.get("rank") or 0.0),
            str(row.get("wiki")),
            str(row.get("id")),
        )
    )
    return rows[:limit]


def wiki_show(page_id: str, wiki: str | None = None) -> ToolResult:
    """Return a Wiki Page body, parsed frontmatter, and linked kanban refs."""

    try:
        clean_page_id = validate_page_id(page_id)
    except WikiNavigationError:
        return f"page not found: {page_id.strip()}"
    try:
        slug, wiki_root = require_visible_wiki(wiki)
    except WikiVisibilityError:
        return NOT_FOUND_OR_NOT_VISIBLE
    try:
        ensure_projection_current(wiki_root)
        with db.connect_wiki(wiki_root / "wiki.db") as conn:
            page_row = db.get_page(conn, clean_page_id)
            projected_refs = db.list_kanban_refs(conn, page_id=clean_page_id)
        if page_row is None or int(page_row.get("archived") or 0):
            return f"page not found: {clean_page_id}"
        page_path = _page_path(wiki_root, clean_page_id)
        if page_path is None or not page_path.is_file():
            return f"page not found: {clean_page_id}"
        frontmatter, body = read_markdown(page_path)
        if str(frontmatter.get("id") or "") != clean_page_id:
            return f"page not found: {clean_page_id}"
    except (FrontmatterError, OSError):
        return f"page not found: {clean_page_id}"

    return {
        "wiki": slug,
        "page_id": clean_page_id,
        "id": clean_page_id,
        "title": frontmatter.get("title"),
        "frontmatter": _jsonable(frontmatter),
        "content": body,
        "body": body,
        "kanban_refs": _linked_kanban_refs(projected_refs, frontmatter),
    }


def wiki_health_check(wiki: str | None = None) -> ToolResult:
    """Return a structured, JSON-serializable lint health report."""

    try:
        slug, wiki_root = require_visible_wiki(wiki)
    except WikiVisibilityError:
        return NOT_FOUND_OR_NOT_VISIBLE
    findings = projection_findings(wiki_root)
    checks = [
        {
            "code": str(finding.get("code") or "unknown"),
            "severity": str(finding.get("severity") or "low"),
            "status": "fail",
            "message": str(finding.get("message") or ""),
            **{
                key: value
                for key, value in finding.items()
                if key not in {"code", "severity", "message"}
            },
        }
        for finding in findings
    ]
    if not checks:
        checks.append(
            {
                "code": "projection_consistency",
                "severity": "low",
                "status": "pass",
                "message": "projection is consistent with Wiki Page files",
            }
        )
    report = {
        "wiki": slug,
        "status": "clean" if not findings else "issues",
        "checks": checks,
        "findings": findings,
        "summary": {
            "total": len(findings),
            "high": sum(1 for finding in findings if finding.get("severity") == "high"),
            "medium": sum(1 for finding in findings if finding.get("severity") == "medium"),
            "low": sum(1 for finding in findings if finding.get("severity") == "low"),
        },
    }
    # Assert JSON serializability at the boundary this tool promises.
    json.dumps(report, sort_keys=True)
    return report


def wiki_inbox(wiki: str | None = None) -> ToolResult:
    """List unprocessed inbox files with last status and classifier suggestions."""

    try:
        slug, wiki_root = require_visible_wiki(wiki)
    except WikiVisibilityError:
        return NOT_FOUND_OR_NOT_VISIBLE
    inbox = wiki_root / "raw" / "inbox"
    if not inbox.exists():
        return []
    statuses = _load_inbox_status(wiki_root)
    rows: list[dict[str, Any]] = []
    for path in sorted(item for item in inbox.iterdir() if item.is_file()):
        relpath = path.relative_to(wiki_root).as_posix()
        recorded = statuses.get(path.name, {})
        suggested = _suggest_class(wiki_root, path)
        status = str(recorded.get("status") or "")
        if not status:
            status = "oversized" if suggested == "oversized" else "not yet attempted"
        rows.append(
            {
                "wiki": slug,
                "name": path.name,
                "path": relpath,
                "absolute_path": path.as_posix(),
                "status": status,
                "suggested_class": str(recorded.get("classified_as") or suggested),
                "last_classification": recorded.get("classified_as"),
                "last_attempted_at": recorded.get("last_attempted_at"),
                "size_bytes": path.stat().st_size,
            }
        )
    return rows


def wiki_ingest(
    path_or_url: str | None = None,
    *,
    wiki: str | None = None,
    classifier: str | None = None,
    inbox: bool = False,
) -> ToolResult:
    """Write tool wrapper for ingest; denied unless the session has a write grant."""

    visible = _resolve_for_write(wiki)
    if isinstance(visible, str):
        return visible
    slug, _wiki_root = visible
    if not _check_wiki_write_mode(slug):
        return WRITE_PERMISSION_DENIED
    if bool(path_or_url) == bool(inbox):
        return "wiki_ingest requires exactly one of path_or_url or inbox=True"
    try:
        if inbox:
            results = ingest_inbox(wiki=slug, author=_agent_author(), author_kind="agent")
            return [_ingest_result_row(result) for result in results]
        if path_or_url is None:
            return "wiki_ingest requires path_or_url"
        return _ingest_result_row(
            ingest_source(
                path_or_url,
                wiki=slug,
                author=_agent_author(),
                author_kind="agent",
                classifier=classifier,
            )
        )
    except IngestError as exc:
        return str(exc)


def wiki_create_page(
    title: str,
    body: str,
    type: str,
    tags: Sequence[str] | None = None,
    sources: Sequence[str] | None = None,
    *,
    wiki: str | None = None,
) -> ToolResult:
    """Create or update a Wiki Page with agent attribution and a git commit."""

    visible = _resolve_for_write(wiki)
    if isinstance(visible, str):
        return visible
    slug, wiki_root = visible
    if not _check_wiki_write_mode(slug):
        return WRITE_PERMISSION_DENIED
    try:
        return _create_or_update_page(
            wiki_root,
            wiki=slug,
            title=title,
            body=body,
            page_type=type,
            tags=tags or (),
            sources=sources or (),
            author=_agent_author(),
        )
    except WikiNavigationError as exc:
        return str(exc)


def wiki_link_kanban(
    page_id: str,
    task_id: str,
    *,
    wiki: str | None = None,
) -> ToolResult:
    """Link a Wiki Page to a kanban task without mutating kanban.db."""

    visible = _resolve_for_write(wiki)
    if isinstance(visible, str):
        return visible
    slug, wiki_root = visible
    if not _check_wiki_write_mode(slug):
        return WRITE_PERMISSION_DENIED
    try:
        return _link_kanban_ref(
            wiki_root,
            wiki=slug,
            page_id=page_id,
            task_id=task_id,
            author=_agent_author(),
        )
    except WikiNavigationError as exc:
        return str(exc)


def _check_wiki_write_mode(wiki: str | None) -> bool:
    """Return whether the current session may mutate ``wiki``.

    Visibility is intentionally checked by callers before this function is
    evaluated, so a Write Grant cannot reveal an invisible Wiki.
    """

    env_wiki = os.environ.get("HERMES_WIKI")
    if env_wiki and (wiki is None or env_wiki == wiki):
        return True
    try:
        cfg = create_adapters().config.load()
        wiki_cfg = cfg.get("wiki", {}) if isinstance(cfg, Mapping) else {}
        grants = _string_set(
            wiki_cfg.get("write_grants") if isinstance(wiki_cfg, Mapping) else None
        )
        toolsets = _string_set(cfg.get("toolsets") if isinstance(cfg, Mapping) else None)
        enabled_toolsets = _string_set(
            cfg.get("enabled_toolsets") if isinstance(cfg, Mapping) else None
        )
    except Exception:
        return False
    return (
        "wiki" in toolsets
        or "wiki" in enabled_toolsets
        or "*" in grants
        or (wiki is not None and wiki in grants)
    )


def register_tools(registry: ToolRegistry | None = None) -> ToolRegistry:
    """Register the Hermes Wiki tools via the tool-registry seam."""

    target = registry or create_adapters().tools
    for name, fn in _READ_TOOL_FUNCTIONS.items():
        target.register(name, fn, schema=_tool_schema(name))
    for name, fn in _WRITE_TOOL_FUNCTIONS.items():
        target.register(
            name,
            fn,
            check_fn=lambda: _check_wiki_write_mode(None),
            schema=_tool_schema(name),
        )
    return target


def _resolve_for_write(wiki: str | None) -> tuple[str, Path] | str:
    try:
        return require_visible_wiki(wiki)
    except WikiVisibilityError:
        return NOT_FOUND_OR_NOT_VISIBLE


def _create_or_update_page(
    wiki_root: Path,
    *,
    wiki: str,
    title: str,
    body: str,
    page_type: str,
    tags: Sequence[str],
    sources: Sequence[str],
    author: str,
) -> dict[str, Any]:
    clean_type = _clean_page_type(page_type)
    page_id = f"{_directory_for_page_type(clean_type)}/{_slugify(title)}"
    page_path = wiki_root / f"{page_id}.md"
    now = _utc_now()
    created = now
    existing_refs: list[Mapping[str, Any]] = []
    if page_path.exists():
        frontmatter, _existing_body = read_markdown(page_path)
        created = str(frontmatter.get("created") or now)
        existing_refs = _frontmatter_kanban_refs(frontmatter)

    metadata: dict[str, Any] = {
        "id": page_id,
        "title": _one_line(title, "title"),
        "type": clean_type,
        "created": created,
        "updated": now,
        "tags": [str(tag) for tag in tags],
        "sources": [str(source) for source in sources],
        "confidence": "medium",
        "contested": False,
        "author": author,
        "author_kind": "agent",
        "links": [],
        "inbound_links": 0,
    }
    if existing_refs:
        metadata["kanban_refs"] = [dict(ref) for ref in existing_refs]

    write_markdown(page_path, metadata, body)
    _rewrite_index(wiki_root)
    _append_tool_log(
        wiki_root,
        now=now,
        action="create-page",
        target=page_id,
        author=author,
        details={"title": title, "type": clean_type},
    )
    rebuild = projection.rebuild_projection(
        wiki_root,
        rebuild_reason="manual",
        author=author,
        author_kind="agent",
    )
    if rebuild.status != "active":
        raise WikiNavigationError(f"projection rebuild failed: {rebuild.notes}")
    _refresh_registry_counts(wiki_root, wiki=wiki, updated=now)
    commit = git_ops.commit_change(
        wiki_root,
        action="create-page",
        what=page_id,
        author=author,
    )
    return {
        "wiki": wiki,
        "id": page_id,
        "page_id": page_id,
        "title": title,
        "type": clean_type,
        "path": page_path.relative_to(wiki_root).as_posix(),
        "author": author,
        "author_kind": "agent",
        "commit_id": commit.commit_id,
    }


def _link_kanban_ref(
    wiki_root: Path,
    *,
    wiki: str,
    page_id: str,
    task_id: str,
    author: str,
) -> dict[str, Any]:
    clean_page_id = validate_page_id(page_id)
    clean_task_id = _one_line(task_id, "task_id")
    page_path = _page_path(wiki_root, clean_page_id)
    if page_path is None or not page_path.is_file():
        raise WikiNavigationError(f"page not found: {clean_page_id}")
    frontmatter, body = read_markdown(page_path)
    if str(frontmatter.get("id") or "") != clean_page_id:
        raise WikiNavigationError(f"page not found: {clean_page_id}")

    now = _utc_now()
    refs = [dict(ref) for ref in _frontmatter_kanban_refs(frontmatter)]
    wanted = {"task_id": clean_task_id, "direction": "page->task"}
    existing = next(
        (
            ref
            for ref in refs
            if ref.get("task_id") == wanted["task_id"]
            and ref.get("direction", "page->task") == wanted["direction"]
        ),
        None,
    )
    if existing is None:
        refs.append({**wanted, "created": now})
        created = now
    else:
        created = str(existing.get("created") or now)
        existing["created"] = created

    frontmatter["kanban_refs"] = refs
    frontmatter["updated"] = now
    frontmatter["author"] = author
    frontmatter["author_kind"] = "agent"
    write_markdown(page_path, dict(frontmatter), body)
    _append_tool_log(
        wiki_root,
        now=now,
        action="link-kanban",
        target=clean_page_id,
        author=author,
        details={"task_id": clean_task_id, "direction": "page->task"},
    )
    rebuild = projection.rebuild_projection(
        wiki_root,
        rebuild_reason="manual",
        author=author,
        author_kind="agent",
    )
    if rebuild.status != "active":
        raise WikiNavigationError(f"projection rebuild failed: {rebuild.notes}")
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        db.upsert_kanban_ref(
            conn,
            page_id=clean_page_id,
            task_id=clean_task_id,
            direction="page->task",
            created=created,
        )
        conn.commit()
        db_hash = projection.projection_db_sha256(wiki_root / "wiki.db")
        conn.execute(
            "UPDATE projection_versions SET db_sha256 = ? WHERE status = 'active'",
            (db_hash,),
        )
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    commit = git_ops.commit_change(
        wiki_root,
        action="link-kanban",
        what=f"{clean_page_id} {clean_task_id}",
        author=author,
    )
    return {
        "wiki": wiki,
        "page_id": clean_page_id,
        "task_id": clean_task_id,
        "direction": "page->task",
        "created": created,
        "author": author,
        "author_kind": "agent",
        "commit_id": commit.commit_id,
    }


def _clean_page_type(page_type: str) -> str:
    clean = _one_line(page_type, "type")
    if clean not in set(PAGE_DIR_TYPES.values()):
        raise WikiNavigationError(f"invalid page type: {clean}")
    return clean


def _directory_for_page_type(page_type: str) -> str:
    for directory, expected_type in PAGE_DIR_TYPES.items():
        if expected_type == page_type:
            return directory
    raise WikiNavigationError(f"invalid page type: {page_type}")


def _rewrite_index(wiki_root: Path) -> None:
    pages: dict[str, list[tuple[str, str]]] = {heading: [] for heading in _INDEX_HEADINGS}
    for path in sorted(projection._iter_page_files(wiki_root)):
        try:
            metadata, _body = read_markdown(path)
        except FrontmatterError:
            continue
        page_id = path.with_suffix("").relative_to(wiki_root).as_posix()
        heading = str(metadata.get("type") or "source").title() + "s"
        pages.setdefault(heading, []).append((str(metadata.get("title") or page_id), page_id))
    lines = ["# Index", ""]
    for heading in pages:
        entries = pages[heading]
        lines.extend([f"## {heading}", ""])
        for title, page_id in sorted(entries, key=lambda item: item[1]):
            lines.append(f"- [{title}]({page_id}.md) — `{page_id}`")
        lines.append("")
    (wiki_root / "index.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _append_tool_log(
    wiki_root: Path,
    *,
    now: str,
    action: str,
    target: str,
    author: str,
    details: Mapping[str, Any],
) -> None:
    encoded = json.dumps(details, separators=(",", ":"), sort_keys=True)
    with (wiki_root / "log.md").open("a", encoding="utf-8") as handle:
        handle.write(f"| {now} | {action} | {target} | {author} | agent | {encoded} |\n")


def _refresh_registry_counts(wiki_root: Path, *, wiki: str, updated: str) -> None:
    home = wiki_root.parent.parent
    registry = home / "wikis" / "wikis.db"
    if not registry.exists():
        return
    with db.connect_registry(registry) as registry_conn:
        db.initialize_registry(registry_conn)
        with db.connect_wiki(wiki_root / "wiki.db") as wiki_conn:
            page_count = wiki_conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
            source_count = wiki_conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        db.update_wiki_counts(
            registry_conn,
            slug=wiki,
            page_count=int(page_count),
            source_count=int(source_count),
            updated=updated,
        )
        registry_conn.commit()


def _wiki_nav_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "slug": row.get("slug"),
        "domain": row.get("domain"),
        "page_count": row.get("page_count") or 0,
        "source_count": row.get("source_count") or 0,
        "health_score": row.get("health_score"),
        "last_ingest": row.get("last_ingest"),
        "last_lint": row.get("last_lint"),
        "updated": row.get("updated"),
        "archived": bool(int(row.get("archived") or 0)),
    }


def _page_nav_row(row: Mapping[str, Any], *, wiki: str) -> dict[str, Any]:
    return {
        "wiki": wiki,
        "id": row.get("id"),
        "title": row.get("title"),
        "type": row.get("type"),
        "tags": list(row.get("tags") or []),
        "sources": list(row.get("sources") or []),
        "snippet": row.get("snippet"),
        "updated": row.get("updated"),
        "author": row.get("author"),
        "author_kind": row.get("author_kind"),
    }


def _search_row(row: Mapping[str, Any], *, wiki: str) -> dict[str, Any]:
    rank = float(row.get("rank") or 0.0)
    return {
        "wiki": wiki,
        "id": row.get("id"),
        "title": row.get("title"),
        "type": row.get("type"),
        "tags": list(row.get("tags") or []),
        "snippet": row.get("context") or row.get("snippet") or "",
        "context": row.get("context") or row.get("snippet") or "",
        "rank": rank,
        "score": rank,
    }


def _page_path(wiki_root: Path, page_id: str) -> Path | None:
    rel = Path(page_id + ".md")
    path = (wiki_root / rel).resolve()
    try:
        path.relative_to(wiki_root.resolve())
    except ValueError:
        return None
    return path


def _linked_kanban_refs(
    projected_refs: Sequence[Mapping[str, Any]],
    frontmatter: Mapping[str, Any],
) -> list[dict[str, Any]]:
    refs: dict[tuple[str, str, str], dict[str, Any]] = {}
    page_id = str(frontmatter.get("id") or "")
    for ref in projected_refs:
        key = (
            str(ref.get("page_id") or page_id),
            str(ref.get("task_id") or ""),
            str(ref.get("direction") or ""),
        )
        if key[1] and key[2]:
            refs[key] = {
                "page_id": key[0],
                "task_id": key[1],
                "direction": key[2],
                "created": ref.get("created"),
            }
    for ref in _frontmatter_kanban_refs(frontmatter):
        key = (page_id, str(ref.get("task_id") or ""), str(ref.get("direction") or "page->task"))
        if key[1]:
            refs.setdefault(
                key,
                {
                    "page_id": page_id,
                    "task_id": key[1],
                    "direction": key[2],
                    "created": ref.get("created"),
                },
            )
    rows: list[dict[str, Any]] = []
    for key in sorted(refs):
        row = refs[key]
        row["task"] = _read_kanban_task(str(row["task_id"]))
        rows.append(row)
    return rows


def _frontmatter_kanban_refs(frontmatter: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = frontmatter.get("kanban_refs")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _read_kanban_task(task_id: str) -> Mapping[str, Any] | None:
    try:
        task = create_adapters().kanban.get_task(task_id)
    except Exception:
        return None
    return _jsonable(dict(task)) if task is not None else None


def _load_inbox_status(wiki_root: Path) -> dict[str, dict[str, str]]:
    status_path = wiki_root / "raw" / "inbox_status.json"
    try:
        loaded = json.loads(status_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    statuses: dict[str, dict[str, str]] = {}
    for key, value in loaded.items():
        if isinstance(key, str) and isinstance(value, dict):
            statuses[key] = {
                str(inner_key): str(inner_value)
                for inner_key, inner_value in value.items()
            }
    return statuses


def _suggest_class(wiki_root: Path, path: Path) -> str:
    if path.stat().st_size > MAX_INGEST_BYTES:
        return "oversized"
    try:
        return classify_source(path.name, path.read_bytes(), wiki_root=wiki_root).name
    except Exception:
        return "unknown"


def _ingest_result_row(result: Any) -> dict[str, Any]:
    return {
        "wiki": result.wiki,
        "classified_as": result.classified_as,
        "source_id": result.source_id,
        "sha256": result.sha256,
        "pages_created": list(result.pages_created),
        "pages_updated": list(result.pages_updated),
        "raw_snapshot": result.raw_snapshot,
        "source_url": result.source_url,
        "commit_id": result.commit_id,
        "skipped": result.skipped,
        "message": result.message,
    }


def _tool_schema(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": f"Hermes Wiki tool {name}",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": True},
    }


def _agent_author() -> str:
    return os.environ.get("HERMES_MODEL") or os.environ.get("HERMES_AGENT_MODEL") or "agent"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise WikiNavigationError("title must contain at least one slug character")
    return slug


def _one_line(value: str, field: str) -> str:
    clean = str(value).strip()
    if not clean:
        raise WikiNavigationError(f"{field} is required")
    if "\n" in clean or "\r" in clean:
        raise WikiNavigationError(f"{field} must be a single line")
    return clean


def _string_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    if isinstance(value, Sequence):
        return {str(item) for item in value}
    return set()


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
    except TypeError:
        if isinstance(value, Mapping):
            return {str(key): _jsonable(inner) for key, inner in value.items()}
        if isinstance(value, Sequence) and not isinstance(value, str):
            return [_jsonable(item) for item in value]
        return str(value)
    return value


_READ_TOOL_FUNCTIONS: dict[str, ToolCallable] = {
    "wiki_list": wiki_list,
    "wiki_search": wiki_search,
    "wiki_show": wiki_show,
    "wiki_health_check": wiki_health_check,
    "wiki_inbox": wiki_inbox,
}
_WRITE_TOOL_FUNCTIONS: dict[str, ToolCallable] = {
    "wiki_ingest": wiki_ingest,
    "wiki_create_page": wiki_create_page,
    "wiki_link_kanban": wiki_link_kanban,
}
_INDEX_HEADINGS = ("Sources", "Concepts", "Entities", "Comparisons", "Queries", "Summaries")

__all__ = [
    "NOT_FOUND_OR_NOT_VISIBLE",
    "READ_TOOLS",
    "WRITE_PERMISSION_DENIED",
    "WRITE_TOOLS",
    "_check_wiki_write_mode",
    "register_tools",
    "wiki_create_page",
    "wiki_health_check",
    "wiki_inbox",
    "wiki_ingest",
    "wiki_link_kanban",
    "wiki_list",
    "wiki_search",
    "wiki_show",
]
