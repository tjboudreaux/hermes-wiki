"""Visible-Wiki filtering helpers for agent and prompt surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from adapters.base import HomeResolver
from hermes_wiki.management import (
    NOT_FOUND_OR_NOT_VISIBLE,
    WikiManagementError,
    ensure_wiki_mutable,
    list_visible_wikis,
)


class WikiVisibilityError(WikiManagementError):
    """Raised when a wiki is not visible to the active profile."""


def visible_wikis(
    *,
    include_archived: bool = False,
    profile: str | None = None,
    home_resolver: HomeResolver | None = None,
) -> list[dict[str, Any]]:
    """Return registry rows visible to the active profile.

    This wraps the existing management gate so read surfaces use one
    non-disclosing implementation for archived/private/blacklisted Wikis.
    """

    return list_visible_wikis(
        include_archived=include_archived,
        profile=profile,
        home_resolver=home_resolver,
    )


def require_visible_wiki(
    wiki: str | None = None,
    *,
    profile: str | None = None,
    home_resolver: HomeResolver | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[str, Path]:
    """Resolve ``wiki`` and return ``(slug, path)`` if it is visible."""

    try:
        resolved = ensure_wiki_mutable(
            slug=wiki,
            profile=profile,
            home_resolver=home_resolver,
            env=env,
        )
    except WikiManagementError as exc:
        raise WikiVisibilityError(NOT_FOUND_OR_NOT_VISIBLE) from exc
    return resolved.slug, resolved.path


def is_wiki_visible(
    wiki: str,
    *,
    profile: str | None = None,
    home_resolver: HomeResolver | None = None,
) -> bool:
    """Return whether ``wiki`` is visible without disclosing why it is hidden."""

    try:
        require_visible_wiki(wiki, profile=profile, home_resolver=home_resolver)
    except WikiVisibilityError:
        return False
    return True


__all__ = [
    "NOT_FOUND_OR_NOT_VISIBLE",
    "WikiVisibilityError",
    "is_wiki_visible",
    "require_visible_wiki",
    "visible_wikis",
]
