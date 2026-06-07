"""Built-in image/audio/video classifiers (magic bytes + extension fallback)."""

from __future__ import annotations

import pytest

from hermes_wiki.classifiers import classify_source

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
GIF = b"GIF89a" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 64
WAV = b"RIFF\x24\x00\x00\x00WAVE" + b"\x00" * 64
FLAC = b"fLaC" + b"\x00" * 64
OGG = b"OggS" + b"\x00" * 64
MP3_ID3 = b"ID3\x04" + b"\x00" * 64
MP3_FRAME = b"\xff\xfb\x90\x00" + b"\x00" * 64
M4A = b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 64
MP4 = b"\x00\x00\x00\x20ftypisom" + b"\x00" * 64
MOV = b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 64
WEBM = b"\x1aE\xdf\xa3" + b"\x00" * 64


@pytest.mark.parametrize(
    ("name", "content", "label"),
    [
        ("shot.png", PNG, "image"),
        ("photo.bin", JPEG, "image"),  # magic wins without a known extension
        ("anim.gif", GIF, "image"),
        ("pic.webp", WEBP, "image"),
        ("talk.wav", WAV, "audio"),
        ("song.bin", FLAC, "audio"),
        ("cast.ogg", OGG, "audio"),
        ("tagged.mp3", MP3_ID3, "audio"),
        ("frame.bin", MP3_FRAME, "audio"),
        ("voice.m4a", M4A, "audio"),  # M4A brand stays audio, not video
        ("clip.mp4", MP4, "video"),
        ("clip.bin", MOV, "video"),
        ("clip.webm", WEBM, "video"),
    ],
)
def test_magic_bytes_classify_high_confidence(name: str, content: bytes, label: str) -> None:
    result = classify_source(name, content)
    assert result.name == label
    assert result.confidence == "high"


@pytest.mark.parametrize(
    ("name", "label"),
    [
        ("shot.jpeg", "image"),
        ("song.mp3", "audio"),
        ("clip.mov", "video"),
    ],
)
def test_extension_fallback_is_medium_confidence(name: str, label: str) -> None:
    result = classify_source(name, b"\x00\x01\x02\x03 unrecognizable bytes")
    assert result.name == label
    assert result.confidence == "medium"


def test_existing_text_labels_keep_precedence() -> None:
    pdf = b"%PDF-1.7\n" + b"\x00" * 64
    assert classify_source("paper.pdf", pdf).name == "paper"

    article = b"# Heading\n\nPublished: 2026-01-01\n\nBody text."
    assert classify_source("post.md", article).name == "article"

    transcript = b"Alice: hello there\nBob: hi Alice\n"
    assert classify_source("chat.txt", transcript).name == "transcript"


def test_unmatched_bytes_remain_unknown() -> None:
    result = classify_source("mystery.dat", b"\x00\x01\x02\x03\x04")
    assert result.name == "unknown"
