"""Portable Monitor definitions stored with each LLM Wiki."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
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

SUPPORTED_SOURCES = frozenset({"arxiv", "rss", "x"})

_MONITOR_BLOCK_RE = re.compile(
    r"\n?<!-- wiki-monitor (?P<name>[A-Za-z0-9_-]+) -->"
    r"\n```yaml\n(?P<body>.*?)\n```\n?",
    re.DOTALL,
)


class MonitorError(RuntimeError):
    """Raised for clean user-facing monitor failures."""


@dataclass(frozen=True, slots=True)
class MonitorDefinition:
    """Portable desired monitor definition stored in ``SCHEMA.md``."""

    name: str
    source: str
    schedule: str
    env: dict[str, str]
    prompt: str
    skills: tuple[str, ...] = ("wiki-ingest",)
    enabled: bool = True
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DefineMonitorResult:
    """Result returned after a monitor definition write."""

    wiki: str
    path: Path
    definition: MonitorDefinition
    created: bool
    commit_id: str | None


def define_monitor(
    *,
    source: str,
    wiki: str | None = None,
    profile: str | None = None,
    name: str | None = None,
    schedule: str | None = None,
    prompt: str | None = None,
    skills: tuple[str, ...] | None = None,
    author: str | None = None,
) -> DefineMonitorResult:
    """Define or update one portable Monitor in the resolved wiki's ``SCHEMA.md``.

    This intentionally does **not** call the cron seam. Defining desired state is
    separate from scheduling; a later explicit reconcile command owns cron writes.
    """

    clean_source = _validate_source(source)
    clean_name = _validate_name(name or _default_name(clean_source))
    clean_schedule = _one_line(schedule or _default_schedule(clean_source), "schedule")
    clean_prompt = _one_line(prompt or _default_prompt(clean_source), "prompt")
    clean_skills = _validate_skills(skills or ("wiki-ingest",))
    acting_author, acting_kind = resolve_actor(author=author, author_kind="human")
    try:
        resolved = ensure_wiki_mutable(slug=wiki, profile=profile)
    except WikiManagementError as exc:
        raise MonitorError(NOT_FOUND_OR_NOT_VISIBLE) from exc

    definition = MonitorDefinition(
        name=clean_name,
        source=clean_source,
        schedule=clean_schedule,
        enabled=True,
        skills=clean_skills,
        env={"HERMES_WIKI": resolved.slug},
        prompt=clean_prompt,
        metadata={"defined_by": acting_author, "author_kind": acting_kind},
    )
    created = _replace_schema_monitor_record(resolved.path, definition)
    timestamp = utc_now()
    append_log_entry(
        resolved.path,
        timestamp=timestamp,
        action="monitor",
        target=definition.name,
        author=acting_author,
        author_kind=acting_kind,
        details={
            "source": definition.source,
            "schedule": definition.schedule,
            "wiki": resolved.slug,
            "created": created,
        },
    )
    commit = git_ops.commit_change(
        resolved.path,
        action="monitor",
        what=definition.name,
        author=acting_author,
    )
    return DefineMonitorResult(
        wiki=resolved.slug,
        path=resolved.path,
        definition=definition,
        created=created,
        commit_id=commit.commit_id,
    )


def read_schema_monitor_records(wiki_root: Path | str) -> list[dict[str, Any]]:
    """Parse canonical Monitor records from ``SCHEMA.md`` marker blocks."""

    schema = Path(wiki_root) / "SCHEMA.md"
    if not schema.exists():
        return []
    text = schema.read_text(encoding="utf-8")
    records: list[dict[str, Any]] = []
    for match in _MONITOR_BLOCK_RE.finditer(text):
        marker_name = match.group("name")
        try:
            loaded = yaml.safe_load(match.group("body")) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(loaded, dict):
            continue
        monitors = loaded.get("monitors")
        if not isinstance(monitors, list) or not monitors:
            continue
        record = monitors[0]
        if not isinstance(record, dict):
            continue
        normalized = _normalize_record(record, marker_name=marker_name)
        if normalized is not None:
            records.append(normalized)
    records.sort(key=lambda row: str(row["name"]))
    return records


def _replace_schema_monitor_record(wiki_root: Path, definition: MonitorDefinition) -> bool:
    schema = wiki_root / "SCHEMA.md"
    text = schema.read_text(encoding="utf-8")
    updated, removed = _remove_monitor_blocks_from_text(text, name=definition.name)
    block = _render_monitor_block(definition)
    schema.write_text(updated.rstrip() + block + "\n", encoding="utf-8")
    return not removed


def _remove_monitor_blocks_from_text(text: str, *, name: str) -> tuple[str, list[str]]:
    removed: list[str] = []

    def replace(match: re.Match[str]) -> str:
        block_name = match.group("name")
        if block_name != name:
            return match.group(0)
        removed.append(block_name)
        return "\n"

    return _MONITOR_BLOCK_RE.sub(replace, text), removed


def _render_monitor_block(definition: MonitorDefinition) -> str:
    lines = [
        "",
        f"<!-- wiki-monitor {definition.name} -->",
        "```yaml",
        "monitors:",
        f"  - name: {_plain_yaml(definition.name)}",
        f"    source: {_plain_yaml(definition.source)}",
        f"    schedule: {_yaml_scalar(definition.schedule)}",
        f"    enabled: {str(definition.enabled).lower()}",
        "    skills:",
    ]
    lines.extend(f"      - {_plain_yaml(skill)}" for skill in definition.skills)
    lines.extend(
        [
            "    env:",
            f"      HERMES_WIKI: {_plain_yaml(definition.env['HERMES_WIKI'])}",
            f"    prompt: {_yaml_scalar(definition.prompt)}",
        ]
    )
    if definition.metadata:
        lines.append("    metadata:")
        lines.extend(
            f"      {key}: {_yaml_scalar(value)}"
            for key, value in sorted(definition.metadata.items())
        )
    lines.extend(["```", ""])
    return "\n".join(lines)


def _normalize_record(record: dict[str, Any], *, marker_name: str) -> dict[str, Any] | None:
    name = str(record.get("name") or marker_name)
    if name != marker_name:
        return None
    source = str(record.get("source") or "")
    if source not in SUPPORTED_SOURCES:
        return None
    env = record.get("env")
    if not isinstance(env, dict):
        env = {}
    skills = record.get("skills")
    if isinstance(skills, str):
        skills = [skills]
    if not isinstance(skills, list):
        skills = []
    return {
        "name": name,
        "source": source,
        "schedule": str(record.get("schedule") or ""),
        "enabled": bool(record.get("enabled", True)),
        "skills": [str(skill) for skill in skills],
        "env": {str(key): str(value) for key, value in env.items()},
        "prompt": str(record.get("prompt") or ""),
        "metadata": record.get("metadata") if isinstance(record.get("metadata"), dict) else {},
    }


def _default_name(source: str) -> str:
    if source == "arxiv":
        return "weekly-arxiv-sweep"
    if source == "rss":
        return "daily-rss-sweep"
    return "daily-x-sweep"


def _default_schedule(source: str) -> str:
    if source == "arxiv":
        return "0 9 * * 1"
    if source == "rss":
        return "0 8 * * *"
    return "0 10 * * *"


def _default_prompt(source: str) -> str:
    if source == "arxiv":
        return "Sweep arxiv for new domain-relevant papers and ingest any matches into the wiki"
    if source == "rss":
        return "Sweep configured RSS feeds for new domain-relevant items and ingest matches"
    return "Sweep X for new domain-relevant posts and ingest any matches into the wiki"


def _validate_source(source: str) -> str:
    clean = _one_line(source, "source")
    if clean not in SUPPORTED_SOURCES:
        allowed = "|".join(sorted(SUPPORTED_SOURCES))
        raise MonitorError(f"unsupported monitor source {clean!r}; expected {allowed}")
    return clean


def _validate_name(name: str) -> str:
    clean = _one_line(name, "name")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", clean):
        raise MonitorError("monitor name must contain only letters, numbers, hyphen, or underscore")
    return clean


def _validate_skills(skills: tuple[str, ...]) -> tuple[str, ...]:
    clean = tuple(_one_line(skill, "skill") for skill in skills)
    if not clean:
        raise MonitorError("at least one monitor skill is required")
    return clean


def _plain_yaml(value: str) -> str:
    clean = _one_line(value, "value")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/@-]*", clean):
        return _yaml_scalar(clean)
    return clean


def _yaml_scalar(value: str) -> str:
    return json.dumps(_one_line(value, "value"))


def _one_line(value: str, field: str) -> str:
    clean = str(value).strip()
    if not clean:
        raise MonitorError(f"{field} is required")
    if "\n" in clean or "\r" in clean:
        raise MonitorError(f"{field} must be a single line")
    return clean


__all__ = [
    "SUPPORTED_SOURCES",
    "DefineMonitorResult",
    "MonitorDefinition",
    "MonitorError",
    "define_monitor",
    "read_schema_monitor_records",
]
