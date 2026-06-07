"""System-prompt helpers for Hermes Wiki discovery."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from adapters.base import HomeResolver
from hermes_wiki.visibility import resolve_visible_wikis

GUIDANCE_LINE = (
    "Use wiki_search(query, wiki=<slug>) to consult these knowledge bases when a "
    "question is domain-relevant."
)
EMPTY_GUIDANCE_LINE = "Use wiki_search only when a relevant visible wiki is listed."
WRITE_GUIDANCE_LINE = (
    "Before writing to a wiki (ingesting sources or creating/editing pages), load its "
    'skills first: skill_view("wiki:wiki-ingestion") and skill_view("wiki:wiki-writing") '
    'by default; a wiki listing "skills: ..." above uses those assignments instead.'
)


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
    lines.append(WRITE_GUIDANCE_LINE)
    return "\n".join(lines)


def _format_wiki_line(row: Mapping[str, Any]) -> str:
    slug = str(row.get("slug") or "").strip()
    domain = str(row.get("domain") or "domain unavailable").strip() or "domain unavailable"
    page_count = _int_or_zero(row.get("page_count"))
    health = _format_health(row.get("health_score"))
    return f"- {slug}: {domain} ({page_count} pages, health {health}){_skills_suffix(row)}"


def _skills_suffix(row: Mapping[str, Any]) -> str:
    """Render `` (skills: kind=name, ...)`` for non-default assignments only.

    Reading the record must never break prompt construction: a missing path,
    unreadable or malformed ``SCHEMA.md`` falls back to defaults inside
    ``read_schema_skill_record``, and any other surprise yields no suffix.
    Default assignments are omitted to keep the block lean — the
    ``WRITE_GUIDANCE_LINE`` already names them.
    """

    path_value = row.get("path")
    if not path_value:
        return ""
    try:
        from hermes_wiki.skills import DEFAULT_WIKI_SKILLS, read_schema_skill_record

        record = read_schema_skill_record(Path(str(path_value)))
        overrides = {
            kind: value
            for kind, value in record.items()
            if value != DEFAULT_WIKI_SKILLS.get(kind)
        }
    except Exception:
        return ""
    if not overrides:
        return ""
    rendered = ", ".join(f"{kind}={overrides[kind]}" for kind in sorted(overrides))
    return f" (skills: {rendered})"


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


__all__ = [
    "EMPTY_GUIDANCE_LINE",
    "GUIDANCE_LINE",
    "WRITE_GUIDANCE_LINE",
    "available_wikis_block",
]
