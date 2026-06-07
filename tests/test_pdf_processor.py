"""PDF modality: extraction artifacts, page anchors, fallbacks (design PR1)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hermes_wiki import db, media, pipeline
from hermes_wiki.media_processors import pdf_processor_or_none
from hermes_wiki_cli.cli import main

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_PDF = REPO_ROOT / "evals" / "corpus" / "media" / "sources" / "two-page.pdf"
FAKE_PDF = REPO_ROOT / "fixtures" / "sources" / "agent-systems-paper.pdf"


def _with_env(tmp_path: Path, fn):
    merged = {"HERMES_HOME": str(tmp_path), "HERMES_WIKI": "ai-tooling", "USER": "pdf-tester"}
    old = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(merged)
        return fn()
    finally:
        os.environ.clear()
        os.environ.update(old)


def _create_wiki(tmp_path: Path) -> Path:
    assert _with_env(tmp_path, lambda: main(["create", "ai-tooling"])) == 0
    return tmp_path / "wikis" / "ai-tooling"


def test_real_pdf_extracts_pages_with_anchor_headings(tmp_path: Path) -> None:
    wiki_root = _create_wiki(tmp_path)

    result = _with_env(
        tmp_path, lambda: pipeline.ingest_source(str(CORPUS_PDF), wiki="ai-tooling")
    )

    assert result.classified_as == "paper"
    assert len(result.pages_created) == 1  # extraction replaces the derived stub page
    page_id = result.pages_created[0]
    stem = page_id.split("/")[-1]

    extraction = wiki_root / "derived" / "pdf" / stem / "extracted.md"
    text = extraction.read_text(encoding="utf-8")
    assert "## Page 1" in text and "## Page 2" in text  # D7 anchors
    assert "Corpus Page One: modular memory" in text
    assert "Corpus Page Two: retrieval table" in text

    manifest = media.read_manifest(extraction.parent)
    assert manifest is not None
    assert manifest.tool == "pdfplumber"
    assert manifest.version  # pinned extra version stamped
    assert manifest.details["pages"] == 2
    assert manifest.details["artifacts"] == ["extracted.md"]

    page_text = (wiki_root / f"{page_id}.md").read_text(encoding="utf-8")
    assert f"(../derived/pdf/{stem}/extracted.md)" in page_text
    assert "#page-1" in page_text and "#page-2" in page_text
    assert "Corpus Page One: modular memory" in page_text  # summary

    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        row = conn.execute("SELECT sources FROM pages WHERE id = ?", (page_id,)).fetchone()
    assert json.loads(row["sources"]) == [f"derived/pdf/{stem}/manifest.json"]


def test_unparseable_pdf_falls_back_to_default_processor(tmp_path: Path) -> None:
    """Text files wearing a %PDF header keep their pre-PR1 behavior exactly."""

    wiki_root = _create_wiki(tmp_path)

    result = _with_env(
        tmp_path, lambda: pipeline.ingest_source(str(FAKE_PDF), wiki="ai-tooling")
    )

    assert result.classified_as == "paper"
    assert len(result.pages_created) == 2  # Default's source + derived pages
    stem = result.pages_created[0].split("/")[-1]
    assert not (wiki_root / "derived" / "pdf" / stem).exists()  # no artifacts, no manifest


def test_missing_extra_disables_pdf_processor(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util as iu

    real_find_spec = iu.find_spec
    monkeypatch.setattr(
        "hermes_wiki.media_processors.importlib.util.find_spec",
        lambda name: None if name == "pdfplumber" else real_find_spec(name),
    )
    assert pdf_processor_or_none() is None


def test_artifact_escape_is_rejected(tmp_path: Path) -> None:
    """Derived artifacts may not write outside their derived directory."""

    _create_wiki(tmp_path)

    class EscapingProcessor:
        def process(self, request: pipeline.ProcessRequest):
            return [
                pipeline.DerivedArtifact(
                    relpath="../../evil.md", content="x", tool="t", version="1"
                ),
                pipeline.GeneratedPage(
                    pipeline.WikiPage(
                        id=request.source_page_id,
                        title=request.title,
                        type="source",
                        body="escape attempt",
                        sources=(request.snapshot_relpath,),
                    )
                ),
            ]

    with pytest.raises(pipeline.IngestError, match="escapes"):
        _with_env(
            tmp_path,
            lambda: pipeline.ingest_source(
                str(CORPUS_PDF), wiki="ai-tooling", processor=EscapingProcessor()
            ),
        )
