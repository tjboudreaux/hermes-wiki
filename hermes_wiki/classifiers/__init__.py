"""Classifier chain for Hermes Wiki Source Snapshots."""

from __future__ import annotations

import importlib.util
import re
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from hermes_wiki import db, projection
from hermes_wiki.models import ClassLabel

ClassifierFn = Callable[[str, bytes], ClassLabel | None]


@dataclass(frozen=True, slots=True)
class BuiltinClassifier:
    """One deterministic built-in classifier in the declared precedence order."""

    name: str
    classify: ClassifierFn


def classify_source(name: str, content: bytes, *, wiki_root: Path | None = None) -> ClassLabel:
    """Classify bytes using built-ins first, trusted custom classifiers second, then unknown."""

    for classifier in BUILTIN_CLASSIFIERS:
        label = classifier.classify(name, content)
        if label is not None:
            return label

    if wiki_root is not None:
        custom_label = _classify_with_trusted_custom(wiki_root, name=name, content=content)
        if custom_label is not None:
            return custom_label

    return ClassLabel("unknown", "low", "fallback retained for review")


def _classify_article(name: str, content: bytes) -> ClassLabel | None:
    suffix = Path(name).suffix.lower()
    text = _decode_text(content)
    lowered = text.lower()
    has_heading = re.search(r"(?m)^#\s+\S+", text) is not None
    has_html_article = bool(re.search(r"(?is)<\s*(html|article|body)\b", text))
    article_markers = (
        "clipped article",
        "clipped html",
        "blog post",
        "from a blog",
        "newsletter",
        "published:",
        "byline",
        "## article",
    )
    has_article_language = re.search(r"\b(article|blog|newsletter)\b", lowered) is not None

    if suffix in {".html", ".htm"} and has_html_article:
        return ClassLabel("article", "high", "html/article structure")
    if suffix in {".md", ".markdown"} and (
        any(marker in lowered for marker in article_markers)
        or (has_heading and has_article_language)
    ):
        return ClassLabel("article", "medium", "clipped markdown/blog article")
    if has_html_article or any(marker in lowered for marker in article_markers):
        return ClassLabel("article", "medium", "clipped html/blog article")
    return None


def _classify_paper(name: str, content: bytes) -> ClassLabel | None:
    suffix = Path(name).suffix.lower()
    text = _decode_text(content)
    lowered = text.lower()
    has_pdf_marker = content.startswith(b"%PDF")
    has_doi = re.search(r"\bdoi\s*:\s*10\.\d{4,9}/\S+", lowered) is not None
    has_abstract = re.search(r"(?m)^abstract\b|[\n\r]abstract[\n\r]", lowered) is not None
    has_references = re.search(r"(?m)^(references|bibliography)\b", lowered) is not None
    has_numbered_sections = len(re.findall(r"(?m)^\d+\.\s+[A-Z]", text)) >= 2

    if suffix == ".pdf" and (has_pdf_marker or (has_doi and has_abstract)):
        return ClassLabel("paper", "high", "pdf academic structure")
    if has_doi and has_abstract and (has_references or has_numbered_sections):
        return ClassLabel("paper", "medium", "doi/abstract/references structure")
    return None


def _classify_transcript(name: str, content: bytes) -> ClassLabel | None:
    text = _decode_text(content)
    speaker_lines = _speaker_label_lines(text)
    if len(speaker_lines) >= 2:
        return ClassLabel("transcript", "high", "speaker-labeled transcript")
    if Path(name).suffix.lower() in {".vtt", ".srt"} and speaker_lines:
        return ClassLabel("transcript", "medium", "caption speaker labels")
    return None


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}
_VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


def _classify_image(name: str, content: bytes) -> ClassLabel | None:
    if (
        content.startswith(b"\x89PNG\r\n\x1a\n")
        or content.startswith(b"\xff\xd8\xff")
        or content.startswith((b"GIF87a", b"GIF89a"))
        or (content.startswith(b"RIFF") and content[8:12] == b"WEBP")
    ):
        return ClassLabel("image", "high", "image magic bytes")
    if Path(name).suffix.lower() in _IMAGE_SUFFIXES:
        return ClassLabel("image", "medium", "image file extension")
    return None


def _classify_audio(name: str, content: bytes) -> ClassLabel | None:
    if (
        (content.startswith(b"RIFF") and content[8:12] == b"WAVE")
        or content.startswith((b"fLaC", b"OggS", b"ID3"))
        or content[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}
        or (content[4:8] == b"ftyp" and content[8:11] == b"M4A")
    ):
        return ClassLabel("audio", "high", "audio magic bytes")
    if Path(name).suffix.lower() in _AUDIO_SUFFIXES:
        return ClassLabel("audio", "medium", "audio file extension")
    return None


def _classify_video(name: str, content: bytes) -> ClassLabel | None:
    # Runs after audio, so remaining ftyp brands (isom/mp42/qt …) are video.
    if content[4:8] == b"ftyp" or content.startswith(b"\x1aE\xdf\xa3"):
        return ClassLabel("video", "high", "video container magic bytes")
    if Path(name).suffix.lower() in _VIDEO_SUFFIXES:
        return ClassLabel("video", "medium", "video file extension")
    return None


BUILTIN_CLASSIFIERS: tuple[BuiltinClassifier, ...] = (
    BuiltinClassifier("article", _classify_article),
    BuiltinClassifier("paper", _classify_paper),
    BuiltinClassifier("transcript", _classify_transcript),
    BuiltinClassifier("image", _classify_image),
    BuiltinClassifier("audio", _classify_audio),
    BuiltinClassifier("video", _classify_video),
)


def _speaker_label_lines(text: str) -> list[str]:
    metadata_labels = {
        "abstract",
        "article",
        "author",
        "date",
        "doi",
        "published",
        "references",
        "source",
        "title",
    }
    labels: list[str] = []
    for match in re.finditer(r"(?m)^([A-Z][A-Za-z0-9 ._-]{0,30}):\s+\S", text):
        label = match.group(1).strip()
        if label.lower() in metadata_labels:
            continue
        if re.fullmatch(r"Speaker\s*\d+|[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}", label):
            labels.append(label)
    return labels


def _classify_with_trusted_custom(
    wiki_root: Path,
    *,
    name: str,
    content: bytes,
) -> ClassLabel | None:
    classifiers = list(_trusted_custom_classifiers(wiki_root))
    if not classifiers:
        return None
    safe_name = Path(name).name or "source"
    with tempfile.TemporaryDirectory(prefix="hermes-wiki-classify-") as temp_dir:
        source_path = Path(temp_dir) / safe_name
        source_path.write_bytes(content)
        for classifier_name, plugin_path in classifiers:
            result = _run_custom_classifier(classifier_name, plugin_path, source_path)
            if result is not None:
                return result
    return None


def _trusted_custom_classifiers(wiki_root: Path) -> Iterable[tuple[str, Path]]:
    wiki_db = wiki_root / "wiki.db"
    if not wiki_db.exists():
        return ()
    root = wiki_root.resolve()
    rows: list[dict[str, Any]]
    with db.connect_wiki(wiki_db) as conn:
        rows = [
            row
            for row in db.list_trusted_plugins(conn)
            if str(row.get("kind")) == "classifier"
        ]
    classifiers: list[tuple[str, Path, str]] = []
    for row in rows:
        plugin_path = (wiki_root / str(row.get("path") or "")).resolve()
        try:
            plugin_path.relative_to(root)
        except ValueError:
            continue
        if not plugin_path.is_file():
            continue
        if projection.sha256_file(plugin_path) != str(row.get("sha256") or ""):
            continue
        classifiers.append(
            (
                str(row.get("name") or plugin_path.stem),
                plugin_path,
                str(row.get("trusted_at") or ""),
            )
        )
    ordered = sorted(classifiers, key=lambda item: (item[2], item[0]))
    return tuple((name, path) for name, path, _trusted_at in ordered)


def _run_custom_classifier(
    classifier_name: str,
    plugin_path: Path,
    source_path: Path,
) -> ClassLabel | None:
    module = _load_plugin_module(classifier_name, plugin_path)
    classify = getattr(module, "classify", None)
    if not callable(classify):
        return None
    result = classify(source_path)
    if result is None:
        return None
    if isinstance(result, ClassLabel):
        return result
    if isinstance(result, str) and result.strip():
        return ClassLabel(result.strip(), "medium", f"trusted custom classifier {classifier_name}")
    return None


def _load_plugin_module(classifier_name: str, plugin_path: Path) -> ModuleType:
    digest = projection.sha256_file(plugin_path)[:16]
    module_name = f"hermes_wiki_trusted_classifier_{classifier_name}_{digest}"
    spec = importlib.util.spec_from_file_location(module_name, plugin_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load trusted classifier: {classifier_name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _decode_text(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")


__all__ = ["BUILTIN_CLASSIFIERS", "BuiltinClassifier", "classify_source"]
