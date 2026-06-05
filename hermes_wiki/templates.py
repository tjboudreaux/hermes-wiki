"""Starter Markdown templates for a newly-created LLM Wiki."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

STARTER_FILENAMES = ("SCHEMA.md", "index.md", "log.md")
WIKI_DIRECTORIES = (
    "raw",
    "raw/inbox",
    "raw/articles",
    "raw/papers",
    "raw/transcripts",
    "raw/images",
    "raw/audio",
    "raw/video",
    "raw/code",
    "raw/unknown",
    "entities",
    "concepts",
    "comparisons",
    "sources",
    "queries",
    "summaries",
    "_archive",
    "plugins",
    "plugins/classifiers",
    "plugins/processors",
)
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")


@dataclass(frozen=True, slots=True)
class StarterFilesResult:
    """Result of writing starter Markdown files for a wiki."""

    wiki_root: Path
    created_files: tuple[Path, Path, Path]
    directories: tuple[Path, ...]


def write_wiki_starter_files(
    wiki_root: Path | str,
    *,
    slug: str,
    domain: str | None = None,
    author: str | None = None,
    author_kind: str = "human",
    created: str | None = None,
    overwrite: bool = False,
) -> StarterFilesResult:
    """Create starter ``SCHEMA.md``, ``index.md``, and ``log.md`` files.

    Existing files are protected by default because these Markdown artifacts are
    wiki-authoritative durable content. Pass ``overwrite=True`` only for an
    explicit re-scaffold operation.
    """

    root = Path(wiki_root)
    clean_slug = _validate_slug(slug)
    created_at = _timestamp(created)
    clean_author = _default_author(author)
    clean_author_kind = _one_line_required(author_kind, "author_kind")

    schema_path = root / "SCHEMA.md"
    index_path = root / "index.md"
    log_path = root / "log.md"
    paths = (schema_path, index_path, log_path)
    if not overwrite:
        existing = [path for path in paths if path.exists()]
        if existing:
            raise FileExistsError(
                "refusing to overwrite existing wiki starter file(s): "
                + ", ".join(str(path) for path in existing)
            )

    directories = ensure_wiki_directories(root)
    schema_path.write_text(
        generate_schema_markdown(slug=clean_slug, domain=domain, created=created_at),
        encoding="utf-8",
    )
    index_path.write_text(
        generate_index_markdown(slug=clean_slug, domain=domain, created=created_at),
        encoding="utf-8",
    )
    log_path.write_text(
        generate_log_markdown(
            slug=clean_slug,
            author=clean_author,
            author_kind=clean_author_kind,
            created=created_at,
        ),
        encoding="utf-8",
    )
    return StarterFilesResult(wiki_root=root, created_files=paths, directories=directories)


def ensure_wiki_directories(wiki_root: Path | str) -> tuple[Path, ...]:
    """Create the standard per-wiki content and plugin directories."""

    root = Path(wiki_root)
    root.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for rel in WIKI_DIRECTORIES:
        directory = root / rel
        directory.mkdir(parents=True, exist_ok=True)
        created.append(directory)
    return tuple(created)


def generate_schema_markdown(
    *,
    slug: str,
    domain: str | None = None,
    created: str | None = None,
) -> str:
    """Return the starter Schema Markdown for a wiki."""

    clean_slug = _validate_slug(slug)
    created_at = _timestamp(created)
    clean_domain = _display_domain(domain)
    domain_yaml = _yaml_quote(clean_domain)
    return "\n".join(
        [
            f"# Schema: {clean_slug}",
            "",
            "This Schema is the domain contract for this LLM Wiki. Markdown files and",
            "Raw Sources are authoritative; SQLite projections are rebuildable support views.",
            "",
            "## Domain",
            "",
            clean_domain,
            "",
            "```yaml",
            f"slug: {clean_slug}",
            f"domain: {domain_yaml}",
            "private: false",
            f"created: {created_at}",
            "```",
            "",
            "## Page Types",
            "",
            "- `source` — curated Source Pages that summarize immutable Source Snapshots.",
            "- `entity` — people, organizations, products, projects, or concrete nouns.",
            "- `concept` — ideas, methods, patterns, claims, or mechanisms.",
            "- `comparison` — structured tradeoffs between entities or concepts.",
            "- `query` — saved research questions and answer trails.",
            "- `summary` — synthesized overviews spanning multiple Wiki Pages.",
            "",
            "## Taxonomy",
            "",
            "Use this section to define allowed tags and any domain-specific constraints.",
            "",
            "```yaml",
            "taxonomy:",
            "  - tag: TODO",
            "    description: TODO: describe the tag and when agents should apply it",
            "    page_types: [entity, concept, comparison, query, summary, source]",
            "required_frontmatter:",
            "  - id",
            "  - title",
            "  - type",
            "  - created",
            "  - updated",
            "  - author",
            "  - author_kind",
            "  - sources",
            "```",
            "",
            "## Propagation Rules",
            "",
            "Propagation rules tell ingest and page-edit surfaces how to keep the Index, Log,",
            "links, and projection synchronized after a durable write.",
            "",
            "```yaml",
            "propagation_rules:",
            "  update_index: true",
            "  append_log: true",
            "  refresh_projection: true",
            "  cross_link_existing_pages: true",
            "  standard_markdown_links_only: true",
            "  auto_link_kanban: false",
            "  page_line_limit: 200",
            "```",
            "",
            "## Monitors",
            "",
            "Portable Monitor definitions live here. Scheduling is reconciled separately into",
            "Hermes cron and must scope writes with `HERMES_WIKI`.",
            "",
            "```yaml",
            "monitors:",
            "  - name: TODO-monitor-name",
            "    source: rss",
            "    schedule: \"0 9 * * 1\"",
            "    enabled: false",
            f"    env: {{ HERMES_WIKI: {clean_slug} }}",
            "    prompt: TODO: describe what this monitor should sweep or verify",
            "```",
            "",
            "## Trusted Plugins",
            "",
            "Custom classifier and processor code is never executed merely because a file",
            "exists. Trust is canonical here as path + sha256 and projected to `wiki.db`.",
            "",
            "### Trusted Classifiers",
            "",
            "```yaml",
            "trusted_plugins:",
            "  classifiers:",
            "    - name: TODO-classifier",
            "      kind: classifier",
            "      path: plugins/classifiers/TODO.py",
            "      sha256: TODO",
            "      trusted_at: TODO",
            "      author: TODO",
            "      author_kind: human",
            "```",
            "",
            "### Trusted Processors",
            "",
            "```yaml",
            "trusted_plugins:",
            "  processors:",
            "    - name: TODO-processor",
            "      kind: processor",
            "      path: plugins/processors/TODO.py",
            "      sha256: TODO",
            "      trusted_at: TODO",
            "      author: TODO",
            "      author_kind: human",
            "```",
            "",
        ]
    )


def generate_index_markdown(
    *,
    slug: str,
    domain: str | None = None,
    created: str | None = None,
) -> str:
    """Return the starter Index Markdown for a wiki."""

    clean_slug = _validate_slug(slug)
    created_at = _timestamp(created)
    clean_domain = _display_domain(domain)
    sections = (
        "Sources",
        "Concepts",
        "Entities",
        "Comparisons",
        "Queries",
        "Summaries",
    )
    lines = [
        f"# Index: {clean_slug}",
        "",
        f"Domain: {clean_domain}",
        f"Created: {created_at}",
        "",
        "This Index is the sectioned catalog of Wiki Pages. It should contain standard",
        "relative Markdown links only; search metadata belongs in the rebuildable projection.",
        "",
    ]
    for section in sections:
        lines.extend([f"## {section}", "", "_No pages yet._", ""])
    return "\n".join(lines)


def generate_log_markdown(
    *,
    slug: str,
    author: str | None = None,
    author_kind: str = "human",
    created: str | None = None,
) -> str:
    """Return the starter append-only action Log Markdown for a wiki."""

    clean_slug = _validate_slug(slug)
    created_at = _timestamp(created)
    clean_author = _default_author(author)
    clean_author_kind = _one_line_required(author_kind, "author_kind")
    return "\n".join(
        [
            f"# Log: {clean_slug}",
            "",
            "This is the append-only action log for this LLM Wiki. Page History is rendered",
            "from this Log, git commits, and the projection outside Wiki Page bodies.",
            "",
            "| Time | Action | Target | Author | Author Kind | Details |",
            "| --- | --- | --- | --- | --- | --- |",
            (
                f"| {_table_cell(created_at)} | create | {_table_cell(clean_slug)} | "
                f"{_table_cell(clean_author)} | {_table_cell(clean_author_kind)} | "
                "Generated starter SCHEMA.md, index.md, and log.md. |"
            ),
            "",
        ]
    )


def _timestamp(value: str | None) -> str:
    if value is not None:
        return _one_line_required(value, "created")
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_slug(slug: str) -> str:
    clean_slug = _one_line_required(slug, "slug")
    if not _SLUG_RE.fullmatch(clean_slug):
        raise ValueError(
            "wiki slug must be lowercase alphanumeric with optional single-hyphen separators"
        )
    return clean_slug


def _default_author(author: str | None) -> str:
    if author is not None:
        return _one_line_required(author, "author")
    return _one_line_required(os.environ.get("USER") or "unknown", "author")


def _display_domain(domain: str | None) -> str:
    if domain is None or domain.strip() == "":
        return "TODO: describe the wiki's domain scope"
    return _one_line_required(domain, "domain")


def _one_line_required(value: str, field: str) -> str:
    clean_value = value.strip()
    if not clean_value:
        raise ValueError(f"{field} is required")
    if "\n" in clean_value or "\r" in clean_value:
        raise ValueError(f"{field} must be a single line")
    return clean_value


def _yaml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _table_cell(value: str) -> str:
    return value.replace("|", r"\|")


__all__ = [
    "STARTER_FILENAMES",
    "WIKI_DIRECTORIES",
    "StarterFilesResult",
    "ensure_wiki_directories",
    "generate_index_markdown",
    "generate_log_markdown",
    "generate_schema_markdown",
    "write_wiki_starter_files",
]
