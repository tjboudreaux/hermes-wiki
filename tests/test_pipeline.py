"""Integration tests for single-source ingest and propagation."""

from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import yaml

from hermes_wiki import pipeline
from hermes_wiki_cli.cli import main


def _run_cli(tmp_path: Path, *argv: str, env: dict[str, str] | None = None) -> int:
    merged = {"HERMES_HOME": str(tmp_path), "USER": "ingest-tester", **(env or {})}
    old = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(merged)
        return main(list(argv))
    finally:
        os.environ.clear()
        os.environ.update(old)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _write_article(path: Path, *, title: str = "Hermes Memory Article") -> None:
    path.write_text(
        "\n".join(
            [
                f"# {title}",
                "",
                "Hermes Wiki helps coding agents preserve Durable Agent Memory.",
                "Durable Agent Memory lets Hermes connect source snapshots to concepts.",
                "The article mentions Hermes, Source Snapshots, and Agent Memory repeatedly.",
            ]
        ),
        encoding="utf-8",
    )


def _read_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    _, metadata_text, body = text.split("---", 2)
    metadata = yaml.safe_load(metadata_text) or {}
    assert isinstance(metadata, dict)
    return metadata, body


def _latest_source_page(wiki_root: Path) -> Path:
    return sorted((wiki_root / "sources").glob("*.md"))[-1]


def test_cli_ingest_local_source_creates_pages_projection_log_and_git(
    tmp_path: Path,
    capsys,
) -> None:
    """Single-source ingest writes pages, raw evidence, projection rows, log, and commit."""
    assert _run_cli(tmp_path, "create", "ai-tooling", "--domain", "AI agents") == 0
    article = tmp_path / "article.md"
    _write_article(article)
    capsys.readouterr()

    assert _run_cli(tmp_path, "ingest", str(article), "--wiki", "ai-tooling") == 0
    out = capsys.readouterr().out
    assert "class=article" in out
    assert "sources/" in out

    wiki_root = tmp_path / "wikis" / "ai-tooling"
    source_page = _latest_source_page(wiki_root)
    metadata, body = _read_frontmatter(source_page)
    assert source_page.name.startswith("2026-") or source_page.name[:10].count("-") == 2
    assert metadata["id"] == source_page.with_suffix("").relative_to(wiki_root).as_posix()
    assert metadata["type"] == "source"
    assert metadata["author"] == "ingest-tester"
    assert metadata["author_kind"] == "human"
    assert metadata["sources"]
    assert "Curated summary" in body
    assert "](../raw/articles/" in body
    assert body.strip() != article.read_text(encoding="utf-8").strip()

    concept_pages = sorted((wiki_root / "concepts").glob("*.md"))
    entity_pages = sorted((wiki_root / "entities").glob("*.md"))
    assert concept_pages or entity_pages
    derived_page = (concept_pages or entity_pages)[0]
    derived_metadata, derived_body = _read_frontmatter(derived_page)
    assert metadata["sources"][0] in derived_metadata["sources"]
    assert f"](../sources/{source_page.name})" in derived_body

    index_text = (wiki_root / "index.md").read_text(encoding="utf-8")
    assert metadata["id"] in index_text
    assert derived_metadata["id"] in index_text
    log_text = (wiki_root / "log.md").read_text(encoding="utf-8")
    assert "ingest" in log_text
    assert "ingest-tester" in log_text
    assert "human" in log_text

    with sqlite3.connect(wiki_root / "wiki.db") as conn:
        conn.row_factory = sqlite3.Row
        page_ids = {row["id"] for row in conn.execute("SELECT id FROM pages")}
        assert metadata["id"] in page_ids
        assert derived_metadata["id"] in page_ids
        latest_ingest = conn.execute(
            "SELECT source_type, sha256, pages_created, author, author_kind FROM ingest_log"
        ).fetchone()
        assert latest_ingest["source_type"] == "article"
        assert latest_ingest["sha256"]
        assert metadata["id"] in latest_ingest["pages_created"]
        latest_source = conn.execute(
            "SELECT id, version, is_latest, classified_as, sha256 FROM sources"
        ).fetchone()
        assert latest_source["id"] == metadata["sources"][0]
        assert latest_source["version"] == 1
        assert latest_source["is_latest"] == 1
        assert latest_source["classified_as"] == "article"
        assert latest_source["sha256"] == latest_ingest["sha256"]
        assert conn.execute("SELECT count(*) FROM pages_fts").fetchone()[0] == len(page_ids)

    assert _run_cli(tmp_path, "search", "Durable", "--wiki", "ai-tooling") == 0
    assert metadata["id"] in capsys.readouterr().out
    registry = sqlite3.connect(tmp_path / "wikis" / "wikis.db")
    try:
        row = registry.execute(
            "SELECT page_count, source_count, last_ingest FROM wikis WHERE slug='ai-tooling'"
        ).fetchone()
        assert row[0] >= 2
        assert row[1] == 1
        assert row[2]
    finally:
        registry.close()

    assert "[[" not in source_page.read_text(encoding="utf-8")
    assert not (wiki_root / ".obsidian").exists()
    assert _git(wiki_root, "log", "-1", "--pretty=%s").stdout.strip().startswith(
        "wiki: ingest article"
    )
    tracked = _git(wiki_root, "ls-files").stdout
    assert "wiki.db" not in tracked
    assert "db_versions/manifest.jsonl" in tracked
    assert _git(wiki_root, "status", "--porcelain").stdout.strip() == ""


def test_ingest_cross_links_existing_page_and_increments_inbound_links(tmp_path: Path) -> None:
    """A later ingest mentioning an existing page cross-links and increments inbound_links."""
    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    _write_article(first, title="Agent Memory")
    _write_article(second, title="Hermes Update")

    assert _run_cli(tmp_path, "ingest", str(first), "--wiki", "ai-tooling") == 0
    wiki_root = tmp_path / "wikis" / "ai-tooling"
    existing = wiki_root / "concepts" / "agent-memory.md"
    assert existing.exists()
    with sqlite3.connect(wiki_root / "wiki.db") as conn:
        before = conn.execute(
            "SELECT inbound_links FROM pages WHERE id='concepts/agent-memory'"
        ).fetchone()[0]

    assert _run_cli(tmp_path, "ingest", str(second), "--wiki", "ai-tooling") == 0
    with sqlite3.connect(wiki_root / "wiki.db") as conn:
        after = conn.execute(
            "SELECT inbound_links FROM pages WHERE id='concepts/agent-memory'"
        ).fetchone()[0]
    assert after > before
    assert "../concepts/agent-memory.md" in _latest_source_page(wiki_root).read_text(
        encoding="utf-8"
    )


def test_single_source_ingest_rolls_back_on_processor_failure(tmp_path: Path) -> None:
    """Processor failure leaves no page files, rows, or uncommitted durable artifacts."""
    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    article = tmp_path / "article.md"
    _write_article(article)
    wiki_root = tmp_path / "wikis" / "ai-tooling"
    first_head = _git(wiki_root, "rev-parse", "HEAD").stdout.strip()

    class ExplodingProcessor(pipeline.DefaultProcessor):
        def process(self, request: pipeline.ProcessRequest) -> list[pipeline.GeneratedPage]:
            pages = super().process(request)
            assert pages
            raise pipeline.ProcessorError("boom after planning")

    old = os.environ.copy()
    try:
        os.environ["HERMES_HOME"] = str(tmp_path)
        pipeline.ingest_source(
            str(article),
            wiki="ai-tooling",
            processor=ExplodingProcessor(),
            author="ingest-tester",
        )
    except pipeline.IngestError as exc:
        assert "boom after planning" in str(exc)
    else:  # pragma: no cover - failure expected
        raise AssertionError("ingest unexpectedly succeeded")
    finally:
        os.environ.clear()
        os.environ.update(old)

    assert list((wiki_root / "sources").glob("*.md")) == []
    assert list((wiki_root / "concepts").glob("*.md")) == []
    with sqlite3.connect(wiki_root / "wiki.db") as conn:
        assert conn.execute("SELECT count(*) FROM pages").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM sources").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM ingest_log").fetchone() == (0,)
    assert _git(wiki_root, "rev-parse", "HEAD").stdout.strip() == first_head
    assert _git(wiki_root, "status", "--porcelain").stdout.strip() == ""


def test_empty_inbox_and_plugin_hash_mismatch_listing(tmp_path: Path, capsys) -> None:
    """Empty inbox is clean and modified trusted plugin is shown disabled."""
    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    assert _run_cli(tmp_path, "inbox", "--wiki", "ai-tooling") == 0
    assert "inbox empty" in capsys.readouterr().out.lower()
    assert _run_cli(tmp_path, "ingest", "--inbox", "--wiki", "ai-tooling") == 0
    assert "inbox empty" in capsys.readouterr().out.lower()

    plugin_path = tmp_path / "wikis" / "ai-tooling" / "plugins" / "classifiers" / "foo.py"
    plugin_path.write_text("def classify(path):\n    return None\n", encoding="utf-8")
    assert _run_cli(tmp_path, "plugins", "trust", "classifier", "foo", "--wiki", "ai-tooling") == 0
    capsys.readouterr()
    assert _run_cli(tmp_path, "plugins", "list", "--wiki", "ai-tooling") == 0
    assert "foo" in capsys.readouterr().out

    plugin_path.write_text("def classify(path):\n    return 'changed'\n", encoding="utf-8")
    assert _run_cli(tmp_path, "plugins", "list", "--wiki", "ai-tooling") == 0
    out = capsys.readouterr().out
    assert "foo" in out
    assert "hash-mismatch" in out or "disabled" in out
