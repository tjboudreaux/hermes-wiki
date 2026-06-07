"""Media plumbing evals (CI lane, ``pytest -m eval``): classification,
manifests, storage tiering, and citation wiring over the committed corpus.

These run the REAL ingest pipeline over the media micro-corpus but involve no
extraction models — fully deterministic (D5 plumbing lane).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.harness import wiki_builder
from hermes_wiki import db, media

pytestmark = pytest.mark.eval

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS = REPO_ROOT / "evals" / "corpus" / "media"
GOLDEN = json.loads((CORPUS / "golden-fingerprints.json").read_text(encoding="utf-8"))
MEDIA_FILES = sorted(
    name for name, meta in GOLDEN.items() if meta["label"] in media.MEDIA_LABELS
)


def test_corpus_fingerprints_are_current() -> None:
    """Committed fixtures must match their golden sha256/size/label exactly."""

    import hashlib

    from hermes_wiki.classifiers import classify_source

    for name, meta in sorted(GOLDEN.items()):
        data = (CORPUS / "sources" / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == meta["sha256"], name
        assert len(data) == meta["size"], name
        assert classify_source(name, data).name == meta["label"], name


def test_corpus_stays_within_budget() -> None:
    total = sum((CORPUS / "sources" / name).stat().st_size for name in GOLDEN)
    assert total < 5 * 1024 * 1024, "media corpus exceeded its 5MB budget"


@pytest.mark.parametrize("name", MEDIA_FILES)
def test_media_corpus_ingest_plumbing(name: str, tmp_path: Path) -> None:
    """Each media fixture ingests into a stub page + manifest with golden sha."""

    home = tmp_path / "hermes-home"
    slug = "media-eval"
    wiki_builder.build_corpus_wiki(
        home,
        slug=slug,
        domain="media plumbing eval",
        sources=[CORPUS / "sources" / name],
    )
    wiki_root = home / "wikis" / slug
    meta = GOLDEN[name]

    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        pages = [dict(row) for row in conn.execute("SELECT id, type, sources FROM pages")]
        source_rows = [dict(row) for row in conn.execute("SELECT id, sha256 FROM sources")]

    # Exactly one stub source page; no derived concept/entity garbage.
    assert [page["type"] for page in pages] == ["source"]
    page = pages[0]
    stem = page["id"].split("/")[-1]
    manifest_rel = f"derived/{meta['label']}/{stem}/{media.MANIFEST_FILENAME}"
    assert json.loads(page["sources"]) == [manifest_rel]

    manifest = media.read_manifest(wiki_root / "derived" / meta["label"] / stem)
    assert manifest is not None
    assert manifest.input_sha256 == meta["sha256"]
    assert manifest.input_size == meta["size"]
    assert manifest.details["label"] == meta["label"]
    assert manifest.details["storage"] == "snapshot"  # corpus files are small

    # The sources table carries the same fingerprint.
    assert source_rows and source_rows[0]["sha256"] == meta["sha256"]
    # Snapshot landed in the tracked tree for small media.
    snapshot = source_rows[0]["id"]
    assert (wiki_root / snapshot).exists()
    assert not snapshot.startswith("raw/large/")


def test_pdf_extraction_matches_golden(tmp_path: Path) -> None:
    """pdfplumber extraction over the corpus PDF is pinned to a golden (PR1)."""

    home = tmp_path / "hermes-home"
    slug = "pdf-eval"
    wiki_builder.build_corpus_wiki(
        home,
        slug=slug,
        domain="pdf extraction eval",
        sources=[CORPUS / "sources" / "two-page.pdf"],
    )
    wiki_root = home / "wikis" / slug
    derived = sorted((wiki_root / "derived" / "pdf").iterdir())
    assert len(derived) == 1
    actual = (derived[0] / "extracted.md").read_text(encoding="utf-8")
    golden = (CORPUS / "golden" / "two-page.extracted.md").read_text(encoding="utf-8")
    # Title line carries the ingest-derived name; the page content is pinned.
    assert actual.splitlines()[2:] == golden.splitlines()[2:]
    manifest = media.read_manifest(derived[0])
    assert manifest is not None and manifest.tool == "pdfplumber"
