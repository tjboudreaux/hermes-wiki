"""Wiki-owned kanban linkage (frontmatter canonical, projection derived)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapters.base import create_adapters
from hermes_wiki import db, git_ops, projection
from hermes_wiki.attribution import record_change, resolve_actor, utc_now
from hermes_wiki.frontmatter import FrontmatterError, read_markdown, write_markdown
from hermes_wiki.management import (
    NOT_FOUND_OR_NOT_VISIBLE,
    WikiManagementError,
    ensure_wiki_mutable,
)
from hermes_wiki.navigation import WikiNavigationError, validate_page_id
from hermes_wiki.visibility import WikiVisibilityError, require_visible_wiki

TASK_ID_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")


class KanbanLinkError(WikiNavigationError):
    """Raised for clean kanban-linkage failures."""


class KanbanUnavailableError(RuntimeError):
    """Raised when the read-only kanban seam cannot be reached."""


@dataclass(frozen=True, slots=True)
class KanbanTask:
    """Task metadata read from the kanban seam."""

    id: str
    title: str | None = None
    raw: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class KanbanLinkResult:
    """Observable result for link/unlink commands and tools."""

    wiki: str
    page_id: str
    task_id: str
    direction: str
    created: str | None
    task_title: str | None
    changed: bool
    action: str
    author: str
    author_kind: str
    commit_id: str | None = None

    def to_row(self) -> dict[str, Any]:
        return {
            "wiki": self.wiki,
            "page_id": self.page_id,
            "task_id": self.task_id,
            "direction": self.direction,
            "created": self.created,
            "task_title": self.task_title,
            "changed": self.changed,
            "action": self.action,
            "author": self.author,
            "author_kind": self.author_kind,
            "commit_id": self.commit_id,
        }


def link_page_to_task(
    page_id: str,
    task_id: str,
    *,
    wiki: str | None = None,
    author: str | None = None,
    author_kind: str = "human",
) -> KanbanLinkResult:
    """Link a Wiki Page to an existing kanban task without mutating kanban."""

    resolved = _resolve_wiki(wiki)
    clean_page_id = _existing_page_id(resolved.path, page_id)
    clean_task_id = _clean_task_id(task_id)
    task = require_task(clean_task_id)
    acting_author, acting_kind = resolve_actor(author=author, author_kind=author_kind)
    page_path = resolved.path / f"{clean_page_id}.md"
    frontmatter, body = read_markdown(page_path)
    refs = normalize_kanban_refs(frontmatter.get("kanban_refs"), page_id=clean_page_id)
    existing = _find_ref(refs, task_id=clean_task_id, direction="page->task")
    if existing is not None:
        _ensure_projected_ref(
            resolved.path,
            page_id=clean_page_id,
            task_id=clean_task_id,
            direction="page->task",
            created=str(existing.get("created") or ""),
        )
        return KanbanLinkResult(
            wiki=resolved.slug,
            page_id=clean_page_id,
            task_id=clean_task_id,
            direction="page->task",
            created=str(existing.get("created") or ""),
            task_title=task.title,
            changed=False,
            action="link",
            author=acting_author,
            author_kind=acting_kind,
            commit_id=None,
        )

    created = utc_now()
    refs.append({"task_id": clean_task_id, "direction": "page->task", "created": created})
    frontmatter["kanban_refs"] = refs
    frontmatter["updated"] = created
    frontmatter["author"] = acting_author
    frontmatter["author_kind"] = acting_kind
    write_markdown(page_path, dict(frontmatter), body)
    record_change(
        resolved.path,
        timestamp=created,
        action="link-kanban",
        page_id=clean_page_id,
        author=acting_author,
        author_kind=acting_kind,
        details={"task_id": clean_task_id, "direction": "page->task"},
    )
    _rebuild_projection(resolved.path, author=acting_author, author_kind=acting_kind)
    commit = git_ops.commit_change(
        resolved.path,
        action="link",
        what=f"{clean_page_id} {clean_task_id}",
        author=acting_author,
    )
    return KanbanLinkResult(
        wiki=resolved.slug,
        page_id=clean_page_id,
        task_id=clean_task_id,
        direction="page->task",
        created=created,
        task_title=task.title,
        changed=True,
        action="link",
        author=acting_author,
        author_kind=acting_kind,
        commit_id=commit.commit_id,
    )


def unlink_page_from_task(
    page_id: str,
    task_id: str,
    *,
    wiki: str | None = None,
    author: str | None = None,
    author_kind: str = "human",
) -> KanbanLinkResult:
    """Remove a Wiki-owned kanban link from frontmatter and projection."""

    resolved = _resolve_wiki(wiki)
    clean_page_id = _existing_page_id(resolved.path, page_id)
    clean_task_id = _clean_task_id(task_id)
    task = read_task(clean_task_id)
    acting_author, acting_kind = resolve_actor(author=author, author_kind=author_kind)
    page_path = resolved.path / f"{clean_page_id}.md"
    frontmatter, body = read_markdown(page_path)
    refs = normalize_kanban_refs(frontmatter.get("kanban_refs"), page_id=clean_page_id)
    kept = [
        ref
        for ref in refs
        if not (
            ref.get("task_id") == clean_task_id
            and str(ref.get("direction") or "page->task") == "page->task"
        )
    ]
    if len(kept) == len(refs):
        return KanbanLinkResult(
            wiki=resolved.slug,
            page_id=clean_page_id,
            task_id=clean_task_id,
            direction="page->task",
            created=None,
            task_title=None if task is None else task.title,
            changed=False,
            action="unlink",
            author=acting_author,
            author_kind=acting_kind,
            commit_id=None,
        )

    now = utc_now()
    if kept:
        frontmatter["kanban_refs"] = kept
    else:
        frontmatter.pop("kanban_refs", None)
    frontmatter["updated"] = now
    frontmatter["author"] = acting_author
    frontmatter["author_kind"] = acting_kind
    write_markdown(page_path, dict(frontmatter), body)
    record_change(
        resolved.path,
        timestamp=now,
        action="unlink-kanban",
        page_id=clean_page_id,
        author=acting_author,
        author_kind=acting_kind,
        details={"task_id": clean_task_id, "direction": "page->task"},
    )
    _rebuild_projection(resolved.path, author=acting_author, author_kind=acting_kind)
    commit = git_ops.commit_change(
        resolved.path,
        action="unlink",
        what=f"{clean_page_id} {clean_task_id}",
        author=acting_author,
    )
    return KanbanLinkResult(
        wiki=resolved.slug,
        page_id=clean_page_id,
        task_id=clean_task_id,
        direction="page->task",
        created=None,
        task_title=None if task is None else task.title,
        changed=True,
        action="unlink",
        author=acting_author,
        author_kind=acting_kind,
        commit_id=commit.commit_id,
    )


def refs_for_page(page_id: str, *, wiki: str | None = None) -> list[dict[str, Any]]:
    """Return linked tasks for one Wiki Page from the projection."""

    slug, wiki_root = _resolve_visible_wiki(wiki)
    clean_page_id = _existing_page_id(wiki_root, page_id)
    _ensure_projection(wiki_root)
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        rows = db.list_kanban_refs(conn, page_id=clean_page_id)
    return [_decorate_ref(row, wiki=slug) for row in rows]


def refs_for_task(task_id: str, *, wiki: str | None = None) -> list[dict[str, Any]]:
    """Return pages linked to one task, answered from the wiki projection."""

    slug, wiki_root = _resolve_visible_wiki(wiki)
    clean_task_id = _clean_task_id(task_id)
    _ensure_projection(wiki_root)
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        rows = db.list_kanban_refs(conn, task_id=clean_task_id)
    return [_decorate_ref(row, wiki=slug) for row in rows]


def normalize_kanban_refs(value: Any, *, page_id: str | None = None) -> list[dict[str, Any]]:
    """Normalize frontmatter ``kanban_refs`` entries and de-duplicate them."""

    if not isinstance(value, list):
        return []
    seen: set[tuple[str, str]] = set()
    refs: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        task_id = str(item.get("task_id") or "").strip()
        if not task_id:
            continue
        direction = str(item.get("direction") or "page->task").strip() or "page->task"
        key = (task_id, direction)
        if key in seen:
            continue
        seen.add(key)
        ref = {"task_id": task_id, "direction": direction}
        if item.get("created"):
            ref["created"] = str(item.get("created"))
        if page_id and direction == "task->page":
            ref["page_id"] = page_id
        refs.append(ref)
    return refs


def read_task(task_id: str) -> KanbanTask | None:
    """Read task metadata from the read-only kanban seam."""

    try:
        raw = create_adapters().kanban.get_task(task_id)
    except Exception as exc:
        raise KanbanUnavailableError(str(exc) or "kanban seam unreachable") from exc
    if raw is None:
        return None
    data = dict(raw)
    task_value = str(data.get("id") or data.get("task_id") or task_id)
    title = data.get("title") or data.get("name") or data.get("summary")
    return KanbanTask(id=task_value, title=None if title is None else str(title), raw=data)


def require_task(task_id: str) -> KanbanTask:
    """Return an existing task or raise a user-facing validation error."""

    try:
        task = read_task(task_id)
    except KanbanUnavailableError as exc:
        raise KanbanLinkError(f"kanban seam unreachable; cannot validate task {task_id}") from exc
    if task is None:
        raise KanbanLinkError(f"kanban task not found: {task_id}")
    return task


def auto_link_enabled(wiki_root: Path) -> bool:
    """Return whether ``SCHEMA.md`` opts into ingest-time task-id detection."""

    try:
        schema = (wiki_root / "SCHEMA.md").read_text(encoding="utf-8")
    except OSError:
        return False
    return bool(re.search(r"(?im)^\s*auto_link_kanban\s*:\s*true\s*$", schema))


def auto_link_ingest_pages(
    wiki_root: Path,
    *,
    source_text: str,
    page_ids: Sequence[str],
    created: str,
) -> list[str]:
    """Attach detected task IDs to ingested Source Pages when SCHEMA opts in."""

    if not auto_link_enabled(wiki_root):
        return []
    task_ids = sorted(set(TASK_ID_RE.findall(source_text)))
    if not task_ids:
        return []
    linked: list[str] = []
    # Keep auto-linking conservative: source text task IDs attach to Source
    # Pages, which are the durable source-context pages for that text.
    source_page_ids = [page_id for page_id in page_ids if page_id.startswith("sources/")]
    for page_id in source_page_ids:
        page_path = wiki_root / f"{page_id}.md"
        try:
            frontmatter, body = read_markdown(page_path)
        except (OSError, FrontmatterError):
            continue
        refs = normalize_kanban_refs(frontmatter.get("kanban_refs"), page_id=page_id)
        changed = False
        for task_id in task_ids:
            try:
                task = read_task(task_id)
            except KanbanUnavailableError:
                continue
            if task is None or _find_ref(refs, task_id=task_id, direction="page->task"):
                continue
            refs.append({"task_id": task_id, "direction": "page->task", "created": created})
            linked.append(task_id)
            changed = True
        if changed:
            frontmatter["kanban_refs"] = refs
            write_markdown(page_path, dict(frontmatter), body)
    return linked


def _decorate_ref(row: Mapping[str, Any], *, wiki: str) -> dict[str, Any]:
    task_id = str(row.get("task_id") or "")
    try:
        task = read_task(task_id)
    except KanbanUnavailableError:
        task = None
    return {
        "wiki": wiki,
        "page_id": str(row.get("page_id") or ""),
        "task_id": task_id,
        "direction": str(row.get("direction") or ""),
        "created": row.get("created"),
        "task_title": None if task is None else task.title,
        "task": None if task is None else dict(task.raw or {}),
    }


def _resolve_wiki(wiki: str | None) -> Any:
    try:
        return ensure_wiki_mutable(slug=wiki)
    except WikiManagementError as exc:
        raise KanbanLinkError(NOT_FOUND_OR_NOT_VISIBLE) from exc


def _resolve_visible_wiki(wiki: str | None) -> tuple[str, Path]:
    try:
        return require_visible_wiki(wiki)
    except WikiVisibilityError as exc:
        raise KanbanLinkError(NOT_FOUND_OR_NOT_VISIBLE) from exc


def _existing_page_id(wiki_root: Path, page_id: str) -> str:
    clean_page_id = validate_page_id(page_id)
    page_path = wiki_root / f"{clean_page_id}.md"
    if not page_path.is_file():
        raise KanbanLinkError(f"page not found: {clean_page_id}")
    try:
        frontmatter, _body = read_markdown(page_path)
    except (OSError, FrontmatterError) as exc:
        raise KanbanLinkError(f"page not found: {clean_page_id}") from exc
    if str(frontmatter.get("id") or "") != clean_page_id:
        raise KanbanLinkError(f"page not found: {clean_page_id}")
    return clean_page_id


def _clean_task_id(task_id: str) -> str:
    clean = str(task_id).strip()
    if not clean:
        raise KanbanLinkError("task id is required")
    if "\n" in clean or "\r" in clean or "/" in clean or "\\" in clean:
        raise KanbanLinkError("invalid task id")
    return clean


def _find_ref(
    refs: Sequence[Mapping[str, Any]],
    *,
    task_id: str,
    direction: str,
) -> Mapping[str, Any] | None:
    return next(
        (
            ref
            for ref in refs
            if ref.get("task_id") == task_id
            and str(ref.get("direction") or "page->task") == direction
        ),
        None,
    )


def _rebuild_projection(wiki_root: Path, *, author: str, author_kind: str) -> None:
    result = projection.rebuild_projection(
        wiki_root,
        rebuild_reason="manual",
        author=author,
        author_kind=author_kind,
    )
    if result.status != "active":
        raise KanbanLinkError(f"projection rebuild failed: {result.notes}")


def _ensure_projected_ref(
    wiki_root: Path,
    *,
    page_id: str,
    task_id: str,
    direction: str,
    created: str,
) -> None:
    _ensure_projection(wiki_root)
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        existing = db.list_kanban_refs(conn, page_id=page_id, task_id=task_id)
        if any(str(row.get("direction") or "") == direction for row in existing):
            return
        db.upsert_kanban_ref(
            conn,
            page_id=page_id,
            task_id=task_id,
            direction=direction,
            created=created or None,
        )
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _ensure_projection(wiki_root: Path) -> None:
    from hermes_wiki.lint import ensure_projection_current

    ensure_projection_current(wiki_root)


__all__ = [
    "KanbanLinkError",
    "KanbanLinkResult",
    "KanbanTask",
    "KanbanUnavailableError",
    "auto_link_enabled",
    "auto_link_ingest_pages",
    "link_page_to_task",
    "normalize_kanban_refs",
    "read_task",
    "refs_for_page",
    "refs_for_task",
    "require_task",
    "unlink_page_from_task",
]
