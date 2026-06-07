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
