"""Per-wiki skill assignments stored canonically in ``SCHEMA.md``."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from hermes_wiki import git_ops
from hermes_wiki.attribution import append_log_entry, resolve_actor, utc_now
from hermes_wiki.management import (
    NOT_FOUND_OR_NOT_VISIBLE,
    WikiManagementError,
    ensure_wiki_mutable,
)

SKILL_KINDS = ("ingestion", "writing", "media")
DEFAULT_WIKI_SKILLS = {
    "ingestion": "wiki:wiki-ingestion",
    "writing": "wiki:wiki-writing",
    "media": "wiki:wiki-media-ingestion",
}

_SKILLS_BLOCK_RE = re.compile(
    r"\n?<!-- wiki-skills -->"
    r"\n```yaml\n(?P<body>.*?)\n```\n?",
    re.DOTALL,
)
_SKILL_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*")


class SkillsError(RuntimeError):
    """Raised for clean user-facing skill-setting failures."""


def read_wiki_skills(
    *,
    wiki: str | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    """Return the resolved wiki's skill assignments, falling back to defaults."""

    from hermes_wiki.visibility import WikiVisibilityError, require_visible_wiki

    try:
        slug, wiki_root = require_visible_wiki(wiki, profile=profile)
    except WikiVisibilityError as exc:
        raise SkillsError(NOT_FOUND_OR_NOT_VISIBLE) from exc
    return {
        "wiki": slug,
        "skills": read_schema_skill_record(wiki_root),
        "defaults": dict(DEFAULT_WIKI_SKILLS),
    }


def set_wiki_skill(
    kind: str,
    skill: str,
    *,
    wiki: str | None = None,
    profile: str | None = None,
    author: str | None = None,
    author_kind: str | None = None,
) -> dict[str, Any]:
    """Assign one skill kind for the resolved wiki and persist it in SCHEMA.md."""

    clean_kind = _validate_kind(kind)
    clean_skill = _validate_skill_name(skill)
    acting_author, acting_kind = resolve_actor(author=author, author_kind=author_kind)
    try:
        resolved = ensure_wiki_mutable(slug=wiki, profile=profile)
    except WikiManagementError as exc:
        raise SkillsError(NOT_FOUND_OR_NOT_VISIBLE) from exc

    skills = read_schema_skill_record(resolved.path)
    skills[clean_kind] = clean_skill
    _replace_schema_skills_record(resolved.path, skills)
    timestamp = utc_now()
    append_log_entry(
        resolved.path,
        timestamp=timestamp,
        action="skills",
        target=clean_kind,
        author=acting_author,
        author_kind=acting_kind,
        details={"kind": clean_kind, "skill": clean_skill, "wiki": resolved.slug},
    )
    git_ops.commit_change(
        resolved.path,
        action="skills",
        what=f"set {clean_kind} -> {clean_skill}",
        author=acting_author,
    )
    return {
        "wiki": resolved.slug,
        "skills": skills,
        "defaults": dict(DEFAULT_WIKI_SKILLS),
    }


def read_schema_skill_record(wiki_root: Path | str) -> dict[str, str]:
    """Parse the canonical skill record from ``SCHEMA.md``, merged over defaults."""

    skills = dict(DEFAULT_WIKI_SKILLS)
    schema = Path(wiki_root) / "SCHEMA.md"
    if not schema.exists():
        return skills
    match = _SKILLS_BLOCK_RE.search(schema.read_text(encoding="utf-8"))
    if match is None:
        return skills
    try:
        loaded = yaml.safe_load(match.group("body")) or {}
    except yaml.YAMLError:
        return skills
    if not isinstance(loaded, dict):
        return skills
    record = loaded.get("wiki_skills")
    if not isinstance(record, dict):
        return skills
    for kind in SKILL_KINDS:
        value = record.get(kind)
        if isinstance(value, str) and value.strip():
            skills[kind] = value.strip()
    return skills


def render_skills_block(skills: dict[str, str] | None = None) -> str:
    """Render the marker block persisted into ``SCHEMA.md``."""

    record = {**DEFAULT_WIKI_SKILLS, **(skills or {})}
    lines = [
        "",
        "<!-- wiki-skills -->",
        "```yaml",
        "wiki_skills:",
    ]
    lines.extend(f"  {kind}: {record[kind]}" for kind in SKILL_KINDS)
    lines.extend(["```", ""])
    return "\n".join(lines)


def _replace_schema_skills_record(wiki_root: Path, skills: dict[str, str]) -> None:
    schema = wiki_root / "SCHEMA.md"
    text = schema.read_text(encoding="utf-8")
    stripped = _SKILLS_BLOCK_RE.sub("\n", text)
    schema.write_text(
        stripped.rstrip() + render_skills_block(skills) + "\n",
        encoding="utf-8",
    )


def _validate_kind(kind: str) -> str:
    clean = str(kind).strip().lower()
    if clean not in SKILL_KINDS:
        allowed = "|".join(SKILL_KINDS)
        raise SkillsError(f"unsupported skill kind {kind!r}; expected {allowed}")
    return clean


def _validate_skill_name(skill: str) -> str:
    clean = str(skill).strip()
    if not clean:
        raise SkillsError("skill name is required")
    if "\n" in clean or "\r" in clean:
        raise SkillsError("skill name must be a single line")
    if not _SKILL_NAME_RE.fullmatch(clean):
        raise SkillsError(
            "skill name must contain only letters, numbers, hyphen, underscore, dot, or colon"
        )
    return clean


__all__ = [
    "DEFAULT_WIKI_SKILLS",
    "SKILL_KINDS",
    "SkillsError",
    "read_schema_skill_record",
    "read_wiki_skills",
    "render_skills_block",
    "set_wiki_skill",
]
