"""Visible-Wiki filtering and write-grant helpers for agent/prompt surfaces."""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from adapters.base import ConfigLoader, HomeResolver, create_adapters
from hermes_wiki import db
from hermes_wiki.home import WikiResolutionError, resolve_home, resolve_wiki
from hermes_wiki.management import (
    NOT_FOUND_OR_NOT_VISIBLE,
    WikiManagementError,
    current_profile,
)


class WikiVisibilityError(WikiManagementError):
    """Raised when a wiki is not visible to the active profile."""


def visible_wikis(
    *,
    include_archived: bool = False,
    profile: str | None = None,
    home_resolver: HomeResolver | None = None,
    config: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return registry rows visible to the active profile.

    The returned set is governed by the profile's ``wiki:`` config:
    whitelist (when non-empty) defines the visible set, blacklist subtracts
    when no whitelist is present, private wikis require explicit whitelist,
    and archived wikis are hidden unless ``include_archived`` is true.
    """

    return resolve_visible_wikis(
        include_archived=include_archived,
        profile=profile,
        home_resolver=home_resolver,
        config=config,
    )


def resolve_visible_wikis(
    *,
    include_archived: bool = False,
    profile: str | None = None,
    home_resolver: HomeResolver | None = None,
    config: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Resolve the exact visible Wiki registry rows for ``profile``."""

    # Validate the supplied profile name even though visibility config is
    # currently profile-loaded by the active adapter.
    current_profile(profile)
    home = resolve_home(home_resolver)
    registry_path = home / "wikis" / "wikis.db"
    if not registry_path.exists():
        return []

    try:
        with db.connect_registry(registry_path) as conn:
            db.initialize_registry(conn)
            rows = [dict(row) for row in db.list_wikis(conn, include_archived=True)]
    except sqlite3.DatabaseError:
        return []

    wiki_cfg = _wiki_config(config)
    return [
        row
        for row in rows
        if _is_visible_row(row, cfg=wiki_cfg, include_archived=include_archived)
    ]


def require_visible_wiki(
    wiki: str | None = None,
    *,
    profile: str | None = None,
    home_resolver: HomeResolver | None = None,
    env: Mapping[str, str] | None = None,
    config: Mapping[str, Any] | None = None,
) -> tuple[str, Path]:
    """Resolve ``wiki`` and return ``(slug, path)`` if it is visible."""

    try:
        resolved = resolve_wiki(
            wiki=wiki,
            profile=current_profile(profile),
            home_resolver=home_resolver,
            env=env,
        )
    except (WikiManagementError, WikiResolutionError) as exc:
        raise WikiVisibilityError(NOT_FOUND_OR_NOT_VISIBLE) from exc
    row = _registry_row(resolved.slug, home=resolved.home)
    if row is None or not _is_visible_row(row, cfg=_wiki_config(config), include_archived=False):
        raise WikiVisibilityError(NOT_FOUND_OR_NOT_VISIBLE)
    return resolved.slug, resolved.path


def is_wiki_visible(
    wiki: str,
    *,
    profile: str | None = None,
    home_resolver: HomeResolver | None = None,
    config: Mapping[str, Any] | None = None,
) -> bool:
    """Return whether ``wiki`` is visible without disclosing why it is hidden."""

    try:
        require_visible_wiki(
            wiki,
            profile=profile,
            home_resolver=home_resolver,
            config=config,
        )
    except WikiVisibilityError:
        return False
    return True


def has_write_grant(
    wiki: str | None,
    *,
    config: Mapping[str, Any] | None = None,
    config_loader: ConfigLoader | None = None,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return whether current session config grants mutation for ``wiki``.

    This deliberately checks only the Write Grant. Callers must perform
    visibility resolution first so write grants cannot reveal invisible wikis.
    """

    source_env = env if env is not None else os.environ
    env_wiki = str(source_env.get("HERMES_WIKI") or "").strip()
    if env_wiki and (wiki is None or env_wiki == wiki):
        return True

    full_config = _load_config(config=config, config_loader=config_loader)
    wiki_cfg = _wiki_config(full_config)
    grants = _string_set(wiki_cfg.get("write_grants"))
    toolsets = _string_set(full_config.get("toolsets"))
    enabled_toolsets = _string_set(full_config.get("enabled_toolsets"))
    return (
        "wiki" in toolsets
        or "wiki" in enabled_toolsets
        or "*" in grants
        or (wiki is None and bool(grants))
        or (wiki is not None and wiki in grants)
    )


def _registry_row(slug: str, *, home: Path) -> dict[str, Any] | None:
    registry_path = home / "wikis" / "wikis.db"
    if not registry_path.exists():
        return None
    try:
        with db.connect_registry(registry_path) as conn:
            db.initialize_registry(conn)
            row = db.get_wiki(conn, slug)
    except sqlite3.DatabaseError:
        return None
    return dict(row) if row is not None else None


def _is_visible_row(
    row: Mapping[str, Any],
    *,
    cfg: Mapping[str, Any],
    include_archived: bool,
) -> bool:
    slug = str(row.get("slug") or "")
    if not slug:
        return False
    if int(row.get("archived") or 0) and not include_archived:
        return False

    whitelist = _string_set(cfg.get("whitelist"))
    if whitelist:
        return slug in whitelist

    if slug in _string_set(cfg.get("blacklist")):
        return False
    if _schema_private(Path(str(row.get("path") or ""))):
        return False

    default_access = str(cfg.get("default_access") or "discoverable").strip().lower()
    return default_access in {"", "all", "discoverable", "public", "visible"}


def _schema_private(wiki_root: Path) -> bool:
    try:
        text = (wiki_root / "SCHEMA.md").read_text(encoding="utf-8")
    except OSError:
        return False
    return bool(re.search(r"(?m)^\s*private:\s*true\s*$", text, flags=re.IGNORECASE))


def _load_config(
    *,
    config: Mapping[str, Any] | None = None,
    config_loader: ConfigLoader | None = None,
) -> Mapping[str, Any]:
    if config is not None:
        return config
    try:
        loaded = (config_loader or create_adapters().config).load()
    except Exception:
        return {}
    return loaded if isinstance(loaded, Mapping) else {}


def _wiki_config(config: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
    full_config = _load_config(config=config)
    wiki_cfg = full_config.get("wiki")
    if isinstance(wiki_cfg, Mapping):
        return wiki_cfg
    # Allow callers/tests to pass the wiki subsection directly.
    wiki_config_keys = ("default_access", "whitelist", "blacklist", "write_grants")
    if any(key in full_config for key in wiki_config_keys):
        return full_config
    return {}


def _string_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    if isinstance(value, Sequence):
        return {str(item) for item in value}
    return set()


__all__ = [
    "NOT_FOUND_OR_NOT_VISIBLE",
    "WikiVisibilityError",
    "has_write_grant",
    "is_wiki_visible",
    "require_visible_wiki",
    "resolve_visible_wikis",
    "visible_wikis",
]
