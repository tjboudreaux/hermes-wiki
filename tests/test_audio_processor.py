"""Audio modality: transcript anchors, large-path streaming, fallbacks (PR3)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hermes_wiki import db, media, pipeline
from hermes_wiki.media_processors import AudioProcessor, audio_processor_or_none

REPO_ROOT = Path(__file__).resolve().parents[1]
TONE_WAV = REPO_ROOT / "evals" / "corpus" / "media" / "sources" / "speech-tone.wav"

FAKE_SEGMENTS = [
    (0.0, 4.2, "Welcome to the modular memory workshop."),
    (4.2, 9.8, "Today we compare retrieval strategies."),
    (65.0, 71.5, "Closing remarks and questions."),
]


def _fake_transcriber(calls: list[tuple[int, str, str]]):
    def transcribe(source_bytes: bytes, source_local_path: str, model_name: str):
        calls.append((len(source_bytes), source_local_path, model_name))
        return list(FAKE_SEGMENTS), "9.9.9-fake"

    return transcribe


def _with_env(tmp_path: Path, fn):
    merged = {"HERMES_HOME": str(tmp_path), "HERMES_WIKI": "ai-tooling", "USER": "aud-tester"}
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


def test_audio_ingest_writes_anchored_transcript(tmp_path: Path) -> None:
    wiki_root = _create_wiki(tmp_path)
    calls: list[tuple[int, str, str]] = []
    processor = AudioProcessor(transcribe=_fake_transcriber(calls))

    result = _with_env(
        tmp_path,
        lambda: pipeline.ingest_source(str(TONE_WAV), wiki="ai-tooling", processor=processor),
    )

    assert result.classified_as == "audio"
    assert calls and calls[0][2] == media.DEFAULT_TRANSCRIBE_MODEL
    assert calls[0][0] > 0 and calls[0][1] == ""  # small media arrives as bytes

    page_id = result.pages_created[0]
    stem = page_id.split("/")[-1]
    transcript = (wiki_root / "derived" / "audio" / stem / "transcript.md").read_text(
        encoding="utf-8"
    )
    assert "## [00:00:00]" in transcript
    assert "## [00:00:04]" in transcript
    assert "## [00:01:05]" in transcript  # D7 hh:mm:ss anchors
    assert "Welcome to the modular memory workshop." in transcript

    manifest = media.read_manifest(wiki_root / "derived" / "audio" / stem)
    assert manifest is not None
    assert manifest.tool == "faster-whisper"
    assert manifest.version == "9.9.9-fake"
    assert manifest.model_id == media.DEFAULT_TRANSCRIBE_MODEL
    assert manifest.details["segments"] == 3
    assert manifest.details["duration_seconds"] == 71.5

    page_text = (wiki_root / f"{page_id}.md").read_text(encoding="utf-8")
    assert "transcript.md" in page_text
    assert "Welcome to the modular memory workshop." in page_text  # summary
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        row = conn.execute("SELECT sources FROM pages WHERE id = ?", (page_id,)).fetchone()
    assert json.loads(row["sources"]) == [f"derived/audio/{stem}/manifest.json"]


def test_large_audio_reaches_transcriber_by_path(tmp_path: Path) -> None:
    """Two-tier originals stream by path; bytes stay empty (D4)."""

    _create_wiki(tmp_path)
    big = tmp_path / "talk.wav"
    big.write_bytes(b"RIFF\x24\x00\x00\x00WAVE")
    with big.open("r+b") as handle:
        handle.truncate(pipeline.MAX_INGEST_BYTES + 256)

    calls: list[tuple[int, str, str]] = []
    processor = AudioProcessor(transcribe=_fake_transcriber(calls))
    result = _with_env(
        tmp_path,
        lambda: pipeline.ingest_source(str(big), wiki="ai-tooling", processor=processor),
    )

    assert result.raw_snapshot.startswith("raw/large/")
    assert calls[0][0] == 0  # no bytes loaded
    assert calls[0][1].endswith("talk.wav")  # transcriber got the local path


def test_transcriber_failure_falls_back_to_stub(tmp_path: Path) -> None:
    wiki_root = _create_wiki(tmp_path)

    def exploding(source_bytes: bytes, source_local_path: str, model_name: str):
        raise RuntimeError("model download failed")

    processor = AudioProcessor(transcribe=exploding)
    result = _with_env(
        tmp_path,
        lambda: pipeline.ingest_source(str(TONE_WAV), wiki="ai-tooling", processor=processor),
    )

    page_text = (wiki_root / f"{result.pages_created[0]}.md").read_text(encoding="utf-8")
    assert "Binary media Source Snapshot" in page_text
    stem = result.pages_created[0].split("/")[-1]
    manifest = media.read_manifest(wiki_root / "derived" / "audio" / stem)
    assert manifest is not None and manifest.tool == "hermes-wiki.media-stub"


def test_missing_extra_disables_audio_processor(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util as iu

    real_find_spec = iu.find_spec
    monkeypatch.setattr(
        "hermes_wiki.media_processors.importlib.util.find_spec",
        lambda name: None if name == "faster_whisper" else real_find_spec(name),
    )
    assert audio_processor_or_none() is None


def test_configured_model_name_is_used_and_stamped(tmp_path: Path) -> None:
    wiki_root = _create_wiki(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "wiki:\n  media:\n    transcribe_model: tiny\n", encoding="utf-8"
    )
    calls: list[tuple[int, str, str]] = []
    processor = AudioProcessor(transcribe=_fake_transcriber(calls))

    result = _with_env(
        tmp_path,
        lambda: pipeline.ingest_source(str(TONE_WAV), wiki="ai-tooling", processor=processor),
    )

    assert calls[0][2] == "tiny"
    stem = result.pages_created[0].split("/")[-1]
    manifest = media.read_manifest(wiki_root / "derived" / "audio" / stem)
    assert manifest is not None and manifest.model_id == "tiny"
