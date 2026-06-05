"""Attribution helpers for durable Wiki writes and page history views."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from adapters.base import create_adapters
from hermes_wiki import db
from hermes_wiki.frontmatter import FrontmatterError, read_markdown, write_markdown

ALLOWED_AUTHOR_KINDS = frozenset({"agent", "profile", "human", "cron"})

_HISTORY_BLOCK_RE = re.compile(
    r"(?im)^\s{0,3}#{1,6}\s+(?:page|author|change)\s+history\b"
    r"|<!--\s*(?:page|author|change)[-_ ]?history\b",
)


@dataclass(frozen=True, slots=True)
class LogEntry:
    """One parsed row from a Wiki's append-only ``log.md``."""

    timestamp: str
    action: str
    target: str
    author: str
    author_kind: str
    details: str
    index: int

    def to_row(self) -> dict[str, Any]:
        """Return a JSON-serializable row for CLI/API consumers."""

        return {
            "timestamp": self.timestamp,
            "action": self.action,
            "target": self.target,
            "author": self.author,
            "author_kind": self.author_kind,
            "details": self.details,
            "index": self.index,
        }


def resolve_actor(
    *,
    author: str | None = None,
    author_kind: str | None = None,
    env: Mapping[str, str] | None = None,
    config: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    """Resolve and normalize an actor to ``(author, author_kind)``.

    Mapping follows SPEC §5.1:
    - agents use the model name
    - cron jobs persist as ``cron:<job>``
    - profile workers persist as ``profile:<slug>``
    - humans prefer configured email/author over ``$USER``
    """

    source_env = env if env is not None else os.environ
    kind = _validate_author_kind(author_kind or _infer_author_kind(source_env))
    if kind == "agent":
        return (_one_line(author or _agent_model(source_env), "author"), "agent")
    if kind == "cron":
        value = author or _first_env(source_env, "HERMES_CRON_JOB", "HERMES_CRON_JOB_NAME")
        value = value or _first_env(source_env, "HERMES_CRON_NAME") or "unknown"
        clean = _one_line(value, "author")
        return (clean if clean.startswith("cron:") else f"cron:{clean}", "cron")
    if kind == "profile":
        value = author or _first_env(source_env, "HERMES_PROFILE_NAME", "HERMES_PROFILE")
        clean = _one_line(value or "default", "author")
        return (clean if clean.startswith("profile:") else f"profile:{clean}", "profile")
    if author is not None and author.strip():
        return (_one_line(author, "author"), "human")
    configured = _configured_human_author(config)
    if configured:
        return (_one_line(configured, "author"), "human")
    return (_one_line(source_env.get("USER") or "unknown", "author"), "human")


def record_change(
    wiki_root: Path | str,
    *,
    page_id: str | None,
    action: str,
    author: str | None = None,
    author_kind: str | None = None,
    timestamp: str | None = None,
    target: str | None = None,
    details: Mapping[str, Any] | str | None = None,
) -> LogEntry:
    """Record an attributed durable change in frontmatter, projection, and ``log.md``.

    ``page_id`` is optional because some durable changes target Wiki-level files
    such as ``SCHEMA.md``. When a page is named and present on disk, the page's
    current frontmatter author is replaced (not accumulated) and the projected
    ``pages`` row is updated if it already exists.
    """

    root = Path(wiki_root)
    at = timestamp or utc_now()
    resolved_author, resolved_kind = resolve_actor(author=author, author_kind=author_kind)
    clean_action = _one_line(action, "action")
    clean_target = _one_line(target or page_id or "", "target")
    encoded_details = _encode_details(details)

    if page_id:
        _update_page_attribution(
            root,
            page_id=page_id,
            author=resolved_author,
            author_kind=resolved_kind,
            updated=at,
        )
    return append_log_entry(
        root,
        timestamp=at,
        action=clean_action,
        target=clean_target,
        author=resolved_author,
        author_kind=resolved_kind,
        details=encoded_details,
    )


def append_log_entry(
    wiki_root: Path | str,
    *,
    timestamp: str,
    action: str,
    target: str,
    author: str,
    author_kind: str,
    details: Mapping[str, Any] | str | None = None,
) -> LogEntry:
    """Append one normalized action row to ``log.md``."""

    root = Path(wiki_root)
    clean_kind = _validate_author_kind(author_kind)
    clean_timestamp = _one_line(timestamp, "timestamp")
    clean_action = _one_line(action, "action")
    clean_target = _one_line(target, "target")
    clean_author = _one_line(author, "author")
    encoded_details = _encode_details(details)
    log_path = root / "log.md"
    existing_count = len(_parse_log_entries(root))
    row = (
        f"| {_table_cell(clean_timestamp)} | {_table_cell(clean_action)} | "
        f"{_table_cell(clean_target)} | {_table_cell(clean_author)} | "
        f"{_table_cell(clean_kind)} | {_table_cell(encoded_details)} |\n"
    )
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(row)
    return LogEntry(
        timestamp=clean_timestamp,
        action=clean_action,
        target=clean_target,
        author=clean_author,
        author_kind=clean_kind,
        details=encoded_details,
        index=existing_count,
    )


def list_log_entries(
    wiki_root: Path | str,
    *,
    author: str | None = None,
    author_kind: str | None = None,
    page_id: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[LogEntry]:
    """Return deterministic chronological log rows with AND filters."""

    kind = None if author_kind is None else _validate_author_kind(author_kind)
    entries = _parse_log_entries(Path(wiki_root))
    if author is not None:
        entries = [entry for entry in entries if entry.author == author]
    if kind is not None:
        entries = [entry for entry in entries if entry.author_kind == kind]
    if page_id is not None:
        entries = [entry for entry in entries if _entry_matches_page(entry, page_id)]
    entries.sort(key=lambda entry: (entry.timestamp, entry.index, entry.action, entry.target))
    start = max(0, offset)
    stop = None if limit is None else start + max(0, limit)
    return entries[start:stop]


def history_block_in_body(body: str) -> bool:
    """Return true when a page embeds forbidden Page History content."""

    return _HISTORY_BLOCK_RE.search(body) is not None


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp used in attribution records."""

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _update_page_attribution(
    wiki_root: Path,
    *,
    page_id: str,
    author: str,
    author_kind: str,
    updated: str,
) -> None:
    page_path = wiki_root / f"{page_id}.md"
    if page_path.is_file():
        try:
            metadata, body = read_markdown(page_path)
        except FrontmatterError:
            metadata = {}
            body = ""
        if metadata:
            metadata["author"] = author
            metadata["author_kind"] = author_kind
            metadata["updated"] = updated
            write_markdown(page_path, metadata, body)

    wiki_db = wiki_root / "wiki.db"
    if not wiki_db.exists():
        return
    try:
        with db.connect_wiki(wiki_db) as conn:
            conn.execute(
                """
                UPDATE pages
                SET author = ?, author_kind = ?, updated = ?
                WHERE id = ?
                """,
                (author, author_kind, updated, page_id),
            )
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        return


def _parse_log_entries(wiki_root: Path) -> list[LogEntry]:
    log_path = wiki_root / "log.md"
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    entries: list[LogEntry] = []
    for line in lines:
        parsed = _parse_log_line(line, index=len(entries))
        if parsed is not None:
            entries.append(parsed)
    return entries


def _parse_log_line(line: str, *, index: int) -> LogEntry | None:
    stripped = line.strip()
    if not stripped.startswith("|") or "---" in stripped:
        return None
    cells = [cell.strip().replace(r"\|", "|") for cell in stripped.strip("|").split("|", 5)]
    if len(cells) != 6:
        return None
    timestamp, action, target, author, author_kind, details = cells
    if timestamp.lower() in {"time", "timestamp"} or action.lower() == "action":
        return None
    if author_kind not in ALLOWED_AUTHOR_KINDS:
        return None
    return LogEntry(
        timestamp=timestamp,
        action=action,
        target=target,
        author=author,
        author_kind=author_kind,
        details=details,
        index=index,
    )


def _entry_matches_page(entry: LogEntry, page_id: str) -> bool:
    if entry.target == page_id:
        return True
    try:
        details = json.loads(entry.details)
    except json.JSONDecodeError:
        return False
    if not isinstance(details, dict):
        return False
    if details.get("page_id") == page_id:
        return True
    for key in ("pages_created", "pages_updated"):
        value = details.get(key)
        if isinstance(value, list) and page_id in {str(item) for item in value}:
            return True
    return False


def _configured_human_author(config: Mapping[str, Any] | None) -> str | None:
    cfg = config
    if cfg is None:
        try:
            cfg = create_adapters().config.load()
        except Exception:
            cfg = {}
    candidates: list[Any] = [
        cfg.get("author_email"),
        cfg.get("email"),
        cfg.get("author"),
    ]
    wiki_cfg = cfg.get("wiki")
    if isinstance(wiki_cfg, Mapping):
        candidates.extend([wiki_cfg.get("author_email"), wiki_cfg.get("email")])
        candidates.append(wiki_cfg.get("author"))
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            nested = candidate.get("email") or candidate.get("author") or candidate.get("name")
            if isinstance(nested, str) and nested.strip():
                return nested
            continue
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return None


def _infer_author_kind(env: Mapping[str, str]) -> str:
    if _first_env(env, "HERMES_CRON_JOB", "HERMES_CRON_JOB_NAME", "HERMES_CRON_NAME"):
        return "cron"
    if env.get("HERMES_PROFILE_WORKER"):
        return "profile"
    if _first_env(env, "HERMES_MODEL", "HERMES_AGENT_MODEL"):
        return "agent"
    return "human"


def _agent_model(env: Mapping[str, str]) -> str:
    return _first_env(env, "HERMES_MODEL", "HERMES_AGENT_MODEL") or "agent"


def _first_env(env: Mapping[str, str], *names: str) -> str | None:
    for name in names:
        value = env.get(name)
        if value is not None and value.strip():
            return value
    return None


def _validate_author_kind(author_kind: str) -> str:
    clean = _one_line(author_kind, "author_kind")
    if clean not in ALLOWED_AUTHOR_KINDS:
        allowed = ", ".join(sorted(ALLOWED_AUTHOR_KINDS))
        raise ValueError(f"author_kind must be one of: {allowed}")
    return clean


def _encode_details(details: Mapping[str, Any] | str | None) -> str:
    if details is None:
        return ""
    if isinstance(details, str):
        return _one_line(details, "details")
    return json.dumps(details, separators=(",", ":"), sort_keys=True)


def _table_cell(value: str) -> str:
    clean = str(value).strip()
    if "\n" in clean or "\r" in clean:
        raise ValueError("log cell must be a single line")
    return clean.replace("|", r"\|")


def _one_line(value: str, field: str) -> str:
    clean = str(value).strip()
    if not clean:
        raise ValueError(f"{field} is required")
    if "\n" in clean or "\r" in clean:
        raise ValueError(f"{field} must be a single line")
    return clean


__all__ = [
    "ALLOWED_AUTHOR_KINDS",
    "LogEntry",
    "append_log_entry",
    "history_block_in_body",
    "list_log_entries",
    "record_change",
    "resolve_actor",
    "utc_now",
]
