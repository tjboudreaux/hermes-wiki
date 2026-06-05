"""System-prompt helpers for Hermes Wiki discovery."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from adapters.base import HomeResolver
from hermes_wiki.visibility import resolve_visible_wikis

GUIDANCE_LINE = (
    "Use wiki_search(query, wiki=<slug>) to consult these knowledge bases when a "
    "question is domain-relevant."
)
EMPTY_GUIDANCE_LINE = "Use wiki_search only when a relevant visible wiki is listed."


def available_wikis_block(
    *,
    profile: str | None = None,
    home_resolver: HomeResolver | None = None,
    config: Mapping[str, Any] | None = None,
) -> str:
    """Return the ``# Available Wikis`` prompt block for ``profile``.

    The block is safe for zero visible wikis and only includes rows returned by
    the visibility resolver, so private/blacklisted/non-whitelisted/archived
    wikis are never named.
    """

    rows = resolve_visible_wikis(
        include_archived=False,
        profile=profile,
        home_resolver=home_resolver,
        config=config,
    )
    lines = ["# Available Wikis", "You have access to the following knowledge bases:"]
    if not rows:
        lines.extend(["No visible wikis.", EMPTY_GUIDANCE_LINE])
        return "\n".join(lines)

    for row in sorted(rows, key=lambda item: str(item.get("slug") or "")):
        lines.append(_format_wiki_line(row))
    lines.append(GUIDANCE_LINE)
    return "\n".join(lines)


def _format_wiki_line(row: Mapping[str, Any]) -> str:
    slug = str(row.get("slug") or "").strip()
    domain = str(row.get("domain") or "domain unavailable").strip() or "domain unavailable"
    page_count = _int_or_zero(row.get("page_count"))
    health = _format_health(row.get("health_score"))
    return f"- {slug}: {domain} ({page_count} pages, health {health})"


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _format_health(value: Any) -> str:
    if value is None:
        return "unknown"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


__all__ = ["EMPTY_GUIDANCE_LINE", "GUIDANCE_LINE", "available_wikis_block"]
