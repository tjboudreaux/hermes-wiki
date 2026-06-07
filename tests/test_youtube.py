"""YouTube modality: notes default, captions opt-in, policy gates (PR6)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from hermes_wiki import pipeline, social, youtube
from hermes_wiki.youtube import (
    _parse_vtt,
    match_youtube_url,
)

WATCH_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
OEMBED = {
    "title": "Modular Memory: A Field Guide",
    "author_name": "Hermes Research",
    "author_url": "https://www.youtube.com/@hermesresearch",
    "type": "video",
}


def _fake_oembed_fetch(url: str) -> dict[str, Any]:
    assert "youtube.com/oembed" in url
    return dict(OEMBED)


def _with_env(tmp_path: Path, fn):
    merged = {"HERMES_HOME": str(tmp_path), "HERMES_WIKI": "ai-tooling", "USER": "yt-tester"}
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


@pytest.fixture(autouse=True)
def _patched_oembed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(social, "_default_fetch_json", _fake_oembed_fetch)


@pytest.mark.parametrize(
    ("url", "video_id"),
    [
        (WATCH_URL, "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?t=42", "dQw4w9WgXcQ"),
        ("https://m.youtube.com/watch?app=desktop&v=abc123def45", "abc123def45"),
        ("https://www.youtube.com/shorts/abc123def45", "abc123def45"),
        ("https://example.com/watch?v=abc123def45", None),
        ("https://www.youtube.com/@hermesresearch", None),
    ],
)
def test_match_youtube_url(url: str, video_id: str | None) -> None:
    assert match_youtube_url(url) == video_id


def test_notes_mode_snapshots_metadata_only(tmp_path: Path) -> None:
    """Default mode: oEmbed citation metadata + watch-and-note page (D8)."""

    wiki_root = _create_wiki(tmp_path)

    result = _with_env(tmp_path, lambda: pipeline.ingest_source(WATCH_URL, wiki="ai-tooling"))

    assert result.classified_as == "youtube"
    assert result.raw_snapshot.startswith("raw/youtube/")
    snapshot = json.loads((wiki_root / result.raw_snapshot).read_text(encoding="utf-8"))
    assert snapshot == OEMBED  # metadata only — never content

    page_id = result.pages_created[0]
    page_text = (wiki_root / f"{page_id}.md").read_text(encoding="utf-8")
    assert "Modular Memory: A Field Guide" in page_text
    assert "Hermes Research" in page_text
    assert "watch-and-note" in page_text
    assert "&t=754s" in page_text  # the to-YouTube anchor convention is taught
    # No derived transcript in notes mode.
    stem = page_id.split("/")[-1]
    assert not (wiki_root / "derived" / "youtube" / stem / "transcript.md").exists()


def test_captions_mode_requires_the_extra(tmp_path: Path, monkeypatch) -> None:
    """Opt-in without yt-dlp fails loud with the install hint (D8b)."""

    _create_wiki(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "wiki:\n  media:\n    youtube: captions\n", encoding="utf-8"
    )
    monkeypatch.setattr(youtube, "default_caption_fetcher_or_none", lambda: None)

    with pytest.raises(pipeline.IngestError, match=r"hermes-wiki\[youtube\]"):
        _with_env(tmp_path, lambda: pipeline.ingest_source(WATCH_URL, wiki="ai-tooling"))


def test_captions_mode_writes_provenance_stamped_transcript(
    tmp_path: Path, monkeypatch
) -> None:
    wiki_root = _create_wiki(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "wiki:\n  media:\n    youtube: captions\n", encoding="utf-8"
    )

    def fake_fetcher(url: str):
        assert url == WATCH_URL
        return (
            [(0.0, 4.0, "Welcome to the field guide."), (4.0, 9.0, "Memory compounds.")],
            {"retrieval": "yt-dlp", "language": "en", "kind": "manual",
             "tool_version": "2026.06.01-fake"},
        )

    monkeypatch.setattr(youtube, "default_caption_fetcher_or_none", lambda: fake_fetcher)

    result = _with_env(tmp_path, lambda: pipeline.ingest_source(WATCH_URL, wiki="ai-tooling"))

    page_id = result.pages_created[0]
    stem = page_id.split("/")[-1]
    derived = wiki_root / "derived" / "youtube" / stem
    transcript = (derived / "transcript.md").read_text(encoding="utf-8")
    assert "## [00:00:00]" in transcript and "Memory compounds." in transcript

    from hermes_wiki import media

    manifest = media.read_manifest(derived)
    assert manifest is not None
    assert manifest.tool == "yt-dlp"
    assert manifest.version == "2026.06.01-fake"
    assert manifest.details["retrieval"] == "yt-dlp"
    assert manifest.details["language"] == "en"
    assert manifest.details["kind"] == "manual"

    page_text = (wiki_root / f"{page_id}.md").read_text(encoding="utf-8")
    assert "captions fetched to" in page_text
    assert "operator-enabled" in page_text


def test_vtt_parser_extracts_timed_segments() -> None:
    payload = "\n".join(
        [
            "WEBVTT",
            "",
            "1",
            "00:00:01.000 --> 00:00:04.500",
            "Hello <b>world</b>",
            "",
            "00:01:02.250 --> 00:01:05.000",
            "Second line",
            "continues here",
            "",
        ]
    )
    segments = _parse_vtt(payload)
    assert segments == [
        (1.0, 4.5, "Hello world"),
        (62.25, 65.0, "Second line continues here"),
    ]
