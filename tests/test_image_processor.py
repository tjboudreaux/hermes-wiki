"""Image modality: Pillow metadata, best-effort OCR, fallbacks (design PR2)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hermes_wiki import db, media, pipeline
from hermes_wiki.media_processors import image_processor_or_none

REPO_ROOT = Path(__file__).resolve().parents[1]
CHART_PNG = REPO_ROOT / "evals" / "corpus" / "media" / "sources" / "chart.png"


def _with_env(tmp_path: Path, fn):
    merged = {"HERMES_HOME": str(tmp_path), "HERMES_WIKI": "ai-tooling", "USER": "img-tester"}
    old = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(merged)
        return fn()
    finally:
        os.environ.clear()
        os.environ.update(old)


def _create_wiki(tmp_path: Path) -> Path:
    from hermes_wiki_cli.cli import main

    assert _with_env(tmp_path, lambda: main(["create", "ai-tooling"])) == 0
    return tmp_path / "wikis" / "ai-tooling"


def test_image_ingest_extracts_metadata_and_embeds(tmp_path: Path) -> None:
    wiki_root = _create_wiki(tmp_path)

    result = _with_env(
        tmp_path, lambda: pipeline.ingest_source(str(CHART_PNG), wiki="ai-tooling")
    )

    assert result.classified_as == "image"
    assert len(result.pages_created) == 1
    page_id = result.pages_created[0]
    stem = page_id.split("/")[-1]

    metadata_md = (wiki_root / "derived" / "image" / stem / "metadata.md").read_text(
        encoding="utf-8"
    )
    assert "- width: 64" in metadata_md
    assert "- height: 64" in metadata_md
    assert "- format: png" in metadata_md

    manifest = media.read_manifest(wiki_root / "derived" / "image" / stem)
    assert manifest is not None
    assert manifest.tool == "pillow"
    assert manifest.details["width"] == 64
    assert manifest.details["height"] == 64
    assert manifest.details["format"] == "png"
    assert "metadata.md" in manifest.details["artifacts"]

    page_text = (wiki_root / f"{page_id}.md").read_text(encoding="utf-8")
    assert "![" in page_text and result.raw_snapshot in page_text  # embedded evidence
    assert "Dimensions: 64x64 (png)" in page_text

    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        row = conn.execute("SELECT sources FROM pages WHERE id = ?", (page_id,)).fetchone()
    assert json.loads(row["sources"]) == [f"derived/image/{stem}/manifest.json"]


def test_corrupt_image_falls_back_to_stub(tmp_path: Path) -> None:
    """PNG magic with garbage body degrades to the provenance stub page."""

    wiki_root = _create_wiki(tmp_path)
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\xff" * 64)

    result = _with_env(tmp_path, lambda: pipeline.ingest_source(str(bad), wiki="ai-tooling"))

    assert result.classified_as == "image"
    page_id = result.pages_created[0]
    page_text = (wiki_root / f"{page_id}.md").read_text(encoding="utf-8")
    assert "Binary media Source Snapshot" in page_text  # stub body
    stem = page_id.split("/")[-1]
    manifest = media.read_manifest(wiki_root / "derived" / "image" / stem)
    assert manifest is not None and manifest.tool == "hermes-wiki.media-stub"


def test_missing_pillow_disables_image_processor(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util as iu

    real_find_spec = iu.find_spec
    monkeypatch.setattr(
        "hermes_wiki.media_processors.importlib.util.find_spec",
        lambda name: None if name == "PIL" else real_find_spec(name),
    )
    assert image_processor_or_none() is None
