"""Hermes home and current Wiki resolution.

Resolution is deliberately filesystem-backed and adapter-seam driven:

1. explicit ``wiki=`` parameter
2. ``HERMES_WIKI`` environment variable
3. profile-local current pointer at ``<home>/wikis/<profile>.current``
4. global default pointer at ``<home>/wikis/default``

Once a non-empty tier selects a slug, that slug must be valid and backed by an
existing wiki directory. Invalid explicit/env/current/default pointers fail
closed instead of silently falling through to a later tier.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from adapters.base import HomeResolver, create_adapters

_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class WikiResolutionError(RuntimeError):
    """Raised when the current Wiki cannot be resolved cleanly."""


@dataclass(frozen=True, slots=True)
class ResolvedWiki:
    """Resolved Wiki metadata used by CLI, tools, and dashboard surfaces."""

    slug: str
    path: Path
    home: Path
    source: str


def resolve_home(home_resolver: HomeResolver | None = None) -> Path:
    """Resolve the active Hermes home through the Home seam."""

    resolver = home_resolver if home_resolver is not None else create_adapters().home
    try:
        home = resolver.home()
    except Exception as exc:
        raise WikiResolutionError(f"Could not resolve Hermes home: {exc}") from exc
    return Path(home).expanduser()


def resolve_wiki(
    *,
    wiki: str | None = None,
    profile: str | None = None,
    home_resolver: HomeResolver | None = None,
    env: Mapping[str, str] | None = None,
) -> ResolvedWiki:
    """Resolve the current Wiki using the canonical cascade.

    ``wiki`` models a surface-level ``wiki=``/``--wiki`` parameter. ``env`` is
    injectable for tests; by default the real process environment is used.
    """

    home = resolve_home(home_resolver)
    wikis_dir = home / "wikis"
    source_env = env if env is not None else os.environ

    explicit_slug = _optional_slug(wiki)
    if explicit_slug is not None:
        return _resolve_slug(
            explicit_slug,
            source="param",
            source_label="wiki parameter",
            home=home,
            wikis_dir=wikis_dir,
        )

    env_slug = _optional_slug(source_env.get("HERMES_WIKI"))
    if env_slug is not None:
        return _resolve_slug(
            env_slug,
            source="env",
            source_label="HERMES_WIKI",
            home=home,
            wikis_dir=wikis_dir,
        )

    if (profile_name := _optional_profile(profile)) is not None:
        current_slug = _read_pointer_file(
            wikis_dir / f"{profile_name}.current",
            source_label=f"profile current for {profile_name!r}",
        )
        if current_slug is not None:
            return _resolve_slug(
                current_slug,
                source="profile-current",
                source_label=f"profile current for {profile_name!r}",
                home=home,
                wikis_dir=wikis_dir,
            )

    default_slug = _read_pointer_file(wikis_dir / "default", source_label="default wiki")
    if default_slug is not None:
        return _resolve_slug(
            default_slug,
            source="default",
            source_label="default wiki",
            home=home,
            wikis_dir=wikis_dir,
        )

    raise WikiResolutionError(
        "No wiki could be resolved: provide wiki=, set HERMES_WIKI, "
        f"write a profile current file under {wikis_dir}, or configure {wikis_dir / 'default'}."
    )


def _optional_slug(value: str | None) -> str | None:
    if value is None:
        return None
    slug = value.strip()
    return slug or None


def _optional_profile(value: str | None) -> str | None:
    if value is None:
        return None
    profile = value.strip()
    if not profile:
        return None
    if not _PROFILE_RE.fullmatch(profile) or profile in {".", ".."}:
        raise WikiResolutionError(f"invalid profile name {value!r}")
    return profile


def _read_pointer_file(path: Path, *, source_label: str) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        message = f"Could not read {source_label} pointer at {path}: {exc}"
        raise WikiResolutionError(message) from exc
    return value or None


def _resolve_slug(
    slug: str,
    *,
    source: str,
    source_label: str,
    home: Path,
    wikis_dir: Path,
) -> ResolvedWiki:
    _validate_slug(slug)
    wiki_path = wikis_dir / slug
    if not wiki_path.is_dir():
        raise WikiResolutionError(
            f"{source_label} selected wiki {slug!r}, but {wiki_path} is missing."
        )
    return ResolvedWiki(slug=slug, path=wiki_path, home=home, source=source)


def _validate_slug(slug: str) -> None:
    if not _SLUG_RE.fullmatch(slug) or slug in {".", ".."}:
        raise WikiResolutionError(f"invalid wiki slug {slug!r}")


__all__ = ["ResolvedWiki", "WikiResolutionError", "resolve_home", "resolve_wiki"]
