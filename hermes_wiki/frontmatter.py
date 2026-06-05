"""YAML frontmatter helpers for authoritative Wiki Page Markdown files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class FrontmatterError(ValueError):
    """Raised when a Markdown file does not contain valid YAML frontmatter."""


def read_markdown(path: Path | str) -> tuple[dict[str, Any], str]:
    """Read ``path`` as a frontmatter Markdown document."""

    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise FrontmatterError(f"{file_path}: missing YAML frontmatter")
    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        raise FrontmatterError(f"{file_path}: unterminated YAML frontmatter")
    try:
        loaded = yaml.safe_load("\n".join(lines[1:closing_index])) or {}
    except yaml.YAMLError as exc:
        raise FrontmatterError(f"{file_path}: invalid YAML frontmatter: {exc}") from exc
    if not isinstance(loaded, dict):
        raise FrontmatterError(f"{file_path}: YAML frontmatter must be a mapping")
    body = "\n".join(lines[closing_index + 1 :]).strip()
    return loaded, body


def write_markdown(path: Path | str, metadata: dict[str, Any], body: str) -> None:
    """Write a Markdown document with deterministic block-style YAML frontmatter."""

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = yaml.safe_dump(
        metadata,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).strip()
    file_path.write_text(f"---\n{frontmatter}\n---\n\n{body.rstrip()}\n", encoding="utf-8")


__all__ = ["FrontmatterError", "read_markdown", "write_markdown"]
