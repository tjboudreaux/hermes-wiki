"""Hermes Wiki dashboard plugin API.

Mounted by Hermes at ``/api/plugins/wiki``. Handlers are deliberately thin
wrappers around ``hermes_wiki`` core modules so CLI, agent tools, and dashboard
behavior stay aligned.
"""

from __future__ import annotations

import sqlite3
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request, status
from pydantic import BaseModel, Field

from hermes_wiki import db
from hermes_wiki.attribution import list_log_entries
from hermes_wiki.frontmatter import FrontmatterError, read_markdown
from hermes_wiki.home import WikiResolutionError, resolve_home
from hermes_wiki.lint import lint_wiki
from hermes_wiki.management import (
    NOT_FOUND_OR_NOT_VISIBLE,
    WikiManagementError,
)
from hermes_wiki.management import (
    archive_wiki as core_archive_wiki,
)
from hermes_wiki.management import (
    create_wiki as core_create_wiki,
)
from hermes_wiki.navigation import WikiNavigationError, validate_page_id
from hermes_wiki.pipeline import (
    InboxFileNotTextError,
    InboxFileTooLargeError,
    IngestError,
    delete_inbox_file,
    ingest_inbox,
    ingest_source,
    read_inbox_file,
    set_inbox_classification,
    write_inbox_file,
)
from hermes_wiki.search import search_wiki
from hermes_wiki.skills import SkillsError, read_wiki_skills, set_wiki_skill
from hermes_wiki.visibility import (
    WikiVisibilityError,
    has_write_grant,
    require_visible_wiki,
    visible_wikis,
)

router = APIRouter()
WRITE_PERMISSION_DENIED = "wiki write permission denied"


class CreateWikiRequest(BaseModel):
    """Payload for creating a Wiki from the dashboard."""

    slug: str
    domain: str | None = None


class IngestRequest(BaseModel):
    """Payload for dashboard ingest."""

    path_or_url: str | None = Field(default=None, alias="path_or_url")
    inbox: bool = False
    classifier: str | None = None


class InboxClassifyRequest(BaseModel):
    """Payload for overriding an inbox file's classifier assignment."""

    classifier: str


class InboxFileUpdateRequest(BaseModel):
    """Payload for replacing one inbox file's content."""

    content: str


class WikiSkillsUpdateRequest(BaseModel):
    """Payload for assigning per-wiki skills; omitted kinds are unchanged."""

    ingestion: str | None = None
    writing: str | None = None


@router.get("/wikis")
def list_wikis() -> list[dict[str, Any]]:
    """Return visible Wiki metadata only."""

    return [_wiki_row(row) for row in _visible_wiki_rows()]


@router.get("/search")
def global_search(q: str, limit: int = 10, wiki: str | None = None) -> dict[str, Any]:
    """Search all visible Wikis, or one visible Wiki when scoped."""

    safe_limit = max(1, min(limit, 50))
    if wiki:
        return search(wiki, q=q, limit=safe_limit)

    results: list[dict[str, Any]] = []
    for row in _visible_wiki_rows():
        slug = str(row.get("slug") or "")
        if not slug:
            continue
        try:
            wiki_rows = search_wiki(q, wiki=slug, limit=safe_limit)
        except WikiManagementError:
            continue
        results.extend(_search_row(search_row, wiki=slug) for search_row in wiki_rows)
    results.sort(key=lambda row: (float(row.get("rank") or 0.0), str(row["wiki"]), str(row["id"])))
    return {
        "wiki": None,
        "query": q,
        "results": results[:safe_limit],
    }


@router.get("/wikis/{slug}")
def get_wiki(slug: str) -> dict[str, Any]:
    """Return summary/stats for one visible Wiki."""

    _slug, wiki_root = _require_visible(slug)
    return _wiki_row(_registry_row(slug, wiki_root))


@router.get("/wikis/{slug}/pages")
def list_pages(
    slug: str,
    page: int = 1,
    page_size: int = 50,
    page_type: str | None = None,
    type: str | None = None,
    tag: str | None = None,
) -> dict[str, Any]:
    """Return a paginated, optionally-filtered page list."""

    _slug, wiki_root = _require_visible(slug)
    from hermes_wiki.lint import ensure_projection_current

    ensure_projection_current(wiki_root)
    effective_type = page_type or type
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        rows = db.list_pages(conn, page_type=effective_type, tag=tag, include_archived=False)
    total = len(rows)
    safe_page_size = max(1, min(int(page_size), 200))
    safe_page = max(1, int(page))
    start = (safe_page - 1) * safe_page_size
    items = [_page_list_row(row) for row in rows[start : start + safe_page_size]]
    return {
        "wiki": slug,
        "items": items,
        "pagination": {
            "page": safe_page,
            "page_size": safe_page_size,
            "total": total,
            "has_next": start + safe_page_size < total,
            "has_previous": safe_page > 1,
        },
        "filters": {"type": effective_type, "tag": tag},
    }


@router.get("/wikis/{slug}/pages/facets")
def get_page_facets(slug: str) -> dict[str, Any]:
    """Return lightweight unique page filter values without page row payloads."""

    _slug, wiki_root = _require_visible(slug)
    from hermes_wiki.lint import ensure_projection_current

    ensure_projection_current(wiki_root)
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        facets = db.page_facets(conn)
    return {
        "wiki": slug,
        "types": facets["types"],
        "tags": facets["tags"],
    }


@router.get("/wikis/{slug}/pages/{page_id:path}")
def get_page(slug: str, page_id: str) -> dict[str, Any]:
    """Return full page content plus metadata panels."""

    clean_page_id = _clean_page_id(page_id)
    _slug, wiki_root = _require_visible(slug)
    from hermes_wiki.lint import ensure_projection_current

    ensure_projection_current(wiki_root)
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        row = db.get_page(conn, clean_page_id)
        projected_refs = db.list_kanban_refs(conn, page_id=clean_page_id)
        all_pages = db.list_pages(conn, include_archived=False)
        inbound_pages = db.list_inbound_page_links(conn, target_page_id=clean_page_id)
    if row is None or int(row.get("archived") or 0):
        raise _not_found("page not found")
    page_path = _page_path(wiki_root, clean_page_id)
    if page_path is None or not page_path.is_file():
        raise _not_found("page not found")
    try:
        frontmatter, body = read_markdown(page_path)
    except (OSError, FrontmatterError) as exc:
        raise _not_found("page not found") from exc
    if str(frontmatter.get("id") or "") != clean_page_id:
        raise _not_found("page not found")
    history = [entry.to_row() for entry in list_log_entries(wiki_root, page_id=clean_page_id)]
    outbound = [str(item) for item in _as_sequence(frontmatter.get("links"))]
    return {
        "wiki": slug,
        "id": clean_page_id,
        "page_id": clean_page_id,
        "title": frontmatter.get("title") or row.get("title"),
        "type": frontmatter.get("type") or row.get("type"),
        "markdown": body,
        "body": body,
        "frontmatter": _jsonable(frontmatter),
        "inbound_links": int(row.get("inbound_links") or 0),
        "outbound_links": outbound,
        "outbound_pages": _linked_page_rows(all_pages, outbound),
        "inbound_pages": _inbound_page_rows(inbound_pages),
        "kanban_refs": _kanban_refs(clean_page_id, frontmatter, projected_refs),
        "history": history,
        "path": page_path.relative_to(wiki_root).as_posix(),
    }


@router.get("/wikis/{slug}/search")
def search(slug: str, q: str, limit: int = 10) -> dict[str, Any]:
    """Search one visible Wiki with FTS5/BM25 ranking."""

    _require_visible(slug)
    try:
        rows = search_wiki(q, wiki=slug, limit=max(1, min(limit, 50)))
    except WikiManagementError as exc:
        if str(exc) == NOT_FOUND_OR_NOT_VISIBLE:
            raise _not_visible() from exc
        raise _bad_request(str(exc)) from exc
    return {
        "wiki": slug,
        "query": q,
        "results": [_search_row(row, wiki=slug) for row in rows],
    }


@router.post("/wikis/{slug}/ingest")
async def ingest_route(
    slug: str,
    request: Request,
    payload: Annotated[IngestRequest | None, Body()] = None,
) -> dict[str, Any]:
    """FastAPI route wrapper for dashboard ingest."""

    return await ingest(slug, payload=payload, request=request)


async def ingest(
    slug: str,
    payload: IngestRequest | None = None,
    request: Request | None = None,
) -> dict[str, Any]:
    """Ingest a source path/URL, uploaded file, or explicit inbox batch."""

    _require_write(slug)
    payload = payload or await _payload_from_request(request)
    if payload.inbox and payload.path_or_url:
        raise _bad_request("ingest accepts either path_or_url or inbox, not both")
    if payload.inbox:
        try:
            results = ingest_inbox(wiki=slug)
        except IngestError as exc:
            raise _bad_request(str(exc)) from exc
        return {
            "wiki": slug,
            "status": "ok",
            "results": [_ingest_row(result) for result in results],
        }
    if not payload.path_or_url:
        raise _bad_request("ingest requires path_or_url or inbox=true")
    try:
        result = ingest_source(
            payload.path_or_url,
            wiki=slug,
            classifier=payload.classifier,
            author_kind="human",
        )
    except IngestError as exc:
        raise _bad_request(str(exc)) from exc
    return {"wiki": slug, "status": "ok", "result": _ingest_row(result)}


@router.get("/wikis/{slug}/inbox")
def get_inbox(slug: str) -> list[dict[str, Any]]:
    """List unprocessed inbox files and classifier/status data."""

    _slug, wiki_root = _require_visible(slug)
    from hermes_wiki.tools import wiki_inbox

    rows = wiki_inbox(slug)
    if isinstance(rows, str):
        raise _not_visible()
    return [_inbox_row(row, wiki_root) for row in rows]


@router.post("/wikis/{slug}/inbox/{filename}/classify")
def reclassify_inbox_item(
    slug: str,
    filename: str,
    payload: InboxClassifyRequest,
) -> dict[str, Any]:
    """Persist a manual classifier override for one inbox file."""

    _slug, wiki_root = _require_write(slug)
    try:
        row = set_inbox_classification(
            wiki=slug,
            filename=filename,
            classifier=payload.classifier,
            author_kind="human",
        )
    except IngestError as exc:
        raise _bad_request(str(exc)) from exc
    return _inbox_row(row, wiki_root)


@router.get("/wikis/{slug}/inbox/{filename}")
def get_inbox_file(slug: str, filename: str) -> dict[str, Any]:
    """Return the content and status metadata for one inbox file."""

    _require_visible(slug)
    try:
        row = read_inbox_file(wiki=slug, filename=filename)
    except IngestError as exc:
        raise _inbox_file_error(exc) from exc
    return _inbox_file_payload(row)


@router.put("/wikis/{slug}/inbox/{filename}")
def update_inbox_file(
    slug: str,
    filename: str,
    payload: InboxFileUpdateRequest,
) -> dict[str, Any]:
    """Replace the content of one inbox file."""

    _require_write(slug)
    try:
        row = write_inbox_file(
            wiki=slug,
            filename=filename,
            content=payload.content,
            author_kind="human",
        )
    except IngestError as exc:
        raise _inbox_file_error(exc) from exc
    return _inbox_file_payload(row)


@router.delete("/wikis/{slug}/inbox/{filename}")
def delete_inbox_file_route(slug: str, filename: str) -> dict[str, Any]:
    """Delete one inbox file and clear its status entry."""

    _require_write(slug)
    try:
        row = delete_inbox_file(wiki=slug, filename=filename, author_kind="human")
    except IngestError as exc:
        raise _inbox_file_error(exc) from exc
    return _inbox_file_payload(row)


@router.get("/wikis/{slug}/skills")
def get_wiki_skills(slug: str) -> dict[str, Any]:
    """Return per-wiki skill assignments and the shipped defaults."""

    _require_visible(slug)
    try:
        return read_wiki_skills(wiki=slug)
    except SkillsError as exc:
        if str(exc) == NOT_FOUND_OR_NOT_VISIBLE:
            raise _not_visible() from exc
        raise _bad_request(str(exc)) from exc


@router.put("/wikis/{slug}/skills")
def update_wiki_skills(slug: str, payload: WikiSkillsUpdateRequest) -> dict[str, Any]:
    """Assign per-wiki skills; only the kinds present in the payload change."""

    _require_write(slug)
    updates = {
        kind: value
        for kind, value in (("ingestion", payload.ingestion), ("writing", payload.writing))
        if value is not None
    }
    if not updates:
        raise _bad_request("at least one of ingestion or writing is required")
    result: dict[str, Any] | None = None
    try:
        for kind, value in updates.items():
            result = set_wiki_skill(kind, value, wiki=slug, author_kind="human")
    except SkillsError as exc:
        if str(exc) == NOT_FOUND_OR_NOT_VISIBLE:
            raise _not_visible() from exc
        raise _bad_request(str(exc)) from exc
    assert result is not None
    return result


@router.get("/wikis/{slug}/health")
def get_health(slug: str) -> dict[str, Any]:
    """Return structured lint report for one visible Wiki."""

    _require_visible(slug)
    try:
        report = lint_wiki(slug=slug).to_dict()
    except WikiManagementError as exc:
        if str(exc) == NOT_FOUND_OR_NOT_VISIBLE:
            raise _not_visible() from exc
        raise _bad_request(str(exc)) from exc
    findings = [_finding_row(finding) for finding in report.get("findings", [])]
    report["findings"] = findings
    return report


@router.get("/wikis/{slug}/log")
def get_log(
    slug: str,
    page: int = 1,
    page_size: int = 50,
    author: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """Return paginated attributed activity entries."""

    _slug, wiki_root = _require_visible(slug)
    all_entries = list_log_entries(wiki_root, author=author, author_kind=kind)
    safe_page_size = max(1, min(int(page_size), 200))
    safe_page = max(1, int(page))
    start = (safe_page - 1) * safe_page_size
    items = [entry.to_row() for entry in all_entries[start : start + safe_page_size]]
    return {
        "wiki": slug,
        "items": items,
        "pagination": {
            "page": safe_page,
            "page_size": safe_page_size,
            "total": len(all_entries),
            "has_next": start + safe_page_size < len(all_entries),
            "has_previous": safe_page > 1,
        },
        "filters": {"author": author, "kind": kind},
    }


@router.get("/wikis/{slug}/log/facets")
def get_log_facets(slug: str) -> dict[str, Any]:
    """Return lightweight unique activity filter values without log row payloads."""

    _slug, wiki_root = _require_visible(slug)
    entries = list_log_entries(wiki_root)
    authors = sorted({entry.author for entry in entries if entry.author})
    kinds = sorted({entry.author_kind for entry in entries if entry.author_kind})
    return {
        "wiki": slug,
        "authors": authors,
        "kinds": kinds,
    }


@router.post("/wikis")
async def create_wiki(payload: CreateWikiRequest) -> dict[str, Any]:
    """Create a Wiki using the same core path as the CLI."""

    try:
        result = core_create_wiki(payload.slug, domain=payload.domain)
    except WikiManagementError as exc:
        raise _bad_request(str(exc)) from exc
    return _wiki_row(result.registry_row)


@router.post("/wikis/{slug}/archive")
async def archive_wiki(slug: str) -> dict[str, Any]:
    """Archive a visible Wiki without deleting files."""

    _require_write(slug)
    try:
        result = core_archive_wiki(slug)
    except WikiManagementError as exc:
        if str(exc) == NOT_FOUND_OR_NOT_VISIBLE:
            raise _not_visible() from exc
        raise _bad_request(str(exc)) from exc
    return {
        "slug": result.slug,
        "path": result.path.as_posix(),
        "archived": result.archived,
        "commit_id": result.commit_id,
    }


@router.delete("/wikis/{slug}")
async def delete_wiki(slug: str, confirm: bool = False) -> dict[str, Any]:
    """Refuse plain purge requests; deletion is explicit-only/future."""

    if not confirm:
        return {
            "slug": slug,
            "status": "refused",
            "message": "explicit confirmation required; purge is not implemented",
        }
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="purge is not implemented",
    )


def _require_visible(slug: str) -> tuple[str, Path]:
    try:
        return require_visible_wiki(slug)
    except WikiVisibilityError as exc:
        raise _not_visible() from exc


def _require_write(slug: str) -> tuple[str, Path]:
    visible_slug, wiki_root = _require_visible(slug)
    if not has_write_grant(visible_slug):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=WRITE_PERMISSION_DENIED,
        )
    return visible_slug, wiki_root


def _visible_wiki_rows() -> list[dict[str, Any]]:
    """Return visible registry rows, initializing an absent empty-home registry lazily."""

    _ensure_registry_for_empty_home()
    return visible_wikis()


def _ensure_registry_for_empty_home() -> None:
    """Create the registry projection only when a request first needs it.

    Importing this plugin must not touch ``HERMES_HOME`` because Hermes mounts
    dashboard API routes while discovering plugins. A brand-new home may not
    have ``wikis/`` or ``wikis.db`` yet, so initialize just the empty registry
    here at request time and let normal populated-home reads proceed unchanged.
    """

    try:
        registry = resolve_home() / "wikis" / "wikis.db"
    except WikiResolutionError:
        return
    if registry.exists():
        return
    try:
        with db.connect_registry(registry) as conn:
            db.initialize_registry(conn)
            conn.commit()
    except (OSError, sqlite3.DatabaseError):
        return


def _registry_row(slug: str, wiki_root: Path) -> dict[str, Any]:
    registry = wiki_root.parent / "wikis.db"
    with db.connect_registry(registry) as conn:
        db.initialize_registry(conn)
        row = db.get_wiki(conn, slug)
    if row is None:
        raise _not_visible()
    return dict(row)


def _wiki_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "slug": row.get("slug"),
        "domain": row.get("domain"),
        "page_count": int(row.get("page_count") or 0),
        "source_count": int(row.get("source_count") or 0),
        "health_score": float(row.get("health_score") or 0.0),
        "last_ingest": row.get("last_ingest"),
        "last_lint": row.get("last_lint"),
        "created": row.get("created"),
        "updated": row.get("updated"),
        "path": str(row.get("path") or ""),
    }


def _page_list_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "title": row.get("title"),
        "type": row.get("type"),
        "tags": list(row.get("tags") or []),
        "sources": list(row.get("sources") or []),
        "snippet": row.get("snippet"),
        "updated": row.get("updated"),
        "author": row.get("author"),
        "author_kind": row.get("author_kind"),
        "inbound_links": int(row.get("inbound_links") or 0),
    }


def _search_row(row: Mapping[str, Any], *, wiki: str) -> dict[str, Any]:
    rank = float(row.get("rank") or 0.0)
    page_id = str(row.get("id") or "")
    return {
        "wiki": wiki,
        "id": row.get("id"),
        "title": row.get("title"),
        "type": row.get("type"),
        "tags": list(row.get("tags") or []),
        "snippet": row.get("context") or row.get("snippet") or "",
        "rank": rank,
        "score": rank,
        "href": f"/wikis/{wiki}/{page_id}",
    }


def _inbox_row(row: Mapping[str, Any], wiki_root: Path) -> dict[str, Any]:
    path = Path(str(row.get("path") or row.get("name") or ""))
    filename = str(row.get("name") or path.name)
    return {
        "filename": filename,
        "name": filename,
        "path": path.as_posix(),
        "status": row.get("status") or "not yet attempted",
        "classifier": row.get("suggested_class") or row.get("last_classification") or "unknown",
        "suggested_class": row.get("suggested_class"),
        "last_classification": row.get("last_classification"),
        "last_attempted_at": row.get("last_attempted_at"),
        "size_bytes": int(row.get("size_bytes") or _safe_size(wiki_root / path)),
    }


def _inbox_file_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    filename = str(row.get("name") or "")
    payload = dict(row)
    payload["filename"] = filename
    return payload


def _inbox_file_error(exc: IngestError) -> HTTPException:
    if isinstance(exc, InboxFileTooLargeError):
        return HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc))
    if isinstance(exc, InboxFileNotTextError):
        return HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc))
    if str(exc) == NOT_FOUND_OR_NOT_VISIBLE:
        return _not_visible()
    if str(exc) == "inbox file not found":
        return _not_found(str(exc))
    return _bad_request(str(exc))


def _finding_row(finding: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(finding)
    row.setdefault("check", row.get("code") or "unknown")
    row.setdefault("severity", "low")
    row.setdefault("message", "")
    return _jsonable(row)


def _ingest_row(result: Any) -> dict[str, Any]:
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
        "drift_detected": result.drift_detected,
    }


async def _payload_from_request(request: Request | None) -> IngestRequest:
    if request is None:
        return IngestRequest()
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        classifier = _form_text(form, "classifier")
        if _form_text(form, "inbox") in {"1", "true", "yes"}:
            return IngestRequest(inbox=True, classifier=classifier)
        path_or_url = _form_text(form, "path_or_url") or _form_text(form, "url")
        if path_or_url:
            return IngestRequest(path_or_url=path_or_url, classifier=classifier)
        for value in form.values():
            filename = getattr(value, "filename", None)
            read = getattr(value, "read", None)
            if filename and callable(read):
                suffix = Path(str(filename)).suffix or ".txt"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                    handle.write(await read())
                    return IngestRequest(path_or_url=handle.name, classifier=classifier)
    if content_type.startswith("application/json"):
        raw = await request.json()
        if isinstance(raw, Mapping):
            return IngestRequest.model_validate(raw)
    return IngestRequest()


def _form_text(form: Mapping[str, Any], key: str) -> str | None:
    value = form.get(key)
    if value is None or hasattr(value, "filename"):
        return None
    text = str(value).strip()
    return text or None


def _clean_page_id(page_id: str) -> str:
    try:
        return validate_page_id(page_id)
    except WikiNavigationError as exc:
        raise _not_found("page not found") from exc


def _page_path(wiki_root: Path, page_id: str) -> Path | None:
    rel = Path(page_id + ".md")
    path = (wiki_root / rel).resolve()
    try:
        path.relative_to(wiki_root.resolve())
    except ValueError:
        return None
    return path


def _kanban_refs(
    page_id: str,
    frontmatter: Mapping[str, Any],
    projected_refs: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    refs: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in projected_refs:
        key = (
            str(row.get("page_id") or page_id),
            str(row.get("task_id") or ""),
            str(row.get("direction") or "page->task"),
        )
        if key[1]:
            refs[key] = {
                "page_id": key[0],
                "task_id": key[1],
                "direction": key[2],
                "created": row.get("created"),
            }
    for row in _as_sequence(frontmatter.get("kanban_refs")):
        if not isinstance(row, Mapping):
            continue
        key = (
            page_id,
            str(row.get("task_id") or ""),
            str(row.get("direction") or "page->task"),
        )
        if key[1]:
            refs.setdefault(
                key,
                {
                    "page_id": key[0],
                    "task_id": key[1],
                    "direction": key[2],
                    "created": row.get("created"),
                },
            )
    return [_decorate_kanban_ref(refs[key]) for key in sorted(refs)]


def _decorate_kanban_ref(row: dict[str, Any]) -> dict[str, Any]:
    task_id = str(row.get("task_id") or "")
    try:
        from hermes_wiki.kanban_link import read_task

        task = read_task(task_id) if task_id else None
    except Exception:
        task = None
    row["task_title"] = None if task is None else task.title
    row["task"] = None if task is None else _jsonable(dict(task.raw or {}))
    return row


def _linked_page_rows(
    all_pages: Sequence[Mapping[str, Any]],
    page_ids: Sequence[str],
) -> list[dict[str, Any]]:
    by_id = {str(row.get("id") or ""): row for row in all_pages}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page_id in page_ids:
        clean_id = str(page_id).strip().removesuffix(".md")
        if not clean_id or clean_id in seen:
            continue
        seen.add(clean_id)
        row = by_id.get(clean_id)
        rows.append(_page_reference_row(clean_id, row))
    return rows


def _inbound_page_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        _page_reference_row(str(row.get("id") or ""), row)
        for row in rows
        if str(row.get("id") or "")
    ]


def _page_reference_row(page_id: str, row: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        "id": page_id,
        "title": row.get("title") if row is not None else page_id,
        "type": row.get("type") if row is not None else None,
        "exists": row is not None,
    }


def _as_sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        return list(value)
    return [value]


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(inner) for key, inner in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [_jsonable(item) for item in value]
    try:
        import json

        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def _not_visible() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_OR_NOT_VISIBLE)


def _not_found(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
