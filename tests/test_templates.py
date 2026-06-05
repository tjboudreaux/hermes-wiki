"""Tests for per-wiki starter Markdown templates."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_wiki import templates


def _assert_markdown_sane(text: str) -> None:
    assert text.endswith("\n")
    assert text.count("```") % 2 == 0
    assert "[[" not in text


def test_write_wiki_starter_files_generates_required_markdown_sections(
    tmp_path: Path,
) -> None:
    """Wiki creation scaffolds SCHEMA.md, index.md, and log.md starter files."""
    wiki_root = tmp_path / "wikis" / "ai-tooling"

    result = templates.write_wiki_starter_files(
        wiki_root,
        slug="ai-tooling",
        domain="AI agents, coding tools, research",
        author="tester",
        author_kind="human",
        created="2026-06-05T00:00:00Z",
    )

    assert result.created_files == (
        wiki_root / "SCHEMA.md",
        wiki_root / "index.md",
        wiki_root / "log.md",
    )
    assert result.wiki_root == wiki_root

    schema = (wiki_root / "SCHEMA.md").read_text(encoding="utf-8")
    _assert_markdown_sane(schema)
    assert "# Schema: ai-tooling" in schema
    assert "## Domain" in schema
    assert "AI agents, coding tools, research" in schema
    assert "## Taxonomy" in schema
    assert "## Propagation Rules" in schema
    assert "## Monitors" in schema
    assert "## Trusted Plugins" in schema
    assert "### Trusted Classifiers" in schema
    assert "### Trusted Processors" in schema
    assert "trusted_plugins:" in schema
    assert "monitors:" in schema
    assert "private: false" in schema

    index = (wiki_root / "index.md").read_text(encoding="utf-8")
    _assert_markdown_sane(index)
    assert "# Index: ai-tooling" in index
    for heading in (
        "## Sources",
        "## Concepts",
        "## Entities",
        "## Comparisons",
        "## Queries",
        "## Summaries",
    ):
        assert heading in index
    assert "_No pages yet._" in index

    log = (wiki_root / "log.md").read_text(encoding="utf-8")
    _assert_markdown_sane(log)
    assert "# Log: ai-tooling" in log
    assert "append-only" in log
    assert "| Time | Action | Target | Author | Author Kind | Details |" in log
    assert "| 2026-06-05T00:00:00Z | create | ai-tooling | tester | human |" in log


def test_write_wiki_starter_files_refuses_to_clobber_existing_files(
    tmp_path: Path,
) -> None:
    """Starter generation protects existing authoritative Markdown by default."""
    wiki_root = tmp_path / "wikis" / "ai-tooling"
    wiki_root.mkdir(parents=True)
    existing_schema = wiki_root / "SCHEMA.md"
    existing_schema.write_text("human edits\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        templates.write_wiki_starter_files(
            wiki_root,
            slug="ai-tooling",
            domain="AI agents",
            author="tester",
        )

    assert existing_schema.read_text(encoding="utf-8") == "human edits\n"


def test_generated_schema_contains_editable_placeholders_for_later_features() -> None:
    """The SCHEMA template is canonical markdown for taxonomy, monitors, and trust."""
    schema = templates.generate_schema_markdown(
        slug="ai-tooling",
        domain=None,
        created="2026-06-05T00:00:00Z",
    )

    _assert_markdown_sane(schema)
    assert "TODO: describe the wiki's domain scope" in schema
    assert "- tag: TODO" in schema
    assert "auto_link_kanban: false" in schema
    assert "name: TODO-monitor-name" in schema
    assert "path: plugins/classifiers/TODO.py" in schema
    assert "path: plugins/processors/TODO.py" in schema
