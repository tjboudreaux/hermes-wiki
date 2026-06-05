"""Integration tests for single-source ingest and propagation."""

from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import yaml

from fixtures.seed_data import SAMPLE_SOURCE_KINDS, sample_source_path
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


def _latest_classified_as(wiki_root: Path) -> str:
    with sqlite3.connect(wiki_root / "wiki.db") as conn:
        row = conn.execute(
            "SELECT classified_as FROM sources ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    return str(row[0])


def _latest_source_path(wiki_root: Path) -> str:
    with sqlite3.connect(wiki_root / "wiki.db") as conn:
        row = conn.execute("SELECT source_path FROM sources ORDER BY rowid DESC LIMIT 1").fetchone()
    assert row is not None
    return str(row[0])


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


def test_builtin_classifiers_recognize_representative_fixtures() -> None:
    """Representative fixtures map to the three built-ins plus the unknown fallback."""
    expected = {
        "article": "article",
        "paper": "paper",
        "transcript": "transcript",
        "unknown": "unknown",
    }
    assert set(SAMPLE_SOURCE_KINDS) == set(expected)
    for kind, label in expected.items():
        path = sample_source_path(kind)
        result = pipeline.classify_source(path.name, path.read_bytes())
        assert result.name == label


def test_classifier_tie_breaking_uses_declared_builtin_order() -> None:
    """Ambiguous built-in matches resolve deterministically by declared order."""
    ambiguous = b"\n".join(
        [
            b"# DOI Blog Clip",
            b"",
            b"Clipped article from a research blog.",
            b"DOI: 10.5555/hermes.tie.001",
            b"Abstract",
            b"This academic-styled blog post intentionally resembles a paper.",
            b"References",
            b"[1] Fixture Research Desk.",
        ]
    )

    labels = [pipeline.classify_source("doi-blog-clip.md", ambiguous).name for _ in range(5)]
    assert labels == ["article"] * 5


def test_cli_ingest_classifies_fixture_inputs_to_expected_raw_subdirs(
    tmp_path: Path,
    capsys,
) -> None:
    """CLI ingest records classified_as and stores snapshots in class-specific raw folders."""
    expected_raw_subdirs = {
        "article": "raw/articles/",
        "paper": "raw/papers/",
        "transcript": "raw/transcripts/",
        "unknown": "raw/unknown/",
    }
    for kind, raw_prefix in expected_raw_subdirs.items():
        wiki = f"{kind}-wiki"
        assert _run_cli(tmp_path, "create", wiki, "--domain", f"{kind} fixtures") == 0
        capsys.readouterr()

        source = sample_source_path(kind)
        assert _run_cli(tmp_path, "ingest", str(source), "--wiki", wiki) == 0
        out = capsys.readouterr().out
        assert f"class={kind}" in out

        wiki_root = tmp_path / "wikis" / wiki
        assert _latest_classified_as(wiki_root) == kind
        assert _latest_source_path(wiki_root).startswith(raw_prefix)
        assert (wiki_root / _latest_source_path(wiki_root)).is_file()


def test_cli_classifier_selection_is_deterministic_for_same_input(
    tmp_path: Path,
    capsys,
) -> None:
    """The same ambiguous source yields the same class in independent wikis."""
    ambiguous = tmp_path / "ambiguous-blog-paper.md"
    ambiguous.write_text(
        "\n".join(
            [
                "# Academic Blog Clip",
                "",
                "Clipped article from a blog about agent memory.",
                "DOI: 10.5555/hermes.deterministic.001",
                "Abstract",
                "This post has paper-like structure but remains clipped blog Markdown.",
                "References",
                "[1] Fixture Research Desk.",
            ]
        ),
        encoding="utf-8",
    )

    labels: list[str] = []
    for index in range(2):
        wiki = f"deterministic-{index}"
        assert _run_cli(tmp_path, "create", wiki) == 0
        assert _run_cli(tmp_path, "ingest", str(ambiguous), "--wiki", wiki) == 0
        labels.append(_latest_classified_as(tmp_path / "wikis" / wiki))
    capsys.readouterr()

    assert labels == ["article", "article"]


def test_trusted_custom_classifier_runs_only_after_builtins(
    tmp_path: Path,
    capsys,
) -> None:
    """Built-ins win over trusted custom classifiers; custom runs only if built-ins abstain."""
    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    wiki_root = tmp_path / "wikis" / "ai-tooling"
    plugin = wiki_root / "plugins" / "classifiers" / "catchall.py"
    plugin.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "from hermes_wiki.models import ClassLabel",
                "",
                "def classify(path: Path):",
                "    if path.read_bytes():",
                "        return ClassLabel('custom-catchall', 'high', 'trusted custom')",
                "    return None",
            ]
        ),
        encoding="utf-8",
    )
    assert (
        _run_cli(
            tmp_path,
            "plugins",
            "trust",
            "classifier",
            "catchall",
            "--wiki",
            "ai-tooling",
        )
        == 0
    )
    capsys.readouterr()

    article = sample_source_path("article")
    assert _run_cli(tmp_path, "ingest", str(article), "--wiki", "ai-tooling") == 0
    assert _latest_classified_as(wiki_root) == "article"

    unknown = sample_source_path("unknown")
    assert _run_cli(tmp_path, "ingest", str(unknown), "--wiki", "ai-tooling") == 0
    assert _latest_classified_as(wiki_root) == "custom-catchall"


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


def test_ingest_without_source_refuses_and_does_not_process_inbox(
    tmp_path: Path,
    capsys,
) -> None:
    """A missing path is never treated as implicit inbox batch ingest."""
    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    wiki_root = tmp_path / "wikis" / "ai-tooling"
    inbox_file = wiki_root / "raw" / "inbox" / "pending-article.md"
    _write_article(inbox_file, title="Pending Inbox Article")
    capsys.readouterr()

    assert _run_cli(tmp_path, "ingest", "--wiki", "ai-tooling") == 1
    captured = capsys.readouterr()
    assert "requires <path|url> or explicit --inbox" in captured.err
    assert inbox_file.is_file()
    assert not list((wiki_root / "sources").glob("*.md"))
    with sqlite3.connect(wiki_root / "wiki.db") as conn:
        assert conn.execute("SELECT count(*) FROM pages").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM sources").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM ingest_log").fetchone() == (0,)


def test_inbox_listing_status_invisibility_and_explicit_batch_processing(
    tmp_path: Path,
    capsys,
) -> None:
    """Inbox files are listed/statused, hidden until processing, and scoped per wiki."""
    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    assert _run_cli(tmp_path, "create", "other-wiki") == 0
    wiki_root = tmp_path / "wikis" / "ai-tooling"
    other_root = tmp_path / "wikis" / "other-wiki"
    inbox = wiki_root / "raw" / "inbox"
    other_inbox_file = other_root / "raw" / "inbox" / "other-article.md"
    first = inbox / "agent-memory-article.md"
    second = inbox / "memory-workshop-transcript.txt"
    unknown = inbox / "mystery.bin"
    _write_article(first, title="Inbox Agent Memory")
    second.write_text(
        "\n".join(
            [
                "Alice: We should preserve BatchOnlyTerm in the Hermes Wiki.",
                "Bob: The transcript remains useful after inbox ingest.",
            ]
        ),
        encoding="utf-8",
    )
    unknown.write_bytes(b"\x00\x01\x02\x03")
    _write_article(other_inbox_file, title="Other Wiki Inbox")
    capsys.readouterr()

    assert _run_cli(tmp_path, "inbox", "--wiki", "ai-tooling") == 0
    out = capsys.readouterr().out
    assert "agent-memory-article.md: not yet attempted" in out
    assert "memory-workshop-transcript.txt: not yet attempted" in out
    assert "mystery.bin: not yet attempted" in out
    assert "agent-memory-article.md" not in (wiki_root / "index.md").read_text(encoding="utf-8")
    assert _run_cli(tmp_path, "search", "BatchOnlyTerm", "--wiki", "ai-tooling") == 0
    assert "No results." in capsys.readouterr().out
    with sqlite3.connect(wiki_root / "wiki.db") as conn:
        assert conn.execute(
            "SELECT count(*) FROM pages WHERE body_text LIKE '%BatchOnlyTerm%'"
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM ingest_log WHERE source_path LIKE '%agent-memory-article.md%'"
        ).fetchone() == (0,)

    assert _run_cli(tmp_path, "ingest", "--inbox", "--wiki", "ai-tooling") == 0
    out = capsys.readouterr().out
    assert "Ingested agent-memory-article.md class=article" in out
    assert "Ingested memory-workshop-transcript.txt class=transcript" in out
    assert "Retained mystery.bin class=unknown" in out
    assert not first.exists()
    assert not second.exists()
    assert unknown.is_file()
    assert other_inbox_file.is_file()
    assert list((wiki_root / "raw" / "articles").glob("*-v1-inbox-agent-memory.md"))
    assert list((wiki_root / "raw" / "transcripts").glob("*-v1-memory-workshop-transcript.txt"))
    with sqlite3.connect(wiki_root / "wiki.db") as conn:
        assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM ingest_log").fetchone()[0] == 3

    assert _run_cli(tmp_path, "inbox", "--wiki", "ai-tooling") == 0
    assert "mystery.bin: unknown" in capsys.readouterr().out
    assert _run_cli(tmp_path, "search", "BatchOnlyTerm", "--wiki", "ai-tooling") == 0
    assert "sources/" in capsys.readouterr().out


def test_inbox_oversize_cap_boundary_and_direct_refusal(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    """Only files larger than the cap are marked oversized; direct oversize is refused."""
    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    wiki_root = tmp_path / "wikis" / "ai-tooling"
    inbox = wiki_root / "raw" / "inbox"
    under = inbox / "under-cap.md"
    over = inbox / "over-cap.md"
    direct = tmp_path / "direct-over.md"
    _write_article(under, title="Under Cap Article")
    under_bytes = under.read_bytes()
    over.write_bytes(under_bytes + b"\nextra")
    direct.write_bytes(under_bytes + b"\nextra")
    monkeypatch.setattr(pipeline, "MAX_INGEST_BYTES", len(under_bytes))
    capsys.readouterr()

    assert _run_cli(tmp_path, "ingest", "--inbox", "--wiki", "ai-tooling") == 0
    out = capsys.readouterr().out
    assert "Ingested under-cap.md class=article" in out
    assert "Skipped over-cap.md status=oversized" in out
    assert not under.exists()
    assert over.is_file()
    assert list((wiki_root / "raw" / "articles").glob("*-v1-under-cap-article.md"))
    with sqlite3.connect(wiki_root / "wiki.db") as conn:
        assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM pages").fetchone()[0] >= 2

    assert _run_cli(tmp_path, "inbox", "--wiki", "ai-tooling") == 0
    assert "over-cap.md: oversized" in capsys.readouterr().out
    assert _run_cli(tmp_path, "ingest", str(direct), "--wiki", "ai-tooling") == 1
    captured = capsys.readouterr()
    assert "oversized" in captured.err
    assert direct.is_file()


def test_url_fetch_failure_and_same_slug_collisions_do_not_corrupt_state(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    """Failed URL fetches create no artifacts; same-day same-slug ingests avoid overwrites."""
    import urllib.error
    from email.message import Message

    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    wiki_root = tmp_path / "wikis" / "ai-tooling"
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    _write_article(first, title="Collision Article")
    _write_article(second, title="Collision Article")
    second.write_text(second.read_text(encoding="utf-8") + "\nDistinct second bytes.\n")
    capsys.readouterr()

    assert _run_cli(tmp_path, "ingest", str(first), "--wiki", "ai-tooling") == 0
    first_source = _latest_source_page(wiki_root)
    first_raw = wiki_root / _latest_source_path(wiki_root)
    first_raw_bytes = first_raw.read_bytes()
    assert _run_cli(tmp_path, "ingest", str(second), "--wiki", "ai-tooling") == 0
    capsys.readouterr()
    source_pages = sorted((wiki_root / "sources").glob("*.md"))
    raw_snapshots = sorted((wiki_root / "raw" / "articles").glob("*.md"))
    assert len(source_pages) == 2
    assert len(raw_snapshots) == 2
    assert first_source in source_pages
    assert first_raw.read_bytes() == first_raw_bytes

    commits_before = _git(wiki_root, "rev-list", "--count", "HEAD").stdout.strip()
    with sqlite3.connect(wiki_root / "wiki.db") as conn:
        logs_before = conn.execute("SELECT count(*) FROM ingest_log").fetchone()[0]
        sources_before = conn.execute("SELECT count(*) FROM sources").fetchone()[0]
    files_before = sorted(
        path.relative_to(wiki_root) for path in wiki_root.rglob("*") if path.is_file()
    )

    def fail_urlopen(*_args: object, **_kwargs: object) -> object:
        raise urllib.error.HTTPError(
            "https://example.invalid/missing-404",
            404,
            "Not Found",
            hdrs=Message(),
            fp=None,
        )

    monkeypatch.setattr(pipeline.urllib.request, "urlopen", fail_urlopen)
    assert _run_cli(
        tmp_path,
        "ingest",
        "https://example.invalid/missing-404",
        "--wiki",
        "ai-tooling",
    ) == 1
    captured = capsys.readouterr()
    assert "failed to fetch URL" in captured.err
    assert "Traceback" not in captured.err
    assert _git(wiki_root, "rev-list", "--count", "HEAD").stdout.strip() == commits_before
    with sqlite3.connect(wiki_root / "wiki.db") as conn:
        assert conn.execute("SELECT count(*) FROM ingest_log").fetchone()[0] == logs_before
        assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == sources_before
    files_after = sorted(
        path.relative_to(wiki_root) for path in wiki_root.rglob("*") if path.is_file()
    )
    assert files_after == files_before
