"""Core operations for managing LLM Wiki instances."""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from adapters.base import HomeResolver, create_adapters
from hermes_wiki import db, git_ops, projection, templates
from hermes_wiki._validators import ValidationError, validate_profile, validate_slug
from hermes_wiki.home import ResolvedWiki, WikiResolutionError, resolve_home, resolve_wiki

NOT_FOUND_OR_NOT_VISIBLE = "not found or not visible"


class WikiManagementError(RuntimeError):
    """Raised for clean, user-facing wiki management failures."""


@dataclass(frozen=True, slots=True)
class WikiCreateResult:
    """Result of creating a wiki."""

    slug: str
    path: Path
    registry_row: Mapping[str, Any]
    projection_version_id: str
    commit_id: str | None


@dataclass(frozen=True, slots=True)
class WikiArchiveResult:
    """Result of archiving or unarchiving a wiki."""

    slug: str
    path: Path
    archived: bool
    commit_id: str | None


def create_wiki(
    slug: str,
    *,
    domain: str | None = None,
    author: str | None = None,
    author_kind: str = "human",
    home_resolver: HomeResolver | None = None,
) -> WikiCreateResult:
    """Create a new wiki root, registry row, initial projection, and git commit."""

    clean_slug = _validate_slug_for_management(slug)
    acting_author = resolved_author(author)
    home = resolve_home(home_resolver)
    wikis_dir = home / "wikis"
    wiki_root = wikis_dir / clean_slug
    registry_path = wikis_dir / "wikis.db"

    with _registry_connection(home, create=True) as conn:
        if db.get_wiki(conn, clean_slug) is not None or wiki_root.exists():
            raise WikiManagementError(f"wiki {clean_slug!r} already exists")

        git_ops.initialize_wiki_repo(home, clean_slug)
        templates.write_wiki_starter_files(
            wiki_root,
            slug=clean_slug,
            domain=domain,
            author=acting_author,
            author_kind=author_kind,
        )
        projection_result = projection.rebuild_projection(
            wiki_root,
            rebuild_reason="initial",
            author=acting_author,
            author_kind=author_kind,
        )
        if projection_result.status != "active":
            raise WikiManagementError(
                f"failed to initialize projection for {clean_slug}: {projection_result.notes}"
            )
        registry_row = db.upsert_wiki(
            conn,
            slug=clean_slug,
            path=wiki_root,
            domain=domain,
            page_count=0,
            source_count=0,
            health_score=1.0,
            archived=0,
        )
        conn.commit()

    commit = git_ops.commit_change(
        wiki_root,
        action="create",
        what=clean_slug,
        author=acting_author,
    )
    # Re-open to verify the row still exists after git work; this also makes it
    # explicit that the registry DB is independent from the per-wiki repo.
    if not registry_path.exists():  # pragma: no cover - defensive sanity check
        raise WikiManagementError("registry database was not created")
    return WikiCreateResult(
        slug=clean_slug,
        path=wiki_root,
        registry_row=registry_row,
        projection_version_id=projection_result.version_id,
        commit_id=commit.commit_id,
    )


def list_visible_wikis(
    *,
    include_archived: bool = False,
    profile: str | None = None,
    home_resolver: HomeResolver | None = None,
) -> list[dict[str, Any]]:
    """List registry wikis visible to a profile, hiding archived by default."""

    current_profile(profile)
    home = resolve_home(home_resolver)
    registry_path = home / "wikis" / "wikis.db"
    if not registry_path.exists():
        return []
    with _registry_connection(home, create=False) as conn:
        rows = [dict(row) for row in db.list_wikis(conn, include_archived=include_archived)]
    cfg = _wiki_config()
    return [row for row in rows if _is_visible(row, cfg=cfg, include_archived=include_archived)]


def show_wiki(
    *,
    slug: str | None = None,
    profile: str | None = None,
    home_resolver: HomeResolver | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve and return a visible wiki's registry summary."""

    resolved = _resolve_for_read(slug=slug, profile=profile, home_resolver=home_resolver, env=env)
    row = _visible_registry_row(resolved.slug, home=resolved.home, include_archived=False)
    if row is None:
        raise WikiManagementError(NOT_FOUND_OR_NOT_VISIBLE)
    from hermes_wiki.lint import ensure_projection_current

    ensure_projection_current(Path(str(row["path"])))
    return row


def switch_wiki(
    slug: str,
    *,
    profile: str | None = None,
    home_resolver: HomeResolver | None = None,
) -> Path:
    """Set the profile-local current wiki marker."""

    clean_slug = _validate_slug_for_management(slug)
    home = resolve_home(home_resolver)
    row = _visible_registry_row(clean_slug, home=home, include_archived=False)
    if row is None:
        raise WikiManagementError(NOT_FOUND_OR_NOT_VISIBLE)
    profile_name = current_profile(profile)
    marker = home / "wikis" / f"{profile_name}.current"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(clean_slug + "\n", encoding="utf-8")
    return marker


def archive_wiki(
    slug: str,
    *,
    undo: bool = False,
    author: str | None = None,
    home_resolver: HomeResolver | None = None,
) -> WikiArchiveResult:
    """Archive or unarchive a wiki without deleting files."""

    clean_slug = _validate_slug_for_management(slug)
    acting_author = resolved_author(author)
    home = resolve_home(home_resolver)
    if not (home / "wikis" / "wikis.db").exists():
        raise WikiManagementError(NOT_FOUND_OR_NOT_VISIBLE)
    with _registry_connection(home, create=False) as conn:
        row = db.get_wiki(conn, clean_slug)
        if row is None:
            raise WikiManagementError(NOT_FOUND_OR_NOT_VISIBLE)
        wiki_root = Path(str(row["path"]))
        if not wiki_root.is_dir():
            raise WikiManagementError(NOT_FOUND_OR_NOT_VISIBLE)
        if undo:
            db.unarchive_wiki(conn, slug=clean_slug)
            action = "unarchive"
            archived = False
        else:
            db.archive_wiki(conn, slug=clean_slug)
            action = "archive"
            archived = True
        conn.commit()

    _append_management_log(wiki_root, action=action, target=clean_slug, author=acting_author)
    commit = git_ops.commit_change(
        wiki_root,
        action=action,
        what=clean_slug,
        author=acting_author,
    )
    return WikiArchiveResult(
        slug=clean_slug,
        path=wiki_root,
        archived=archived,
        commit_id=commit.commit_id,
    )


def ensure_wiki_mutable(
    slug: str | None = None,
    *,
    profile: str | None = None,
    home_resolver: HomeResolver | None = None,
    env: Mapping[str, str] | None = None,
) -> ResolvedWiki:
    """Resolve a wiki for mutation and deny archived/non-visible wikis."""

    resolved = _resolve_for_read(slug=slug, profile=profile, home_resolver=home_resolver, env=env)
    row = _visible_registry_row(resolved.slug, home=resolved.home, include_archived=False)
    if row is None:
        raise WikiManagementError(NOT_FOUND_OR_NOT_VISIBLE)
    return resolved


def current_profile(profile: str | None = None) -> str:
    """Return the active profile name for profile-local current markers."""

    candidate = (
        profile
        or os.environ.get("HERMES_PROFILE_NAME")
        or os.environ.get("HERMES_PROFILE")
        or "default"
    )
    try:
        return validate_profile(candidate)
    except ValidationError as exc:
        raise WikiManagementError(str(exc)) from exc


def resolved_author(author: str | None = None) -> str:
    """Return the acting author for human CLI mutations."""

    if author is not None and author.strip():
        return _one_line(author, "author")
    return _one_line(os.environ.get("USER") or "unknown", "author")


def _registry_connection(home: Path, *, create: bool) -> sqlite3.Connection:
    registry_path = home / "wikis" / "wikis.db"
    if not create and not registry_path.exists():
        raise WikiManagementError("no wikis registry exists")
    conn = db.connect_registry(registry_path)
    db.initialize_registry(conn)
    return conn


def _resolve_for_read(
    *,
    slug: str | None,
    profile: str | None,
    home_resolver: HomeResolver | None,
    env: Mapping[str, str] | None,
) -> ResolvedWiki:
    try:
        return resolve_wiki(
            wiki=slug,
            profile=current_profile(profile),
            home_resolver=home_resolver,
            env=env,
        )
    except WikiResolutionError as exc:
        if slug is not None or ((env if env is not None else os.environ).get("HERMES_WIKI")):
            raise WikiManagementError(NOT_FOUND_OR_NOT_VISIBLE) from exc
        raise WikiManagementError(str(exc)) from exc


def _visible_registry_row(
    slug: str,
    *,
    home: Path,
    include_archived: bool,
) -> dict[str, Any] | None:
    registry_path = home / "wikis" / "wikis.db"
    if not registry_path.exists():
        return None
    with _registry_connection(home, create=False) as conn:
        row = db.get_wiki(conn, slug)
    if row is None:
        return None
    row_dict = dict(row)
    return (
        row_dict
        if _is_visible(row_dict, cfg=_wiki_config(), include_archived=include_archived)
        else None
    )


def _wiki_config() -> Mapping[str, Any]:
    try:
        loaded = create_adapters().config.load()
    except Exception:
        return {}
    wiki_cfg = loaded.get("wiki") if isinstance(loaded, dict) else None
    return wiki_cfg if isinstance(wiki_cfg, Mapping) else {}


def _is_visible(
    row: Mapping[str, Any],
    *,
    cfg: Mapping[str, Any],
    include_archived: bool,
) -> bool:
    slug = str(row.get("slug") or "")
    if not include_archived and int(row.get("archived") or 0):
        return False
    whitelist = _string_set(cfg.get("whitelist"))
    blacklist = _string_set(cfg.get("blacklist"))
    if whitelist:
        return slug in whitelist
    if slug in blacklist:
        return False
    if _schema_private(Path(str(row.get("path") or ""))):
        return False
    default_access = str(cfg.get("default_access") or "discoverable").strip().lower()
    return default_access in {"", "discoverable", "visible", "public"}


def _schema_private(wiki_root: Path) -> bool:
    try:
        text = (wiki_root / "SCHEMA.md").read_text(encoding="utf-8")
    except OSError:
        return False
    return bool(re.search(r"(?m)^\s*private:\s*true\s*$", text, flags=re.IGNORECASE))


def _string_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    if isinstance(value, (list, tuple, set)):
        return {str(item) for item in value}
    return set()


def _append_management_log(
    wiki_root: Path,
    *,
    action: str,
    target: str,
    author: str,
) -> None:
    log_path = wiki_root / "log.md"
    timestamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    row = (
        f"| {timestamp} | {action} | {target} | {author} | human | "
        f"Wiki management action `{action}`. |\n"
    )
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(row)


def _validate_slug_for_management(slug: str) -> str:
    try:
        return validate_slug(slug)
    except ValidationError as exc:
        raise WikiManagementError(str(exc)) from exc


def _one_line(value: str, field: str) -> str:
    clean = value.strip()
    if not clean:
        raise WikiManagementError(f"{field} is required")
    if "\n" in clean or "\r" in clean:
        raise WikiManagementError(f"{field} must be a single line")
    return clean


__all__ = [
    "NOT_FOUND_OR_NOT_VISIBLE",
    "WikiArchiveResult",
    "WikiCreateResult",
    "WikiManagementError",
    "archive_wiki",
    "create_wiki",
    "current_profile",
    "ensure_wiki_mutable",
    "list_visible_wikis",
    "resolved_author",
    "show_wiki",
    "switch_wiki",
]
