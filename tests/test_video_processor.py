"""Video modality: keyframes, cap, transcript composition, fallbacks (PR4)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hermes_wiki import media, pipeline
from hermes_wiki.media_processors import VideoProcessor, video_processor_or_none

REPO_ROOT = Path(__file__).resolve().parents[1]
CLIP_MP4 = REPO_ROOT / "evals" / "corpus" / "media" / "sources" / "clip.mp4"

JPEG = b"\xff\xd8\xff\xe0fakejpegbytes"


def _fake_scene_detector(scene_count: int, calls: list[int] | None = None):
    def detect(source_bytes: bytes, source_local_path: str, limit: int):
        if calls is not None:
            calls.append(limit)
        frames = [(float(i * 10), JPEG + bytes([i % 256])) for i in range(scene_count)]
        return frames[:limit], "0.6.7-fake"

    return detect


def _fake_transcriber(segments):
    def transcribe(source_bytes: bytes, source_local_path: str, model_name: str):
        return list(segments), "9.9.9-fake"

    return transcribe


def _with_env(tmp_path: Path, fn):
    merged = {"HERMES_HOME": str(tmp_path), "HERMES_WIKI": "ai-tooling", "USER": "vid-tester"}
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


def test_video_ingest_writes_keyframes_and_transcript(tmp_path: Path) -> None:
    wiki_root = _create_wiki(tmp_path)
    processor = VideoProcessor(
        detect_scenes=_fake_scene_detector(3),
        transcribe=_fake_transcriber([(0.0, 5.0, "Scene one narration.")]),
    )

    result = _with_env(
        tmp_path,
        lambda: pipeline.ingest_source(str(CLIP_MP4), wiki="ai-tooling", processor=processor),
    )

    assert result.classified_as == "video"
    page_id = result.pages_created[0]
    stem = page_id.split("/")[-1]
    derived = wiki_root / "derived" / "video" / stem

    keyframes = sorted(path.name for path in (derived / "keyframes").iterdir())
    assert keyframes == [
        "scene-01-0000s.jpg",
        "scene-02-0010s.jpg",
        "scene-03-0020s.jpg",
    ]
    assert (derived / "keyframes" / keyframes[0]).read_bytes().startswith(b"\xff\xd8\xff")

    transcript = (derived / "transcript.md").read_text(encoding="utf-8")
    assert "## [00:00:00]" in transcript and "Scene one narration." in transcript

    manifest = media.read_manifest(derived)
    assert manifest is not None
    assert manifest.tool == "scenedetect"
    assert manifest.details["scenes"] == 3
    assert manifest.details["segments"] == 1
    assert "transcript.md" in manifest.details["artifacts"]
    assert any(name.startswith("keyframes/") for name in manifest.details["artifacts"])

    page_text = (wiki_root / f"{page_id}.md").read_text(encoding="utf-8")
    assert "Scene 1 @ 00:00:00" in page_text
    assert "Scene one narration." in page_text


def test_keyframe_cap_is_enforced_and_configurable(tmp_path: Path) -> None:
    wiki_root = _create_wiki(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "wiki:\n  media:\n    max_keyframes: 5\n", encoding="utf-8"
    )
    calls: list[int] = []
    processor = VideoProcessor(
        detect_scenes=_fake_scene_detector(50, calls),
        transcribe=_fake_transcriber([]),
    )

    result = _with_env(
        tmp_path,
        lambda: pipeline.ingest_source(str(CLIP_MP4), wiki="ai-tooling", processor=processor),
    )

    assert calls == [5]  # cap handed to the detector
    stem = result.pages_created[0].split("/")[-1]
    frames = list((wiki_root / "derived" / "video" / stem / "keyframes").iterdir())
    assert len(frames) == 5


def test_scene_detection_failure_falls_back_to_stub(tmp_path: Path) -> None:
    wiki_root = _create_wiki(tmp_path)

    def exploding(source_bytes: bytes, source_local_path: str, limit: int):
        raise RuntimeError("opencv failed to open container")

    processor = VideoProcessor(detect_scenes=exploding, transcribe=_fake_transcriber([]))
    result = _with_env(
        tmp_path,
        lambda: pipeline.ingest_source(str(CLIP_MP4), wiki="ai-tooling", processor=processor),
    )

    page_text = (wiki_root / f"{result.pages_created[0]}.md").read_text(encoding="utf-8")
    assert "Binary media Source Snapshot" in page_text


def test_transcription_failure_keeps_keyframes(tmp_path: Path) -> None:
    """A broken audio track must not cost the visual extraction."""

    wiki_root = _create_wiki(tmp_path)

    def exploding(source_bytes: bytes, source_local_path: str, model_name: str):
        raise RuntimeError("no audio track")

    processor = VideoProcessor(
        detect_scenes=_fake_scene_detector(2), transcribe=exploding
    )
    result = _with_env(
        tmp_path,
        lambda: pipeline.ingest_source(str(CLIP_MP4), wiki="ai-tooling", processor=processor),
    )

    stem = result.pages_created[0].split("/")[-1]
    derived = wiki_root / "derived" / "video" / stem
    assert len(list((derived / "keyframes").iterdir())) == 2
    transcript = (derived / "transcript.md").read_text(encoding="utf-8")
    assert "*(no speech detected)*" in transcript


def test_missing_extra_disables_video_processor(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util as iu

    real_find_spec = iu.find_spec
    monkeypatch.setattr(
        "hermes_wiki.media_processors.importlib.util.find_spec",
        lambda name: None if name in {"scenedetect", "cv2"} else real_find_spec(name),
    )
    assert video_processor_or_none() is None
