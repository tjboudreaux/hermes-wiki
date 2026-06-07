"""Real-extraction media evals (``pytest -m eval_media`` — weekly lane, D5).

Extraction gates (WER/DER/scene-count/page edit-distance) land with their
modality phases. This module keeps the lane non-empty from day one with a
corpus-integrity gate so weekly runs catch fixture drift immediately.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.eval_media

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS = REPO_ROOT / "evals" / "corpus" / "media"


def test_media_corpus_integrity() -> None:
    golden = json.loads((CORPUS / "golden-fingerprints.json").read_text(encoding="utf-8"))
    assert golden, "media corpus golden fingerprints missing"
    for name, meta in sorted(golden.items()):
        data = (CORPUS / "sources" / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == meta["sha256"], f"fixture drifted: {name}"


def test_pdf_extraction_gate() -> None:
    """Weekly lane: extraction of the corpus PDF stays byte-stable (PR1)."""

    import io

    import pdfplumber

    data = (CORPUS / "sources" / "two-page.pdf").read_bytes()
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = [(page.extract_text() or "").strip() for page in pdf.pages]
    assert pages == [
        "Corpus Page One: modular memory",
        "Corpus Page Two: retrieval table",
    ]


def test_image_metadata_extraction_gate() -> None:
    """Weekly lane: Pillow metadata for the corpus chart stays stable (PR2)."""

    import io

    from PIL import Image

    data = (CORPUS / "sources" / "chart.png").read_bytes()
    with Image.open(io.BytesIO(data)) as img:
        assert img.size == (64, 64)
        assert str(img.format).lower() == "png"


def test_audio_transcription_smoke_gate(tmp_path: Path) -> None:
    """Weekly lane: real faster-whisper (tiny) runs end-to-end over the corpus.

    The corpus tone has no speech, so this gates the transcription *path*
    (model load, decode, artifact shape) rather than WER. A WER threshold gate
    lands when a properly-licensed CC0 speech fixture is added (LICENSES.md).
    """

    pytest.importorskip("faster_whisper")

    import os

    from hermes_wiki import media, pipeline
    from hermes_wiki_cli.cli import main

    merged = {"HERMES_HOME": str(tmp_path), "HERMES_WIKI": "media-eval", "USER": "eval"}
    old = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(merged)
        (tmp_path / "config.yaml").write_text(
            "wiki:\n  media:\n    transcribe_model: tiny\n", encoding="utf-8"
        )
        assert main(["create", "media-eval"]) == 0
        result = pipeline.ingest_source(
            str(CORPUS / "sources" / "speech-tone.wav"), wiki="media-eval"
        )
    finally:
        os.environ.clear()
        os.environ.update(old)

    wiki_root = tmp_path / "wikis" / "media-eval"
    stem = result.pages_created[0].split("/")[-1]
    manifest = media.read_manifest(wiki_root / "derived" / "audio" / stem)
    assert manifest is not None
    assert manifest.tool == "faster-whisper"
    assert manifest.model_id == "tiny"
    transcript = (wiki_root / "derived" / "audio" / stem / "transcript.md").read_text(
        encoding="utf-8"
    )
    assert transcript.startswith("# Transcript:")
