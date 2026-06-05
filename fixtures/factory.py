"""Shared test-wiki factory for Hermes Wiki validators and integration tests."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from fixtures import seed_data
from fixtures.seed_data import LintFindingSeed, PageSeed
from hermes_wiki import db, git_ops, projection, templates

OVERSIZED_SAMPLE_BYTES = 50 * 1024 * 1024 + 1


@dataclass(frozen=True, slots=True)
class TestWikiFixture:
    """Paths and deterministic identifiers for a populated fixture home."""

    home: Path
    registry_db: Path
    primary_slug: str
    archived_slug: str
    private_slug: str
    primary_wiki_root: Path
    archived_wiki_root: Path
    private_wiki_root: Path
    primary_wiki_db: Path
    page_ids: tuple[str, ...]
    raw_source_paths: tuple[str, ...]
    inbox_paths: dict[str, Path]
    lint_findings: tuple[LintFindingSeed, ...]
    profile: str


def build_test_wiki(tmp_path: Path | str) -> TestWikiFixture:
    """Build a fully populated deterministic Hermes home under ``tmp_path``.

    The returned home is ``Path(tmp_path) / "hermes-home"`` and never points at
    the user's live ``~/.hermes`` or the repository-local mission harness home.
    """

    return build_populated_home(Path(tmp_path) / "hermes-home")


def build_populated_home(home: Path | str) -> TestWikiFixture:
    """Build the shared multi-wiki fixture in an exact isolated home path."""

    target_home = Path(home)
    _assert_safe_home(target_home)
    wikis_dir = target_home / "wikis"
    wikis_dir.mkdir(parents=True, exist_ok=True)

    primary_root = _create_primary_wiki(target_home)
    archived_root = _create_registry_wiki(
        target_home,
        slug=seed_data.ARCHIVED_WIKI_SLUG,
        domain=seed_data.ARCHIVED_WIKI_DOMAIN,
        private=False,
    )
    private_root = _create_registry_wiki(
        target_home,
        slug=seed_data.PRIVATE_WIKI_SLUG,
        domain=seed_data.PRIVATE_WIKI_DOMAIN,
        private=True,
    )

    (wikis_dir / "default").write_text(seed_data.PRIMARY_WIKI_SLUG + "\n", encoding="utf-8")
    (wikis_dir / f"{seed_data.PROFILE_NAME}.current").write_text(
        seed_data.PRIMARY_WIKI_SLUG + "\n",
        encoding="utf-8",
    )

    registry_db = wikis_dir / "wikis.db"
    with db.connect_registry(registry_db) as conn:
        db.initialize_registry(conn)
        db.upsert_wiki(
            conn,
            slug=seed_data.PRIMARY_WIKI_SLUG,
            path=primary_root,
            domain=seed_data.PRIMARY_WIKI_DOMAIN,
            created=seed_data.FIXED_PREVIOUS,
            updated=seed_data.FIXED_NOW,
            page_count=len(seed_data.PRIMARY_PAGES),
            source_count=len(seed_data.RAW_SOURCE_DESTINATIONS),
            last_ingest=seed_data.FIXED_NOW,
            last_lint=seed_data.FIXED_NOW,
            health_score=0.72,
        )
        db.upsert_wiki(
            conn,
            slug=seed_data.ARCHIVED_WIKI_SLUG,
            path=archived_root,
            domain=seed_data.ARCHIVED_WIKI_DOMAIN,
            created=seed_data.FIXED_PREVIOUS,
            updated=seed_data.FIXED_NOW,
            page_count=0,
            source_count=0,
            last_lint=seed_data.FIXED_NOW,
            health_score=0.95,
            archived=1,
            archived_at=seed_data.FIXED_NOW,
        )
        db.upsert_wiki(
            conn,
            slug=seed_data.PRIVATE_WIKI_SLUG,
            path=private_root,
            domain=seed_data.PRIVATE_WIKI_DOMAIN,
            created=seed_data.FIXED_PREVIOUS,
            updated=seed_data.FIXED_NOW,
            page_count=0,
            source_count=0,
            last_lint=seed_data.FIXED_NOW,
            health_score=1.0,
        )
        conn.commit()

    inbox_paths = _write_inbox_samples(primary_root)

    return TestWikiFixture(
        home=target_home,
        registry_db=registry_db,
        primary_slug=seed_data.PRIMARY_WIKI_SLUG,
        archived_slug=seed_data.ARCHIVED_WIKI_SLUG,
        private_slug=seed_data.PRIVATE_WIKI_SLUG,
        primary_wiki_root=primary_root,
        archived_wiki_root=archived_root,
        private_wiki_root=private_root,
        primary_wiki_db=primary_root / "wiki.db",
        page_ids=tuple(page.id for page in seed_data.PRIMARY_PAGES),
        raw_source_paths=tuple(seed_data.RAW_SOURCE_DESTINATIONS.values()),
        inbox_paths=inbox_paths,
        lint_findings=seed_data.LINT_FINDINGS,
        profile=seed_data.PROFILE_NAME,
    )


def _assert_safe_home(home: Path) -> None:
    resolved = home.expanduser().resolve()
    live = (Path.home() / ".hermes").resolve()
    if resolved == live or live in resolved.parents:
        raise ValueError(f"refusing to build test fixture under live Hermes home: {resolved}")
    if resolved.exists() and any(resolved.iterdir()):
        raise FileExistsError(f"fixture home must be empty or absent: {resolved}")


def _create_registry_wiki(
    home: Path,
    *,
    slug: str,
    domain: str,
    private: bool,
) -> Path:
    wiki_root = git_ops.initialize_wiki_repo(home, slug)
    templates.write_wiki_starter_files(
        wiki_root,
        slug=slug,
        domain=domain,
        author=seed_data.FIXTURE_AUTHOR,
        author_kind=seed_data.FIXTURE_AUTHOR_KIND,
        created=seed_data.FIXED_PREVIOUS,
    )
    if private:
        schema = wiki_root / "SCHEMA.md"
        schema.write_text(
            schema.read_text(encoding="utf-8").replace("private: false", "private: true"),
            encoding="utf-8",
        )
    projection.rebuild_projection(
        wiki_root,
        rebuild_reason="initial",
        author=seed_data.FIXTURE_AUTHOR,
        author_kind=seed_data.FIXTURE_AUTHOR_KIND,
    )
    git_ops.commit_change(
        wiki_root,
        action="create",
        what=slug,
        author=seed_data.FIXTURE_AUTHOR,
    )
    return wiki_root


def _create_primary_wiki(home: Path) -> Path:
    wiki_root = git_ops.initialize_wiki_repo(home, seed_data.PRIMARY_WIKI_SLUG)
    templates.write_wiki_starter_files(
        wiki_root,
        slug=seed_data.PRIMARY_WIKI_SLUG,
        domain=seed_data.PRIMARY_WIKI_DOMAIN,
        author=seed_data.FIXTURE_AUTHOR,
        author_kind=seed_data.FIXTURE_AUTHOR_KIND,
        created=seed_data.FIXED_PREVIOUS,
    )
    git_ops.commit_change(
        wiki_root,
        action="create",
        what=seed_data.PRIMARY_WIKI_SLUG,
        author=seed_data.FIXTURE_AUTHOR,
    )

    _copy_classified_raw_sources(wiki_root)
    _write_primary_pages(wiki_root, use_initial_agent_memory=True)
    _append_log_row(
        wiki_root,
        action="ingest",
        target="fixture-sources",
        details="Seeded source/entity/concept/comparison/query/summary pages.",
    )
    _rewrite_index(wiki_root)
    git_ops.commit_change(
        wiki_root,
        action="ingest",
        what="fixture-sources",
        author=seed_data.FIXTURE_AUTHOR,
    )

    _write_primary_pages(wiki_root, use_initial_agent_memory=False)
    _append_log_row(
        wiki_root,
        action="edit",
        target="concepts/agent-memory",
        details="Updated links, search-normalization term, and kanban reference.",
    )
    _rewrite_index(wiki_root)
    git_ops.commit_change(
        wiki_root,
        action="edit",
        what="concepts/agent-memory",
        author=seed_data.FIXTURE_AUTHOR,
    )

    projection.rebuild_projection(
        wiki_root,
        rebuild_reason="initial",
        author=seed_data.FIXTURE_AUTHOR,
        author_kind=seed_data.FIXTURE_AUTHOR_KIND,
    )
    _populate_primary_projection(wiki_root)
    git_ops.commit_change(
        wiki_root,
        action="rebuild",
        what="projection",
        author=seed_data.FIXTURE_AUTHOR,
    )
    return wiki_root


def _copy_classified_raw_sources(wiki_root: Path) -> None:
    for kind, destination in seed_data.RAW_SOURCE_DESTINATIONS.items():
        target = wiki_root / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(seed_data.sample_source_path(kind), target)


def _write_primary_pages(wiki_root: Path, *, use_initial_agent_memory: bool) -> None:
    for page in seed_data.PRIMARY_PAGES:
        body = (
            seed_data.INITIAL_AGENT_MEMORY_BODY
            if use_initial_agent_memory and page.id == "concepts/agent-memory"
            else page.body
        )
        metadata = _page_frontmatter(page)
        if use_initial_agent_memory and page.id == "concepts/agent-memory":
            metadata["updated"] = seed_data.FIXED_PREVIOUS
            metadata["links"] = ["entities/hermes"]
            metadata.pop("kanban_refs", None)
        _write_markdown_page(wiki_root / page.relative_path, metadata=metadata, body=body)


def _page_frontmatter(page: PageSeed) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "id": page.id,
        "title": page.title,
        "type": page.type,
        "created": page.created,
        "updated": page.updated,
        "tags": list(page.tags),
        "sources": list(page.sources),
        "confidence": page.confidence,
        "contested": page.contested,
        "author": page.author,
        "author_kind": page.author_kind,
        "links": list(page.links),
    }
    if page.contradictions:
        metadata["contradictions"] = page.contradictions
    if page.kanban_refs:
        metadata["kanban_refs"] = [
            {
                "task_id": ref.task_id,
                "direction": ref.direction,
                "created": ref.created,
            }
            for ref in page.kanban_refs
        ]
    return metadata


def _write_markdown_page(path: Path, *, metadata: dict[str, Any], body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = yaml.safe_dump(
        metadata,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).strip()
    path.write_text(f"---\n{frontmatter}\n---\n\n{body.rstrip()}\n", encoding="utf-8")


def _append_log_row(wiki_root: Path, *, action: str, target: str, details: str) -> None:
    log_path = wiki_root / "log.md"
    row = (
        f"| {seed_data.FIXED_NOW} | {action} | {target} | {seed_data.FIXTURE_AUTHOR} | "
        f"{seed_data.FIXTURE_AUTHOR_KIND} | {details} |\n"
    )
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(row)


def _rewrite_index(wiki_root: Path) -> None:
    sections: dict[str, list[PageSeed]] = {page_type: [] for page_type in seed_data.PAGE_TYPES}
    for page in seed_data.PRIMARY_PAGES:
        sections[page.type].append(page)
    lines = [
        f"# Index: {seed_data.PRIMARY_WIKI_SLUG}",
        "",
        f"Domain: {seed_data.PRIMARY_WIKI_DOMAIN}",
        f"Created: {seed_data.FIXED_PREVIOUS}",
        "",
    ]
    for page_type in seed_data.PAGE_TYPES:
        heading = page_type.title() + "s"
        lines.extend([f"## {heading}", ""])
        for page in sections[page_type]:
            lines.append(f"- [{page.title}]({page.id}.md) — `{page.id}`")
        lines.append("")
    (wiki_root / "index.md").write_text("\n".join(lines), encoding="utf-8")


def _populate_primary_projection(wiki_root: Path) -> None:
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        for page in seed_data.PRIMARY_PAGES:
            page_path = wiki_root / page.relative_path
            db.upsert_page(
                conn,
                id=page.id,
                title=page.title,
                type=page.type,
                created=page.created,
                updated=page.updated,
                tags=page.tags,
                sources=page.sources,
                confidence=page.confidence,
                contested=1 if page.contested else 0,
                contradictions=page.contradictions,
                author=page.author,
                author_kind=page.author_kind,
                sha256=projection.sha256_file(page_path),
                inbound_links=page.inbound_links,
                snippet=_snippet(page.body),
                body_text=page.body,
            )
        for tag in seed_data.TAXONOMY_TAGS:
            db.add_taxonomy_tag(conn, tag=tag, created="2026-06-05")
        for kind, source_id in seed_data.RAW_SOURCE_DESTINATIONS.items():
            source_path = wiki_root / source_id
            db.upsert_source(
                conn,
                id=source_id,
                ingested_at=seed_data.FIXED_NOW,
                sha256=projection.sha256_file(source_path),
                source_url=f"https://fixtures.invalid/{kind}",
                source_path=source_id,
                version=1,
                previous_source_id=None,
                is_latest=1,
                classified_as=kind,
            )
            db.insert_ingest_log(
                conn,
                ingested_at=seed_data.FIXED_NOW,
                source_type=kind,
                source_url=f"https://fixtures.invalid/{kind}",
                source_path=source_id,
                sha256=projection.sha256_file(source_path),
                pages_created=[
                    page.id for page in seed_data.PRIMARY_PAGES if source_id in page.sources
                ],
                pages_updated=[],
                author=seed_data.FIXTURE_AUTHOR,
                author_kind=seed_data.FIXTURE_AUTHOR_KIND,
            )
        db.insert_ingest_log(
            conn,
            ingested_at=seed_data.FIXED_NOW,
            source_type="unknown",
            source_url=None,
            source_path="raw/inbox/unknown-sample.dat",
            sha256=None,
            pages_created=[],
            pages_updated=[],
            author=seed_data.FIXTURE_AUTHOR,
            author_kind=seed_data.FIXTURE_AUTHOR_KIND,
        )
        db.insert_ingest_log(
            conn,
            ingested_at=seed_data.FIXED_NOW,
            source_type="oversized",
            source_url=None,
            source_path="raw/inbox/oversized-sample.bin",
            sha256=None,
            pages_created=[],
            pages_updated=[],
            author=seed_data.FIXTURE_AUTHOR,
            author_kind=seed_data.FIXTURE_AUTHOR_KIND,
        )
        for page in seed_data.PRIMARY_PAGES:
            for ref in page.kanban_refs:
                db.upsert_kanban_ref(
                    conn,
                    page_id=page.id,
                    task_id=ref.task_id,
                    direction=ref.direction,
                    created=ref.created,
                )
        conn.commit()
        db.rebuild_pages_fts(conn)
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _write_inbox_samples(wiki_root: Path) -> dict[str, Path]:
    inbox = wiki_root / "raw" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    unknown_path = inbox / "unknown-sample.dat"
    shutil.copyfile(seed_data.sample_source_path("unknown"), unknown_path)

    oversized_path = inbox / "oversized-sample.bin"
    with oversized_path.open("wb") as handle:
        handle.truncate(OVERSIZED_SAMPLE_BYTES)

    return {"unknown": unknown_path, "oversized": oversized_path}


def _snippet(body: str) -> str | None:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:240]
    return None


__all__ = [
    "OVERSIZED_SAMPLE_BYTES",
    "TestWikiFixture",
    "build_populated_home",
    "build_test_wiki",
]
