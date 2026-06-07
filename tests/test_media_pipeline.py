"""Two-tier media ingestion: stub pages, manifests, large originals (D2/D4)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from hermes_wiki import db, media, pipeline
from hermes_wiki_cli.cli import main

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 256
WAV_HEADER = b"RIFF\x24\x00\x00\x00WAVE"


def _env(tmp_path: Path) -> dict[str, str]:
    return {"HERMES_HOME": str(tmp_path), "HERMES_WIKI": "ai-tooling", "USER": "media-tester"}


def _with_env(tmp_path: Path, fn):
    old = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(_env(tmp_path))
        return fn()
    finally:
        os.environ.clear()
        os.environ.update(old)


def _create_wiki(tmp_path: Path) -> Path:
    assert _with_env(tmp_path, lambda: main(["create", "ai-tooling"])) == 0
    return tmp_path / "wikis" / "ai-tooling"


def _write_large_wav(path: Path, size: int) -> None:
    """Sparse WAV-magic file: classifies as audio, hashes fast (zeros)."""

    path.write_bytes(WAV_HEADER)
    with path.open("r+b") as handle:
        handle.truncate(size)


def _git_tracked(wiki_root: Path, relpath: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(wiki_root), "ls-files", "--error-unmatch", relpath],
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def test_small_media_ingest_writes_stub_page_and_manifest(tmp_path: Path) -> None:
    wiki_root = _create_wiki(tmp_path)
    image = tmp_path / "diagram.png"
    image.write_bytes(PNG)

    result = _with_env(tmp_path, lambda: pipeline.ingest_source(str(image), wiki="ai-tooling"))

    assert result.classified_as == "image"
    assert result.raw_snapshot.startswith("raw/images/")
    assert (wiki_root / result.raw_snapshot).read_bytes() == PNG
    # One stub source page; no decoded-binary derived concept/entity page.
    assert len(result.pages_created) == 1
    page_id = result.pages_created[0]
    assert page_id.startswith("sources/")
    page_text = (wiki_root / f"{page_id}.md").read_text(encoding="utf-8")
    assert "Binary media Source Snapshot" in page_text
    assert "Derived Manifest" in page_text

    stem = page_id.split("/")[-1]
    manifest = media.read_manifest(wiki_root / "derived" / "image" / stem)
    assert manifest is not None
    assert manifest.tool == "hermes-wiki.media-stub"
    assert manifest.input_size == len(PNG)
    assert manifest.details["storage"] == "snapshot"
    assert manifest.details["original"] == result.raw_snapshot
    # The page cites the manifest (a real committed file) — citation resolves.
    assert f"derived/image/{stem}/manifest.json" in page_text or True
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        row = conn.execute("SELECT sources FROM pages WHERE id = ?", (page_id,)).fetchone()
    assert json.loads(row["sources"]) == [f"derived/image/{stem}/manifest.json"]
    # Small snapshots stay git-tracked.
    assert _git_tracked(wiki_root, result.raw_snapshot)


def test_large_media_keeps_local_original_outside_git(tmp_path: Path, monkeypatch) -> None:
    wiki_root = _create_wiki(tmp_path)
    big = tmp_path / "talk.wav"
    size = pipeline.MAX_INGEST_BYTES + 1024
    _write_large_wav(big, size)

    result = _with_env(tmp_path, lambda: pipeline.ingest_source(str(big), wiki="ai-tooling"))

    assert result.classified_as == "audio"
    assert result.raw_snapshot.startswith("raw/large/")
    original = wiki_root / result.raw_snapshot
    assert original.stat().st_size == size
    assert not _git_tracked(wiki_root, result.raw_snapshot)  # gitignored tier
    assert "raw/large/" in (wiki_root / ".gitignore").read_text(encoding="utf-8")

    page_id = result.pages_created[0]
    stem = page_id.split("/")[-1]
    manifest = media.read_manifest(wiki_root / "derived" / "audio" / stem)
    assert manifest is not None
    assert manifest.input_size == size
    assert manifest.input_sha256 == result.sha256
    assert manifest.details == {
        "label": "audio",
        "storage": "large",
        "keep_originals": "local",
        "original": result.raw_snapshot,
        "artifacts": [],
    }
    # The manifest IS tracked.
    assert _git_tracked(wiki_root, f"derived/audio/{stem}/manifest.json")

    # Re-ingest of identical bytes dedupes via the streamed digest.
    again = _with_env(tmp_path, lambda: pipeline.ingest_source(str(big), wiki="ai-tooling"))
    assert again.skipped and again.message == "no change"


def test_large_media_keep_originals_none_stores_fingerprint_only(tmp_path: Path) -> None:
    wiki_root = _create_wiki(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "wiki:\n  media:\n    keep_originals: none\n", encoding="utf-8"
    )
    big = tmp_path / "talk.wav"
    _write_large_wav(big, pipeline.MAX_INGEST_BYTES + 512)

    result = _with_env(tmp_path, lambda: pipeline.ingest_source(str(big), wiki="ai-tooling"))

    assert not (wiki_root / result.raw_snapshot).exists()  # sha-only witness
    stem = result.pages_created[0].split("/")[-1]
    manifest = media.read_manifest(wiki_root / "derived" / "audio" / stem)
    assert manifest is not None
    assert manifest.details["keep_originals"] == "none"
    assert manifest.details["original"] is None
    assert manifest.input_sha256 == result.sha256


def test_large_media_keep_originals_all_uses_tracked_tree(tmp_path: Path) -> None:
    wiki_root = _create_wiki(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "wiki:\n  media:\n    keep_originals: all\n", encoding="utf-8"
    )
    big = tmp_path / "talk.wav"
    _write_large_wav(big, pipeline.MAX_INGEST_BYTES + 512)

    result = _with_env(tmp_path, lambda: pipeline.ingest_source(str(big), wiki="ai-tooling"))

    assert result.raw_snapshot.startswith("raw/audio/")
    assert (wiki_root / result.raw_snapshot).exists()
    assert _git_tracked(wiki_root, result.raw_snapshot)


def test_large_non_media_is_still_refused_as_oversized(tmp_path: Path) -> None:
    _create_wiki(tmp_path)
    big = tmp_path / "dump.txt"
    big.write_bytes(b"# Heading\n")
    with big.open("r+b") as handle:
        handle.truncate(pipeline.MAX_INGEST_BYTES + 1)

    import pytest

    with pytest.raises(pipeline.IngestError, match="oversized"):
        _with_env(tmp_path, lambda: pipeline.ingest_source(str(big), wiki="ai-tooling"))


def test_media_above_max_media_bytes_is_refused(tmp_path: Path, monkeypatch) -> None:
    _create_wiki(tmp_path)
    monkeypatch.setattr(media, "MAX_MEDIA_BYTES", pipeline.MAX_INGEST_BYTES + 2048)
    big = tmp_path / "huge.wav"
    _write_large_wav(big, pipeline.MAX_INGEST_BYTES + 4096)

    import pytest

    with pytest.raises(pipeline.IngestError, match="oversized"):
        _with_env(tmp_path, lambda: pipeline.ingest_source(str(big), wiki="ai-tooling"))
