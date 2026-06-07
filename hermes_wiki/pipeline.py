"""Single-source ingest pipeline for Hermes LLM Wikis."""

from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import inspect
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol, cast
from urllib.parse import urlparse

from hermes_wiki import db, git_ops, projection
from hermes_wiki.attribution import append_log_entry, record_change, resolve_actor
from hermes_wiki.classifiers import classify_source as _classify_source
from hermes_wiki.frontmatter import FrontmatterError, read_markdown, write_markdown
from hermes_wiki.kanban_link import auto_link_ingest_pages
from hermes_wiki.management import (
    NOT_FOUND_OR_NOT_VISIBLE,
    WikiManagementError,
    ensure_wiki_mutable,
)
from hermes_wiki.models import ClassLabel, WikiPage

MAX_INGEST_BYTES = 50 * 1024 * 1024
RAW_SUBDIRS = {
    "article": "articles",
    "paper": "papers",
    "transcript": "transcripts",
    "unknown": "unknown",
}
INBOX_STATUS_REL = Path("raw/inbox_status.json")


class IngestError(RuntimeError):
    """Raised for clean user-facing ingest failures."""


class InboxFileTooLargeError(IngestError):
    """Raised when an inbox file exceeds the Phase-1 ingest size cap."""


class InboxFileNotTextError(IngestError):
    """Raised when an inbox file is not valid UTF-8 text."""


class ProcessorError(RuntimeError):
    """Raised when a source processor cannot produce pages."""


@dataclass(frozen=True, slots=True)
class ProcessRequest:
    """Input given to a processor after classification and snapshot planning."""

    source_ref: str
    source_bytes: bytes
    source_text: str
    title: str
    source_slug: str
    label: ClassLabel
    snapshot_relpath: str
    source_page_id: str
    source_page_filename: str
    existing_pages: tuple[ExistingPage, ...]
    now: str
    today: str


@dataclass(frozen=True, slots=True)
class ExistingPage:
    """Small index of an existing Wiki Page used for cross-link propagation."""

    id: str
    title: str
    path: Path
    inbound_links: int
    links: tuple[str, ...]
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GeneratedPage:
    """A Wiki Page planned by a processor."""

    page: WikiPage


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Observable result of one ingest run."""

    wiki: str
    classified_as: str
    source_id: str
    sha256: str
    pages_created: tuple[str, ...]
    pages_updated: tuple[str, ...]
    raw_snapshot: str
    source_url: str | None
    commit_id: str | None
    skipped: bool = False
    message: str = ""
    drift_detected: bool = False


@dataclass(frozen=True, slots=True)
class _SourceVersionPlan:
    """Version metadata for the Source Snapshot being materialized."""

    version: int
    previous_source_id: str | None
    drift_detected: bool
    superseded_source_ids: tuple[str, ...] = ()


class Processor(Protocol):
    """Processor interface for turning one Source Snapshot into Wiki Pages."""

    def process(self, request: ProcessRequest) -> list[GeneratedPage]:
        """Return generated Wiki Pages."""


class DefaultProcessor:
    """Default deterministic processor that creates Source + concept/entity pages."""

    def process(self, request: ProcessRequest) -> list[GeneratedPage]:
        source_links = [
            page
            for page in request.existing_pages
            if _mentions_title(request.source_text, page.title)
        ]
        source_page = WikiPage(
            id=request.source_page_id,
            title=request.title,
            type="source",
            body=_source_page_body(request, source_links),
            tags=("ingest", request.label.name),
            sources=(request.snapshot_relpath,),
            links=tuple(page.id for page in source_links),
            confidence=request.label.confidence,
        )

        derived_title, derived_type = _derived_page_title_and_type(request)
        derived_dir = "entities" if derived_type == "entity" else "concepts"
        derived_id = f"{derived_dir}/{_slugify(derived_title)}"
        derived_page = WikiPage(
            id=derived_id,
            title=derived_title,
            type=derived_type,
            body=_derived_page_body(derived_title, request),
            tags=tuple(tag for tag in ("ingest", request.label.name) if tag),
            sources=(request.snapshot_relpath,),
            links=(request.source_page_id,),
            confidence=request.label.confidence,
        )
        return [GeneratedPage(source_page), GeneratedPage(derived_page)]


class CustomProcessor:
    """Trusted custom processor loaded from a per-wiki path+sha record."""

    def __init__(self, *, name: str, plugin_path: Path) -> None:
        self.name = name
        self.plugin_path = plugin_path

    def process(self, request: ProcessRequest) -> list[GeneratedPage]:
        module = _load_processor_module(self.name, self.plugin_path)
        process = getattr(module, "process", None)
        if not callable(process):
            raise ProcessorError(f"trusted processor {self.name} does not export process")
        result = _call_custom_processor(process, request)
        if not isinstance(result, list):
            raise ProcessorError(f"trusted processor {self.name} must return a list")
        return [_coerce_generated_page(item) for item in result]


def ingest_source(
    source_ref: str,
    *,
    wiki: str | None = None,
    author: str | None = None,
    author_kind: str | None = None,
    classifier: str | None = None,
    processor: Processor | None = None,
) -> IngestResult:
    """Ingest exactly one local path or URL into a Wiki."""

    try:
        resolved = ensure_wiki_mutable(slug=wiki)
    except WikiManagementError as exc:
        raise IngestError(NOT_FOUND_OR_NOT_VISIBLE) from exc

    acting_author, acting_kind = resolve_actor(author=author, author_kind=author_kind)
    source = _read_source(source_ref)
    wiki_root = resolved.path
    if len(source.content) > MAX_INGEST_BYTES:
        _record_direct_inbox_status_if_applicable(
            wiki_root,
            source=source,
            status="oversized",
            classified_as="oversized",
            author=acting_author,
            author_kind=acting_kind,
        )
        raise IngestError("oversized source exceeds the 50MB Phase 1 ingest cap")
    return _ingest_source_content(
        source_ref,
        source=source,
        wiki_slug=resolved.slug,
        wiki_root=wiki_root,
        author=acting_author,
        author_kind=acting_kind,
        processor=processor,
        remove_source_path=None,
        preclassified_label=_forced_label(classifier),
    )


def ingest_inbox(
    *,
    wiki: str | None = None,
    author: str | None = None,
    author_kind: str | None = None,
    processor: Processor | None = None,
) -> list[IngestResult]:
    """Explicitly process the pending inbox for one Wiki.

    This is intentionally separate from ``ingest_source`` so a missing path can
    never be interpreted as batch inbox intent.
    """

    try:
        resolved = ensure_wiki_mutable(slug=wiki)
    except WikiManagementError as exc:
        raise IngestError(NOT_FOUND_OR_NOT_VISIBLE) from exc

    acting_author, acting_kind = resolve_actor(author=author, author_kind=author_kind)
    inbox = resolved.path / "raw" / "inbox"
    if not inbox.exists():
        return []

    results: list[IngestResult] = []
    for inbox_path in sorted(item for item in inbox.iterdir() if item.is_file()):
        source = _read_source(str(inbox_path))
        if len(source.content) > MAX_INGEST_BYTES:
            result = _record_inbox_attempt(
                resolved.path,
                inbox_path=inbox_path,
                status="oversized",
                classified_as="oversized",
                author=acting_author,
                author_kind=acting_kind,
            )
            results.append(result)
            continue
        recorded = _load_inbox_status(resolved.path).get(inbox_path.name, {})
        override = str(recorded.get("classified_as") or "").strip()
        label = (
            _forced_label(override)
            if str(recorded.get("status") or "") == "override" and override
            else classify_source(source.name, source.content, wiki_root=resolved.path)
        )
        if label is None:
            label = classify_source(source.name, source.content, wiki_root=resolved.path)
        if label.name == "unknown":
            result = _record_inbox_attempt(
                resolved.path,
                inbox_path=inbox_path,
                status="unknown",
                classified_as=label.name,
                author=acting_author,
                author_kind=acting_kind,
            )
            results.append(result)
            continue
        result = _ingest_source_content(
            str(inbox_path),
            source=source,
            wiki_slug=resolved.slug,
            wiki_root=resolved.path,
            author=acting_author,
            author_kind=acting_kind,
            processor=processor,
            remove_source_path=inbox_path,
            preclassified_label=label,
        )
        _clear_inbox_status(resolved.path, inbox_path.name)
        results.append(replace(result, message=inbox_path.name))
    return results


def set_inbox_classification(
    *,
    wiki: str | None,
    filename: str,
    classifier: str,
    author: str | None = None,
    author_kind: str | None = None,
) -> dict[str, object]:
    """Persist a manual classifier override for one pending inbox file."""

    try:
        resolved = ensure_wiki_mutable(slug=wiki)
    except WikiManagementError as exc:
        raise IngestError(NOT_FOUND_OR_NOT_VISIBLE) from exc

    clean_filename = _clean_inbox_filename(filename)
    label = _forced_label(classifier)
    if label is None:
        raise IngestError("classifier is required")
    inbox_path = resolved.path / "raw" / "inbox" / clean_filename
    if not inbox_path.is_file():
        raise IngestError("inbox file not found")
    if inbox_path.stat().st_size > MAX_INGEST_BYTES:
        raise IngestError("oversized inbox files cannot be re-classified")

    acting_author, acting_kind = resolve_actor(author=author, author_kind=author_kind)
    now = _utc_now()
    relpath = inbox_path.relative_to(resolved.path).as_posix()
    digest = hashlib.sha256(inbox_path.read_bytes()).hexdigest()
    status_path = resolved.path / INBOX_STATUS_REL
    log_path = resolved.path / "log.md"
    touched: dict[Path, bytes | None] = {}
    _remember(touched, status_path)
    _remember(touched, log_path)
    try:
        statuses = _load_inbox_status(resolved.path)
        statuses[clean_filename] = {
            "status": "override",
            "classified_as": label.name,
            "last_attempted_at": now,
            "overridden_at": now,
            "path": relpath,
            "sha256": digest,
        }
        _write_inbox_status(resolved.path, statuses)
        append_log_entry(
            resolved.path,
            timestamp=now,
            action="inbox-override",
            target=relpath,
            author=acting_author,
            author_kind=acting_kind,
            details={"source": relpath, "class": label.name},
        )
        commit = git_ops.commit_change(
            resolved.path,
            action="inbox",
            what=f"override {clean_filename} -> {label.name}",
            author=acting_author,
        )
    except Exception:
        _restore(touched)
        raise
    return {
        "wiki": resolved.slug,
        "name": clean_filename,
        "path": relpath,
        "status": "override",
        "suggested_class": label.name,
        "last_classification": label.name,
        "last_attempted_at": now,
        "size_bytes": inbox_path.stat().st_size,
        "commit_id": commit.commit_id,
    }


def _inbox_file_detail(
    wiki_root: Path,
    *,
    slug: str,
    clean_filename: str,
    inbox_path: Path,
    content: str,
) -> dict[str, object]:
    recorded = _load_inbox_status(wiki_root).get(clean_filename, {})
    status = str(recorded.get("status") or "not yet attempted")
    classifier = str(recorded.get("classified_as") or "unknown")
    return {
        "wiki": slug,
        "name": clean_filename,
        "path": inbox_path.relative_to(wiki_root).as_posix(),
        "content": content,
        "size_bytes": inbox_path.stat().st_size,
        "status": status,
        "classifier": classifier,
    }


def read_inbox_file(*, wiki: str | None, filename: str) -> dict[str, object]:
    """Return the UTF-8 content and status metadata for one inbox file."""

    from hermes_wiki.visibility import WikiVisibilityError, require_visible_wiki

    try:
        slug, wiki_root = require_visible_wiki(wiki)
    except WikiVisibilityError as exc:
        raise IngestError(NOT_FOUND_OR_NOT_VISIBLE) from exc
    clean_filename = _clean_inbox_filename(filename)
    inbox_path = wiki_root / "raw" / "inbox" / clean_filename
    if not inbox_path.is_file():
        raise IngestError("inbox file not found")
    if inbox_path.stat().st_size > MAX_INGEST_BYTES:
        raise InboxFileTooLargeError("oversized inbox files cannot be read")
    try:
        content = inbox_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise InboxFileNotTextError("inbox file is not valid UTF-8 text") from exc
    return _inbox_file_detail(
        wiki_root,
        slug=slug,
        clean_filename=clean_filename,
        inbox_path=inbox_path,
        content=content,
    )


def write_inbox_file(
    *,
    wiki: str | None,
    filename: str,
    content: str,
    author: str | None = None,
    author_kind: str | None = None,
) -> dict[str, object]:
    """Replace the content of one existing inbox file."""

    try:
        resolved = ensure_wiki_mutable(slug=wiki)
    except WikiManagementError as exc:
        raise IngestError(NOT_FOUND_OR_NOT_VISIBLE) from exc

    clean_filename = _clean_inbox_filename(filename)
    inbox_path = resolved.path / "raw" / "inbox" / clean_filename
    if not inbox_path.is_file():
        raise IngestError("inbox file not found")
    if inbox_path.stat().st_size > MAX_INGEST_BYTES:
        raise InboxFileTooLargeError("oversized inbox files cannot be edited")
    if len(content.encode("utf-8")) > MAX_INGEST_BYTES:
        raise InboxFileTooLargeError("edited content exceeds the ingest size limit")

    acting_author, acting_kind = resolve_actor(author=author, author_kind=author_kind)
    now = _utc_now()
    relpath = inbox_path.relative_to(resolved.path).as_posix()
    status_path = resolved.path / INBOX_STATUS_REL
    log_path = resolved.path / "log.md"
    touched: dict[Path, bytes | None] = {}
    _remember(touched, inbox_path)
    _remember(touched, status_path)
    _remember(touched, log_path)
    try:
        inbox_path.write_text(content, encoding="utf-8")
        digest = hashlib.sha256(inbox_path.read_bytes()).hexdigest()
        statuses = _load_inbox_status(resolved.path)
        entry = statuses.get(clean_filename, {})
        entry.update(
            {
                "status": "edited",
                "last_attempted_at": now,
                "path": relpath,
                "sha256": digest,
            }
        )
        statuses[clean_filename] = entry
        _write_inbox_status(resolved.path, statuses)
        append_log_entry(
            resolved.path,
            timestamp=now,
            action="inbox-edit",
            target=relpath,
            author=acting_author,
            author_kind=acting_kind,
            details={"source": relpath, "bytes": str(inbox_path.stat().st_size)},
        )
        git_ops.commit_change(
            resolved.path,
            action="inbox",
            what=f"edit {clean_filename}",
            author=acting_author,
        )
    except Exception:
        _restore(touched)
        raise
    return _inbox_file_detail(
        resolved.path,
        slug=resolved.slug,
        clean_filename=clean_filename,
        inbox_path=inbox_path,
        content=content,
    )


def delete_inbox_file(
    *,
    wiki: str | None,
    filename: str,
    author: str | None = None,
    author_kind: str | None = None,
) -> dict[str, object]:
    """Delete one inbox file and clear its persisted status entry."""

    try:
        resolved = ensure_wiki_mutable(slug=wiki)
    except WikiManagementError as exc:
        raise IngestError(NOT_FOUND_OR_NOT_VISIBLE) from exc

    clean_filename = _clean_inbox_filename(filename)
    inbox_path = resolved.path / "raw" / "inbox" / clean_filename
    if not inbox_path.is_file():
        raise IngestError("inbox file not found")

    acting_author, acting_kind = resolve_actor(author=author, author_kind=author_kind)
    now = _utc_now()
    relpath = inbox_path.relative_to(resolved.path).as_posix()
    status_path = resolved.path / INBOX_STATUS_REL
    log_path = resolved.path / "log.md"
    touched: dict[Path, bytes | None] = {}
    _remember(touched, inbox_path)
    _remember(touched, status_path)
    _remember(touched, log_path)
    try:
        inbox_path.unlink()
        _clear_inbox_status(resolved.path, clean_filename)
        append_log_entry(
            resolved.path,
            timestamp=now,
            action="inbox-delete",
            target=relpath,
            author=acting_author,
            author_kind=acting_kind,
            details={"source": relpath},
        )
        commit = git_ops.commit_change(
            resolved.path,
            action="inbox",
            what=f"delete {clean_filename}",
            author=acting_author,
        )
    except Exception:
        _restore(touched)
        raise
    return {
        "wiki": resolved.slug,
        "name": clean_filename,
        "path": relpath,
        "status": "deleted",
        "commit_id": commit.commit_id,
    }


def _ingest_source_content(
    source_ref: str,
    *,
    source: _SourceContent,
    wiki_slug: str,
    wiki_root: Path,
    author: str,
    author_kind: str,
    processor: Processor | None,
    remove_source_path: Path | None,
    preclassified_label: ClassLabel | None = None,
) -> IngestResult:
    with _ingest_lock(wiki_root):
        return _ingest_source_content_locked(
            source_ref,
            source=source,
            wiki_slug=wiki_slug,
            wiki_root=wiki_root,
            author=author,
            author_kind=author_kind,
            processor=processor,
            remove_source_path=remove_source_path,
            preclassified_label=preclassified_label,
        )


def _ingest_source_content_locked(
    source_ref: str,
    *,
    source: _SourceContent,
    wiki_slug: str,
    wiki_root: Path,
    author: str,
    author_kind: str,
    processor: Processor | None,
    remove_source_path: Path | None,
    preclassified_label: ClassLabel | None = None,
) -> IngestResult:
    label = preclassified_label or classify_source(source.name, source.content, wiki_root=wiki_root)
    digest = hashlib.sha256(source.content).hexdigest()
    now = _utc_now()
    today = now[:10]
    existing_pages = tuple(_existing_pages(wiki_root))

    version_plan_or_skip = _plan_source_version(wiki_root, source=source, digest=digest)
    if isinstance(version_plan_or_skip, IngestResult):
        return version_plan_or_skip
    version_plan = version_plan_or_skip

    source_slug = _source_slug(source.name, source.text)
    raw_relpath = _unique_raw_relpath(
        wiki_root,
        label=label.name,
        today=today,
        version=version_plan.version,
        slug=source_slug,
        suffix=source.suffix,
    )
    source_page_id = _unique_page_id(wiki_root, f"sources/{today}-{source_slug}")
    request = ProcessRequest(
        source_ref=source_ref,
        source_bytes=source.content,
        source_text=source.text,
        title=_title_from_source(source.name, source.text),
        source_slug=source_slug,
        label=label,
        snapshot_relpath=raw_relpath,
        source_page_id=source_page_id,
        source_page_filename=f"{source_page_id.split('/')[-1]}.md",
        existing_pages=existing_pages,
        now=now,
        today=today,
    )
    selected_processor = (
        processor or _trusted_processor_for_label(wiki_root, label.name) or DefaultProcessor()
    )

    try:
        planned_pages = selected_processor.process(request)
        if not planned_pages:
            raise ProcessorError("processor produced no pages")
        return _materialize_ingest(
            wiki_root,
            wiki_slug=wiki_slug,
            source=source,
            label=label,
            request=request,
            planned_pages=planned_pages,
            digest=digest,
            now=now,
            author=author,
            author_kind=author_kind,
            remove_source_path=remove_source_path,
            version_plan=version_plan,
        )
    except Exception as exc:
        if isinstance(exc, IngestError):
            raise
        raise IngestError(str(exc)) from exc


def search_wiki(
    query: str,
    *,
    wiki: str | None = None,
    limit: int = 5,
) -> list[dict[str, object]]:
    """Run a simple FTS5 search against one visible Wiki."""

    from hermes_wiki.search import search_wiki as _search_wiki

    try:
        return _search_wiki(query, wiki=wiki, limit=limit)
    except WikiManagementError as exc:
        raise IngestError(str(exc)) from exc


def list_inbox(*, wiki: str | None = None) -> list[dict[str, str]]:
    """List unprocessed inbox files for one Wiki."""

    from hermes_wiki.visibility import WikiVisibilityError, require_visible_wiki

    try:
        _slug, wiki_root = require_visible_wiki(wiki)
    except WikiVisibilityError as exc:
        raise IngestError(NOT_FOUND_OR_NOT_VISIBLE) from exc
    inbox = wiki_root / "raw" / "inbox"
    if not inbox.exists():
        return []
    statuses = _load_inbox_status(wiki_root)
    rows: list[dict[str, str]] = []
    for path in sorted(item for item in inbox.iterdir() if item.is_file()):
        recorded = statuses.get(path.name, {})
        status = str(recorded.get("status") or "")
        if not status:
            status = "oversized" if path.stat().st_size > MAX_INGEST_BYTES else "not yet attempted"
        rows.append({"path": str(path), "name": path.name, "status": status})
    return rows


def _record_direct_inbox_status_if_applicable(
    wiki_root: Path,
    *,
    source: _SourceContent,
    status: str,
    classified_as: str,
    author: str,
    author_kind: str,
) -> None:
    if source.url is not None:
        return
    try:
        path = Path(source.ref).resolve()
        path.relative_to((wiki_root / "raw" / "inbox").resolve())
    except ValueError:
        return
    if path.parent != (wiki_root / "raw" / "inbox").resolve():
        return
    _record_inbox_attempt(
        wiki_root,
        inbox_path=path,
        status=status,
        classified_as=classified_as,
        author=author,
        author_kind=author_kind,
    )


def _record_inbox_attempt(
    wiki_root: Path,
    *,
    inbox_path: Path,
    status: str,
    classified_as: str,
    author: str,
    author_kind: str,
) -> IngestResult:
    now = _utc_now()
    relpath = inbox_path.relative_to(wiki_root).as_posix()
    digest = hashlib.sha256(inbox_path.read_bytes()).hexdigest()
    status_path = wiki_root / INBOX_STATUS_REL
    log_path = wiki_root / "log.md"
    touched: dict[Path, bytes | None] = {}
    _remember(touched, status_path)
    _remember(touched, log_path)
    try:
        statuses = _load_inbox_status(wiki_root)
        statuses[inbox_path.name] = {
            "status": status,
            "classified_as": classified_as,
            "last_attempted_at": now,
            "path": relpath,
            "sha256": digest,
        }
        _write_inbox_status(wiki_root, statuses)
        _append_inbox_attempt_log(
            wiki_root,
            now=now,
            source_ref=relpath,
            status=status,
            classified_as=classified_as,
            author=author,
            author_kind=author_kind,
        )
        with db.connect_wiki(wiki_root / "wiki.db") as conn:
            db.insert_ingest_log(
                conn,
                ingested_at=now,
                source_type=classified_as,
                source_url=None,
                source_path=relpath,
                sha256=digest,
                pages_created=[],
                pages_updated=[],
                drift_detected=0,
                author=author,
                author_kind=author_kind,
            )
            conn.commit()
        commit = git_ops.commit_change(
            wiki_root,
            action="inbox",
            what=f"{status} {inbox_path.name}",
            author=author,
        )
    except Exception:
        _restore(touched)
        raise
    return IngestResult(
        wiki=wiki_root.name,
        classified_as=classified_as,
        source_id=relpath,
        sha256=digest,
        pages_created=(),
        pages_updated=(),
        raw_snapshot=relpath,
        source_url=None,
        commit_id=commit.commit_id,
        skipped=True,
        message=inbox_path.name,
    )


def _load_inbox_status(wiki_root: Path) -> dict[str, dict[str, str]]:
    status_path = wiki_root / INBOX_STATUS_REL
    if not status_path.exists():
        return {}
    try:
        loaded = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
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


def _write_inbox_status(wiki_root: Path, statuses: dict[str, dict[str, str]]) -> None:
    status_path = wiki_root / INBOX_STATUS_REL
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(
        json.dumps(statuses, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _clear_inbox_status(wiki_root: Path, filename: str) -> None:
    statuses = _load_inbox_status(wiki_root)
    if filename not in statuses:
        return
    statuses.pop(filename, None)
    _write_inbox_status(wiki_root, statuses)


def _append_inbox_attempt_log(
    wiki_root: Path,
    *,
    now: str,
    source_ref: str,
    status: str,
    classified_as: str,
    author: str,
    author_kind: str,
) -> None:
    append_log_entry(
        wiki_root,
        timestamp=now,
        action="inbox",
        target=source_ref,
        author=author,
        author_kind=author_kind,
        details={"source": source_ref, "status": status, "class": classified_as},
    )


def _materialize_ingest(
    wiki_root: Path,
    *,
    wiki_slug: str,
    source: _SourceContent,
    label: ClassLabel,
    request: ProcessRequest,
    planned_pages: list[GeneratedPage],
    digest: str,
    now: str,
    author: str,
    author_kind: str,
    version_plan: _SourceVersionPlan,
    remove_source_path: Path | None = None,
) -> IngestResult:
    touched: dict[Path, bytes | None] = {}
    wiki_db = wiki_root / "wiki.db"
    _remember(touched, wiki_db)
    _remember(touched, wiki_root / "index.md")
    _remember(touched, wiki_root / "log.md")
    raw_path = wiki_root / request.snapshot_relpath
    _remember(touched, raw_path)
    if remove_source_path is not None:
        _remember(touched, remove_source_path)

    pages_created: list[str] = []
    pages_updated: list[str] = []
    source_id = request.snapshot_relpath
    try:
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(source.content)
        if remove_source_path is not None and remove_source_path.resolve() != raw_path.resolve():
            remove_source_path.unlink()
        for generated in planned_pages:
            page = generated.page
            page_path = wiki_root / f"{page.id}.md"
            _remember(touched, page_path)
            existed = page_path.exists()
            _write_or_merge_page(
                page_path,
                page=page,
                now=now,
                author=author,
                author_kind=author_kind,
                source_id=source_id,
            )
            (pages_updated if existed else pages_created).append(page.id)

        updated_existing = _cross_link_existing_pages(
            wiki_root,
            request=request,
            planned_ids=[generated.page.id for generated in planned_pages],
            now=now,
            author=author,
            author_kind=author_kind,
            touched=touched,
        )
        pages_updated.extend(updated_existing)
        auto_link_ingest_pages(
            wiki_root,
            source_text=source.text,
            page_ids=[generated.page.id for generated in planned_pages],
            created=now,
        )
        _rewrite_index(wiki_root)
        _record_page_changes_for_ingest(
            wiki_root,
            now=now,
            source_ref=source.ref,
            classified_as=label.name,
            pages_created=pages_created,
            pages_updated=pages_updated,
            author=author,
            author_kind=author_kind,
        )
        rebuild = projection.rebuild_projection(
            wiki_root,
            rebuild_reason="ingest",
            author=author,
            author_kind=author_kind,
        )
        if rebuild.status != "active":
            raise IngestError(f"projection rebuild failed: {rebuild.notes}")
        _record_ingest_rows(
            wiki_root,
            source_id=source_id,
            source=source,
            label=label,
            digest=digest,
            now=now,
            pages_created=pages_created,
            pages_updated=pages_updated,
            author=author,
            author_kind=author_kind,
            version_plan=version_plan,
        )
        _update_registry_after_ingest(wiki_root, wiki_slug=wiki_slug, now=now)
        commit = git_ops.commit_change(
            wiki_root,
            action="ingest",
            what=label.name,
            author=author,
        )
    except Exception:
        _restore(touched)
        raise
    return IngestResult(
        wiki=wiki_slug,
        classified_as=label.name,
        source_id=source_id,
        sha256=digest,
        pages_created=tuple(pages_created),
        pages_updated=tuple(dict.fromkeys(pages_updated)),
        raw_snapshot=source_id,
        source_url=source.url,
        commit_id=commit.commit_id,
        message=f"ingested {source.ref}",
        drift_detected=version_plan.drift_detected,
    )


def classify_source(
    name: str,
    content: bytes,
    *,
    wiki_root: Path | None = None,
) -> ClassLabel:
    """Deterministically classify a Source Snapshot through the classifier chain."""

    return _classify_source(name, content, wiki_root=wiki_root)


def _forced_label(classifier: str | None) -> ClassLabel | None:
    if classifier is None:
        return None
    clean = classifier.strip()
    if not clean:
        return None
    if "\n" in clean or "\r" in clean or "/" in clean or "\\" in clean:
        raise IngestError("invalid classifier")
    return ClassLabel(name=clean, confidence="forced", reason="agent-forced")


def _clean_inbox_filename(filename: str) -> str:
    clean = filename.strip()
    if not clean:
        raise IngestError("filename is required")
    if Path(clean).name != clean or "/" in clean or "\\" in clean:
        raise IngestError("invalid inbox filename")
    return clean


def _trusted_processor_for_label(wiki_root: Path, label_name: str) -> Processor | None:
    wiki_db = wiki_root / "wiki.db"
    if not wiki_db.exists():
        return None
    root = wiki_root.resolve()
    with db.connect_wiki(wiki_db) as conn:
        rows = [
            row
            for row in db.list_trusted_plugins(conn)
            if str(row.get("kind")) == "processor" and str(row.get("name")) == label_name
        ]
    if not rows:
        return None
    row = sorted(rows, key=lambda item: str(item.get("trusted_at") or ""))[-1]
    plugin_path = (wiki_root / str(row.get("path") or "")).resolve()
    try:
        plugin_path.relative_to(root)
    except ValueError:
        return None
    if not plugin_path.is_file():
        return None
    if projection.sha256_file(plugin_path) != str(row.get("sha256") or ""):
        return None
    return CustomProcessor(name=label_name, plugin_path=plugin_path)


def _load_processor_module(processor_name: str, plugin_path: Path) -> ModuleType:
    digest = projection.sha256_file(plugin_path)[:16]
    module_name = f"hermes_wiki_trusted_processor_{processor_name}_{digest}"
    spec = importlib.util.spec_from_file_location(module_name, plugin_path)
    if spec is None or spec.loader is None:
        raise ProcessorError(f"could not load trusted processor: {processor_name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _call_custom_processor(process: Any, request: ProcessRequest) -> Any:
    try:
        signature = inspect.signature(process)
    except (TypeError, ValueError):
        return process(request)
    parameters = list(signature.parameters.values())
    required_keyword_only = [
        parameter
        for parameter in parameters
        if parameter.kind is parameter.KEYWORD_ONLY
        and parameter.default is inspect.Signature.empty
    ]
    if required_keyword_only:
        names = ", ".join(parameter.name for parameter in required_keyword_only)
        raise ProcessorError(
            "trusted processor signature is unsupported: required keyword-only "
            f"parameter(s) {names}; accept a single ProcessRequest instead"
        )
    positional = [
        parameter
        for parameter in parameters
        if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
    ]
    required = [
        parameter
        for parameter in positional
        if parameter.default is inspect.Signature.empty
    ]
    if len(required) <= 1:
        return process(request)
    safe_name = Path(request.source_ref).name or request.source_page_filename
    with tempfile.TemporaryDirectory(prefix="hermes-wiki-process-") as temp_dir:
        raw_path = Path(temp_dir) / safe_name
        raw_path.write_bytes(request.source_bytes)
        return process(raw_path, request.label)


def _coerce_generated_page(item: Any) -> GeneratedPage:
    if isinstance(item, GeneratedPage):
        return item
    if isinstance(item, WikiPage):
        return GeneratedPage(item)
    if isinstance(item, dict):
        data = dict(item)
        for key in ("tags", "sources", "links"):
            if key in data and not isinstance(data[key], tuple):
                data[key] = tuple(data[key] or ())
        return GeneratedPage(WikiPage(**data))
    raise ProcessorError("trusted processor returned an unsupported page object")


@dataclass(frozen=True, slots=True)
class _SourceContent:
    ref: str
    name: str
    suffix: str
    content: bytes
    text: str
    url: str | None


def _read_source(source_ref: str) -> _SourceContent:
    parsed = urlparse(source_ref)
    if parsed.scheme in {"http", "https"}:
        try:
            with urllib.request.urlopen(source_ref, timeout=15) as response:
                content = response.read(MAX_INGEST_BYTES + 1)
        except urllib.error.URLError as exc:
            raise IngestError(f"failed to fetch URL: {exc}") from exc
        name = Path(parsed.path).name or parsed.netloc
        return _SourceContent(
            ref=source_ref,
            name=name,
            suffix=Path(name).suffix or ".txt",
            content=content,
            text=_decode_text(content),
            url=source_ref,
        )
    if parsed.scheme and parsed.scheme != "file":
        raise IngestError(f"unsupported source URL scheme: {parsed.scheme}")
    path = Path(parsed.path if parsed.scheme == "file" else source_ref).expanduser()
    if not path.is_file():
        raise IngestError(f"source path does not exist: {source_ref}")
    content = path.read_bytes()
    return _SourceContent(
        ref=str(path),
        name=path.name,
        suffix=path.suffix or ".txt",
        content=content,
        text=_decode_text(content),
        url=None,
    )


def _plan_source_version(
    wiki_root: Path,
    *,
    source: _SourceContent,
    digest: str,
) -> _SourceVersionPlan | IngestResult:
    wiki_db = wiki_root / "wiki.db"
    if not wiki_db.exists():
        return _SourceVersionPlan(version=1, previous_source_id=None, drift_detected=False)
    with db.connect_wiki(wiki_db) as conn:
        if source.url is not None:
            rows = list(
                conn.execute(
                    """
                    SELECT *
                    FROM sources
                    WHERE source_url = ?
                    ORDER BY version, ingested_at, id
                    """,
                    (source.url,),
                )
            )
            if not rows:
                return _SourceVersionPlan(
                    version=1,
                    previous_source_id=None,
                    drift_detected=False,
                )
            latest_rows = [row for row in rows if int(row["is_latest"] or 0) == 1]
            latest = max(latest_rows or rows, key=lambda row: int(row["version"] or 1))
            if latest["sha256"] == digest:
                return _no_change_result(
                    wiki_root,
                    row=latest,
                    digest=digest,
                    source_url=source.url,
                )
            latest_version = max(int(row["version"] or 1) for row in rows)
            superseded = tuple(str(row["id"]) for row in (latest_rows or [latest]))
            return _SourceVersionPlan(
                version=latest_version + 1,
                previous_source_id=str(latest["id"]),
                drift_detected=True,
                superseded_source_ids=superseded,
            )

        row = conn.execute(
            """
            SELECT *
            FROM sources
            WHERE source_url IS NULL AND sha256 = ? AND is_latest = 1
            ORDER BY ingested_at DESC, id DESC
            LIMIT 1
            """,
            (digest,),
        ).fetchone()
        if row is not None:
            return _no_change_result(wiki_root, row=row, digest=digest, source_url=None)
    return _SourceVersionPlan(version=1, previous_source_id=None, drift_detected=False)


def _no_change_result(
    wiki_root: Path,
    *,
    row: Any,
    digest: str,
    source_url: str | None,
) -> IngestResult:
    return IngestResult(
        wiki=wiki_root.name,
        classified_as=str(row["classified_as"] or "unknown"),
        source_id=str(row["id"]),
        sha256=digest,
        pages_created=(),
        pages_updated=(),
        raw_snapshot=str(row["source_path"] or row["id"]),
        source_url=source_url,
        commit_id=None,
        skipped=True,
        message="no change",
    )


def _write_or_merge_page(
    path: Path,
    *,
    page: WikiPage,
    now: str,
    author: str,
    author_kind: str,
    source_id: str,
) -> None:
    created = now
    sources = list(page.sources or (source_id,))
    links = list(page.links)
    kanban_refs: list[dict[str, Any]] = []
    inbound_links = 0
    if path.exists():
        metadata, body = read_markdown(path)
        created = str(metadata.get("created") or now)
        existing_sources = [str(item) for item in _as_list(metadata.get("sources"))]
        existing_links = [str(item) for item in _as_list(metadata.get("links"))]
        for item in _as_list(metadata.get("kanban_refs")):
            if not isinstance(item, Mapping):
                continue
            ref = cast(Mapping[str, Any], item)
            if ref.get("task_id"):
                kanban_refs.append(dict(ref))
        for item in existing_sources:
            if item not in sources:
                sources.append(item)
        for item in existing_links:
            if item not in links:
                links.append(item)
        inbound_links = int(metadata.get("inbound_links") or 0)
        body = _merge_body(body, page.body)
    else:
        body = page.body
    metadata: dict[str, Any] = {
        "id": page.id,
        "title": page.title,
        "type": page.type,
        "created": created,
        "updated": now,
        "tags": list(page.tags),
        "sources": sources,
        "confidence": page.confidence,
        "contested": page.contested,
        "author": author,
        "author_kind": author_kind,
        "links": links,
        "inbound_links": inbound_links,
    }
    if kanban_refs:
        metadata["kanban_refs"] = kanban_refs
    write_markdown(path, metadata, body)


def _cross_link_existing_pages(
    wiki_root: Path,
    *,
    request: ProcessRequest,
    planned_ids: list[str],
    now: str,
    author: str,
    author_kind: str,
    touched: dict[Path, bytes | None],
) -> list[str]:
    updated: list[str] = []
    new_source_id = request.source_page_id
    for existing in request.existing_pages:
        if existing.id in planned_ids or not _mentions_title(request.source_text, existing.title):
            continue
        _remember(touched, existing.path)
        try:
            metadata, body = read_markdown(existing.path)
        except FrontmatterError:
            continue
        inbound = int(metadata.get("inbound_links") or existing.inbound_links or 0) + 1
        links = [str(item) for item in _as_list(metadata.get("links"))]
        if new_source_id not in links:
            links.append(new_source_id)
        metadata["updated"] = now
        metadata["author"] = author
        metadata["author_kind"] = author_kind
        metadata["inbound_links"] = inbound
        metadata["links"] = links
        relative = _relative_link(from_page=existing.id, to_page=new_source_id)
        if relative not in body:
            body = body.rstrip() + f"\n\nReferenced by [{request.title}]({relative})."
        write_markdown(existing.path, metadata, body)
        updated.append(existing.id)
    return updated


def _record_ingest_rows(
    wiki_root: Path,
    *,
    source_id: str,
    source: _SourceContent,
    label: ClassLabel,
    digest: str,
    now: str,
    pages_created: list[str],
    pages_updated: list[str],
    author: str,
    author_kind: str,
    version_plan: _SourceVersionPlan,
) -> None:
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        for superseded_id in version_plan.superseded_source_ids:
            db.mark_source_not_latest(conn, superseded_id)
        db.upsert_source(
            conn,
            id=source_id,
            ingested_at=now,
            sha256=digest,
            source_url=source.url,
            source_path=source_id,
            version=version_plan.version,
            previous_source_id=version_plan.previous_source_id,
            is_latest=1,
            classified_as=label.name,
        )
        db.insert_ingest_log(
            conn,
            ingested_at=now,
            source_type=label.name,
            source_url=source.url,
            source_path=source_id,
            sha256=digest,
            pages_created=pages_created,
            pages_updated=pages_updated,
            drift_detected=1 if version_plan.drift_detected else 0,
            author=author,
            author_kind=author_kind,
        )
        conn.commit()
        db_hash = projection.projection_db_sha256(wiki_root / "wiki.db")
        conn.execute(
            "UPDATE projection_versions SET db_sha256 = ? WHERE status = 'active'",
            (db_hash,),
        )
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _update_registry_after_ingest(wiki_root: Path, *, wiki_slug: str, now: str) -> None:
    home = wiki_root.parent.parent
    with db.connect_registry(home / "wikis" / "wikis.db") as conn:
        db.initialize_registry(conn)
        with db.connect_wiki(wiki_root / "wiki.db") as wiki_conn:
            page_count = wiki_conn.execute("SELECT count(*) FROM pages").fetchone()[0]
            source_count = wiki_conn.execute("SELECT count(*) FROM sources").fetchone()[0]
        conn.execute(
            """
            UPDATE wikis
            SET page_count = ?, source_count = ?, last_ingest = ?, updated = ?
            WHERE slug = ?
            """,
            (page_count, source_count, now, now, wiki_slug),
        )
        conn.commit()


def _rewrite_index(wiki_root: Path) -> None:
    pages: dict[str, list[tuple[str, str]]] = {
        "Sources": [],
        "Concepts": [],
        "Entities": [],
        "Comparisons": [],
        "Queries": [],
        "Summaries": [],
    }
    for path in sorted(projection._iter_page_files(wiki_root)):
        try:
            metadata, _ = read_markdown(path)
        except FrontmatterError:
            continue
        page_id = path.with_suffix("").relative_to(wiki_root).as_posix()
        heading = str(metadata.get("type") or "source").title() + "s"
        pages.setdefault(heading, []).append((str(metadata.get("title") or page_id), page_id))
    lines = ["# Index", ""]
    for heading, entries in pages.items():
        lines.extend([f"## {heading}", ""])
        for title, page_id in sorted(entries, key=lambda item: item[1]):
            lines.append(f"- [{title}]({page_id}.md) — `{page_id}`")
        lines.append("")
    (wiki_root / "index.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _record_page_changes_for_ingest(
    wiki_root: Path,
    *,
    now: str,
    source_ref: str,
    classified_as: str,
    pages_created: list[str],
    pages_updated: list[str],
    author: str,
    author_kind: str,
) -> None:
    for change, page_ids in (
        ("created", pages_created),
        ("updated", list(dict.fromkeys(pages_updated))),
    ):
        for page_id in page_ids:
            record_change(
                wiki_root,
                page_id=page_id,
                action="ingest",
                author=author,
                author_kind=author_kind,
                timestamp=now,
                details={
                    "source": source_ref,
                    "class": classified_as,
                    "change": change,
                    "pages_created": pages_created,
                    "pages_updated": list(dict.fromkeys(pages_updated)),
                },
            )
    if not pages_created and not pages_updated:
        append_log_entry(
            wiki_root,
            timestamp=now,
            action="ingest",
            target=source_ref,
            author=author,
            author_kind=author_kind,
            details={
                "source": source_ref,
                "class": classified_as,
                "pages_created": pages_created,
                "pages_updated": pages_updated,
            },
        )


def _existing_pages(wiki_root: Path) -> Iterable[ExistingPage]:
    for path in projection._iter_page_files(wiki_root):
        try:
            metadata, _body = read_markdown(path)
        except FrontmatterError:
            continue
        yield ExistingPage(
            id=path.with_suffix("").relative_to(wiki_root).as_posix(),
            title=str(metadata.get("title") or path.stem),
            path=path,
            inbound_links=int(metadata.get("inbound_links") or 0),
            links=tuple(str(item) for item in _as_list(metadata.get("links"))),
            sources=tuple(str(item) for item in _as_list(metadata.get("sources"))),
        )


def _source_page_body(request: ProcessRequest, linked_pages: list[ExistingPage]) -> str:
    raw_link = _relative_link(from_page=request.source_page_id, to_page=request.snapshot_relpath)
    lines = [
        f"# {request.title}",
        "",
        "Curated summary of the immutable Source Snapshot.",
        "",
        f"- Classification: `{request.label.name}` ({request.label.confidence})",
        f"- Raw evidence: [Source Snapshot]({raw_link})",
        "",
        _summary_sentence(request.source_text),
    ]
    if linked_pages:
        lines.extend(["", "## Related existing Wiki Pages", ""])
        for page in linked_pages:
            link = _relative_link(from_page=request.source_page_id, to_page=page.id)
            lines.append(f"- [{page.title}]({link})")
    return "\n".join(lines)


def _derived_page_body(title: str, request: ProcessRequest) -> str:
    return "\n".join(
        [
            f"# {title}",
            "",
            (
                f"{title} is a derived Wiki Page from an ingested "
                f"{request.label.name} Source Snapshot."
            ),
            f"It is grounded in [the Source Page](../sources/{request.source_page_filename}).",
            "",
            _summary_sentence(request.source_text),
        ]
    )


def _derived_page_title_and_type(request: ProcessRequest) -> tuple[str, str]:
    title = request.title
    if re.search(r"\b(inc|labs|systems|hermes|google|openai|anthropic)\b", title, re.I):
        return title, "entity"
    return title, "concept"


def _title_from_source(name: str, text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or _titleize(Path(name).stem)
    return _titleize(Path(name).stem)


def _source_slug(name: str, text: str) -> str:
    return _slugify(_title_from_source(name, text) or Path(name).stem)


def _unique_raw_relpath(
    wiki_root: Path,
    *,
    label: str,
    today: str,
    version: int,
    slug: str,
    suffix: str,
) -> str:
    directory = RAW_SUBDIRS.get(label, label if label else "unknown")
    clean_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    base = f"raw/{directory}/{today}-v{version}-{slug}{clean_suffix}"
    return _unique_relpath(wiki_root, base)


def _unique_page_id(wiki_root: Path, base_id: str) -> str:
    candidate = base_id
    index = 2
    while (wiki_root / f"{candidate}.md").exists():
        candidate = f"{base_id}-{index}"
        index += 1
    return candidate


def _unique_relpath(wiki_root: Path, relpath: str) -> str:
    candidate = Path(relpath)
    index = 2
    while (wiki_root / candidate).exists():
        candidate = candidate.with_name(f"{candidate.stem}-{index}{candidate.suffix}")
        index += 1
    return candidate.as_posix()


def _mentions_title(text: str, title: str) -> bool:
    if not title:
        return False
    return re.search(rf"\b{re.escape(title)}\b", text, flags=re.IGNORECASE) is not None


def _relative_link(*, from_page: str, to_page: str) -> str:
    from_path = Path(f"{from_page}.md")
    to_path = Path(to_page)
    if not to_path.suffix:
        to_path = to_path.with_suffix(".md")
    return Path(os.path.relpath(to_path, start=from_path.parent)).as_posix()


def _summary_sentence(text: str) -> str:
    normalized = " ".join(line.strip("# ").strip() for line in text.splitlines() if line.strip())
    if not normalized:
        return "The source did not contain extractable text; retain the Raw Source for review."
    sentence = re.split(r"(?<=[.!?])\s+", normalized)[0]
    return sentence[:280]


def _decode_text(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "source"


def _titleize(value: str) -> str:
    return re.sub(r"[-_]+", " ", value).strip().title() or "Untitled Source"


def _merge_body(existing: str, new: str) -> str:
    if new in existing:
        return existing
    return existing.rstrip() + "\n\n## Additional Source Context\n\n" + new.strip()


def _as_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@contextmanager
def _ingest_lock(wiki_root: Path) -> Iterator[None]:
    """Serialize ingest runs that mutate the same Wiki Repository."""

    lock_path = wiki_root / ".ingest.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _remember(touched: dict[Path, bytes | None], path: Path) -> None:
    if path in touched:
        return
    touched[path] = path.read_bytes() if path.exists() and path.is_file() else None


def _restore(touched: dict[Path, bytes | None]) -> None:
    for path, content in reversed(touched.items()):
        if content is None:
            if path.exists():
                path.unlink()
            _remove_empty_parents(path.parent)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)


def _remove_empty_parents(path: Path) -> None:
    while path.name and path.exists():
        try:
            path.rmdir()
        except OSError:
            return
        if path.name in {"sources", "concepts", "entities", "articles", "papers", "transcripts"}:
            return
        path = path.parent


__all__ = [
    "DefaultProcessor",
    "GeneratedPage",
    "InboxFileNotTextError",
    "InboxFileTooLargeError",
    "IngestError",
    "IngestResult",
    "ProcessRequest",
    "ProcessorError",
    "classify_source",
    "delete_inbox_file",
    "ingest_inbox",
    "ingest_source",
    "list_inbox",
    "read_inbox_file",
    "search_wiki",
    "write_inbox_file",
]
