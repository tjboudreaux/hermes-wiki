"""Read-only Wiki Page navigation helpers for CLI/tool surfaces."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from hermes_wiki import db
from hermes_wiki.frontmatter import FrontmatterError, read_markdown
from hermes_wiki.management import (
    NOT_FOUND_OR_NOT_VISIBLE,
    WikiManagementError,
)
from hermes_wiki.projection import PAGE_DIR_TYPES
from hermes_wiki.visibility import WikiVisibilityError, require_visible_wiki

Row = dict[str, Any]


class WikiNavigationError(WikiManagementError):
    """Raised for clean, user-facing page navigation failures."""


def list_wiki_pages(
    *,
    wiki: str | None = None,
    page_type: str | None = None,
    tag: str | None = None,
) -> list[Row]:
    """List visible, non-archived Wiki Pages with optional type/tag filters."""

    try:
        _slug, wiki_root = require_visible_wiki(wiki)
    except WikiVisibilityError as exc:
        raise WikiNavigationError(NOT_FOUND_OR_NOT_VISIBLE) from exc

    from hermes_wiki.lint import ensure_projection_current

    ensure_projection_current(wiki_root)
    try:
        with db.connect_wiki(wiki_root / "wiki.db") as conn:
            return db.list_pages(conn, page_type=page_type, tag=tag, include_archived=False)
    except sqlite3.DatabaseError as exc:
        raise WikiNavigationError(f"list-pages failed: {exc}") from exc


def open_wiki_page(
    page_id: str,
    *,
    wiki: str | None = None,
) -> str:
    """Return authoritative Markdown for a visible, non-archived Wiki Page."""

    clean_id = validate_page_id(page_id)
    try:
        _slug, wiki_root = require_visible_wiki(wiki)
    except WikiVisibilityError as exc:
        raise WikiNavigationError(NOT_FOUND_OR_NOT_VISIBLE) from exc

    from hermes_wiki.lint import ensure_projection_current

    ensure_projection_current(wiki_root)
    try:
        with db.connect_wiki(wiki_root / "wiki.db") as conn:
            row = db.get_page(conn, clean_id)
    except sqlite3.DatabaseError as exc:
        raise WikiNavigationError(f"open failed: {exc}") from exc

    if row is None or int(row.get("archived") or 0):
        raise WikiNavigationError(f"page not found: {clean_id}")

    page_path = _page_path(wiki_root, clean_id)
    if page_path is None or not page_path.is_file():
        raise WikiNavigationError(f"page not found: {clean_id}")
    try:
        metadata, _body = read_markdown(page_path)
    except (OSError, FrontmatterError) as exc:
        raise WikiNavigationError(f"page not found: {clean_id}") from exc
    if str(metadata.get("id") or "") != clean_id:
        raise WikiNavigationError(f"page not found: {clean_id}")
    return page_path.read_text(encoding="utf-8").rstrip() + "\n"


def validate_page_id(page_id: str) -> str:
    """Validate a frontmatter page id and return its normalized form."""

    clean = page_id.strip()
    if not clean:
        raise WikiNavigationError("page id is required")
    if "\n" in clean or "\r" in clean or "\\" in clean:
        raise WikiNavigationError("invalid page id")
    if clean.endswith(".md"):
        clean = clean[:-3]
    rel = Path(clean)
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise WikiNavigationError("invalid page id")
    if len(rel.parts) < 2 or rel.parts[0] not in PAGE_DIR_TYPES:
        raise WikiNavigationError("invalid page id")
    if any(part.startswith("_") for part in rel.parts):
        raise WikiNavigationError("invalid page id")
    return rel.as_posix()


def _page_path(wiki_root: Path, page_id: str) -> Path | None:
    try:
        rel = Path(validate_page_id(page_id) + ".md")
    except WikiNavigationError:
        return None
    path = (wiki_root / rel).resolve()
    try:
        path.relative_to(wiki_root.resolve())
    except ValueError:
        return None
    return path


__all__ = [
    "WikiNavigationError",
    "list_wiki_pages",
    "open_wiki_page",
    "validate_page_id",
]
