"""Modality extraction processors (media design PR1+).

Extraction runs in version-stamped processors (design D1): the tool and its
version land in the derived manifest; pages cite the manifest, and citations
into the extraction use stable headings (design D7).
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import io
from collections.abc import Callable
from typing import Any

from hermes_wiki import media
from hermes_wiki.models import WikiPage
from hermes_wiki.pipeline import (
    DefaultProcessor,
    DerivedArtifact,
    GeneratedPage,
    ProcessRequest,
)

PDF_TOOL = "pdfplumber"
IMAGE_TOOL = "pillow"
AUDIO_TOOL = "faster-whisper"

#: (start_seconds, end_seconds, text) transcription segments.
TranscriptSegments = list[tuple[float, float, str]]


def audio_processor_or_none() -> AudioProcessor | None:
    """Return the audio processor when faster-whisper is installed (D3)."""

    if importlib.util.find_spec("faster_whisper") is None:
        return None
    return AudioProcessor()


def _default_transcribe(
    source_bytes: bytes,
    source_local_path: str,
    model_name: str,
) -> tuple[TranscriptSegments, str]:
    """faster-whisper CPU transcription (int8, greedy) over bytes or a path."""

    from faster_whisper import WhisperModel  # ty: ignore[unresolved-import]

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    audio: Any = source_local_path if source_local_path else io.BytesIO(source_bytes)
    raw_segments, _info = model.transcribe(audio, beam_size=1, temperature=0.0)
    segments: TranscriptSegments = [
        (float(segment.start), float(segment.end), str(segment.text).strip())
        for segment in raw_segments
    ]
    return segments, importlib.metadata.version("faster-whisper")


class AudioProcessor:
    """Whisper-family transcription for ``audio`` sources (design PR3).

    Produces ``transcript.md`` with ``## [hh:mm:ss]`` anchor headings (D7) and
    a source page citing the manifest. The transcriber is injectable so unit
    tests and extractor-replay evals stay deterministic; the default uses
    faster-whisper (CPU/int8, greedy) with the model name from
    ``wiki.media.transcribe_model`` stamped into the manifest as model_id.
    Diarization (speaker labels, DER gates) is the documented
    ``[audio-diarize]`` upgrade path.
    """

    def __init__(
        self,
        transcribe: Callable[[bytes, str, str], tuple[TranscriptSegments, str]] | None = None,
    ) -> None:
        self._transcribe = transcribe or _default_transcribe

    def process(self, request: ProcessRequest) -> list[GeneratedPage | DerivedArtifact]:
        from hermes_wiki.pipeline import MediaStubProcessor, _media_settings

        model_name = media.transcribe_model(_media_settings())
        try:
            segments, version = self._transcribe(
                request.source_bytes, request.source_local_path, model_name
            )
        except Exception:
            return MediaStubProcessor().process(request)

        duration = segments[-1][1] if segments else 0.0
        source_page = WikiPage(
            id=request.source_page_id,
            title=request.title,
            type="source",
            body=_audio_source_body(request, segments, duration),
            tags=("ingest", request.label.name),
            sources=(request.manifest_relpath or request.snapshot_relpath,),
            confidence=request.label.confidence,
        )
        return [
            DerivedArtifact(
                relpath="transcript.md",
                content=_render_transcript(request.title, model_name, segments),
                tool=AUDIO_TOOL,
                version=version,
                model_id=model_name,
                details={
                    "segments": len(segments),
                    "duration_seconds": round(duration, 2),
                },
            ),
            GeneratedPage(source_page),
        ]


def _timestamp(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def _render_transcript(title: str, model_name: str, segments: TranscriptSegments) -> str:
    """Render the transcript with ``## [hh:mm:ss]`` anchor headings (D7)."""

    lines = [f"# Transcript: {title}", "", f"- Model: {AUDIO_TOOL} {model_name}", ""]
    if not segments:
        lines.extend(["*(no speech detected)*", ""])
    for start, _end, text in segments:
        lines.extend([f"## [{_timestamp(start)}]", "", text or "*(inaudible)*", ""])
    return "\n".join(lines).rstrip() + "\n"


def _audio_source_body(
    request: ProcessRequest,
    segments: TranscriptSegments,
    duration: float,
) -> str:
    base = request.manifest_relpath.rsplit("/", 1)[0] if request.manifest_relpath else ""
    transcript_rel = f"{base}/transcript.md" if base else "transcript.md"
    summary = next((text for _start, _end, text in segments if text), "")
    summary = " ".join(summary.split())[:280]
    lines = [
        f"# {request.title}",
        "",
        f"Audio source; transcribed to [transcript.md](../{transcript_rel}) "
        f"({len(segments)} segments, ~{_timestamp(duration)}).",
        "",
        f"- Classification: `{request.label.name}` ({request.label.confidence})",
    ]
    if request.manifest_relpath:
        lines.append(f"- Provenance: [Derived Manifest](../{request.manifest_relpath})")
    lines.append(
        "- Cite moments via transcript anchors: "
        f"`([source @ mm:ss](../{transcript_rel}#hhmmss))`"
    )
    if summary:
        lines.extend(["", summary])
    return "\n".join(lines)


def image_processor_or_none() -> ImageProcessor | None:
    """Return the image processor when Pillow is installed (D3 fallback)."""

    if importlib.util.find_spec("PIL") is None:
        return None
    return ImageProcessor()


class ImageProcessor:
    """Pillow metadata extraction (+ best-effort OCR) for ``image`` sources.

    Extraction is mechanical (D1): dimensions, format, and EXIF timestamps go
    into ``metadata.md`` and the manifest; OCR text lands in ``ocr.md`` when
    pytesseract + the tesseract binary are available (silently skipped
    otherwise — captioning is agent-side interpretation, never done here).
    Unreadable images fall back to the media stub page.
    """

    def process(self, request: ProcessRequest) -> list[GeneratedPage | DerivedArtifact]:
        try:
            import PIL
            from PIL import ExifTags, Image
        except ImportError:  # pragma: no cover - guarded by image_processor_or_none
            from hermes_wiki.pipeline import MediaStubProcessor

            return MediaStubProcessor().process(request)

        try:
            with Image.open(io.BytesIO(request.source_bytes)) as img:
                width, height = img.size
                image_format = str(img.format or "unknown").lower()
                exif_datetime = _exif_datetime(img, ExifTags)
        except Exception:
            from hermes_wiki.pipeline import MediaStubProcessor

            return MediaStubProcessor().process(request)

        version = PIL.__version__
        details: dict[str, object] = {
            "width": width,
            "height": height,
            "format": image_format,
        }
        if exif_datetime:
            details["exif_datetime"] = exif_datetime

        artifacts: list[DerivedArtifact] = [
            DerivedArtifact(
                relpath="metadata.md",
                content=_render_image_metadata(request.title, details),
                tool=IMAGE_TOOL,
                version=version,
                details=details,
            )
        ]
        ocr_text = _best_effort_ocr(request.source_bytes)
        if ocr_text:
            artifacts.append(
                DerivedArtifact(
                    relpath="ocr.md",
                    content=f"# OCR: {request.title}\n\n{ocr_text}\n",
                    tool="pytesseract",
                    version=version,
                    details={"ocr": True},
                )
            )

        source_page = WikiPage(
            id=request.source_page_id,
            title=request.title,
            type="source",
            body=_image_source_body(request, details, has_ocr=bool(ocr_text)),
            tags=("ingest", request.label.name),
            sources=(request.manifest_relpath or request.snapshot_relpath,),
            confidence=request.label.confidence,
        )
        return [*artifacts, GeneratedPage(source_page)]


def _exif_datetime(img: Any, exif_tags: Any) -> str | None:
    try:
        exif = img.getexif()
        if not exif:
            return None
        for tag_id, value in exif.items():
            if exif_tags.TAGS.get(tag_id) in {"DateTimeOriginal", "DateTime"}:
                text = str(value).strip()
                if text:
                    return text
    except Exception:
        return None
    return None


def _best_effort_ocr(source_bytes: bytes) -> str:
    """OCR when pytesseract + the tesseract binary exist; empty otherwise."""

    import shutil

    if importlib.util.find_spec("pytesseract") is None or shutil.which("tesseract") is None:
        return ""
    try:
        import pytesseract  # ty: ignore[unresolved-import]
        from PIL import Image

        with Image.open(io.BytesIO(source_bytes)) as img:
            return str(pytesseract.image_to_string(img)).strip()
    except Exception:
        return ""


def _render_image_metadata(title: str, details: dict[str, object]) -> str:
    lines = [f"# Image Metadata: {title}", ""]
    lines.extend(f"- {key}: {details[key]}" for key in sorted(details))
    return "\n".join(lines) + "\n"


def _image_source_body(
    request: ProcessRequest,
    details: dict[str, object],
    *,
    has_ocr: bool,
) -> str:
    base = request.manifest_relpath.rsplit("/", 1)[0] if request.manifest_relpath else ""
    lines = [
        f"# {request.title}",
        "",
        f"![{request.title}](../{request.snapshot_relpath})",
        "",
        f"- Classification: `{request.label.name}` ({request.label.confidence})",
        f"- Dimensions: {details['width']}x{details['height']} ({details['format']})",
    ]
    if "exif_datetime" in details:
        lines.append(f"- Captured: {details['exif_datetime']}")
    if request.manifest_relpath:
        lines.append(f"- Provenance: [Derived Manifest](../{request.manifest_relpath})")
    if has_ocr and base:
        lines.append(f"- Text content: [OCR extraction](../{base}/ocr.md)")
    lines.extend(
        [
            "",
            "Describe what the image shows before citing it as evidence — captions",
            "are interpretation (see the wiki-media-ingestion images protocol).",
        ]
    )
    return "\n".join(lines)


def pdf_processor_or_none() -> PdfProcessor | None:
    """Return the PDF processor when its extra is installed (D3 fallback)."""

    if importlib.util.find_spec("pdfplumber") is None:
        return None
    return PdfProcessor()


class PdfProcessor:
    """pdfplumber extraction for ``paper`` sources (bake-off winner, D10).

    Produces ``extracted.md`` with ``## Page N`` anchor headings plus a source
    page citing the provenance manifest. Unparseable PDFs (and missing extras
    via :func:`pdf_processor_or_none`) fall back to :class:`DefaultProcessor`
    so text-shaped "PDFs" keep their existing behavior.
    """

    def process(self, request: ProcessRequest) -> list[GeneratedPage | DerivedArtifact]:
        try:
            import pdfplumber
        except ImportError:  # pragma: no cover - guarded by pdf_processor_or_none
            return DefaultProcessor().process(request)

        try:
            with pdfplumber.open(io.BytesIO(request.source_bytes)) as pdf:
                page_texts: list[str] = [
                    str(page.extract_text() or "").strip() for page in pdf.pages
                ]
        except Exception:
            # Not a parseable PDF (e.g. text files wearing a %PDF header).
            return DefaultProcessor().process(request)

        version = importlib.metadata.version("pdfplumber")
        extraction_rel = _extraction_relpath(request)
        source_page = WikiPage(
            id=request.source_page_id,
            title=request.title,
            type="source",
            body=_pdf_source_body(request, page_texts, extraction_rel),
            tags=("ingest", request.label.name),
            sources=(request.manifest_relpath or request.snapshot_relpath,),
            confidence=request.label.confidence,
        )
        return [
            DerivedArtifact(
                relpath="extracted.md",
                content=_render_extracted(request.title, page_texts),
                tool=PDF_TOOL,
                version=version,
                details={"pages": len(page_texts)},
            ),
            GeneratedPage(source_page),
        ]


def _extraction_relpath(request: ProcessRequest) -> str:
    base = request.manifest_relpath.rsplit("/", 1)[0] if request.manifest_relpath else ""
    return f"{base}/extracted.md" if base else "extracted.md"


def _render_extracted(title: str, page_texts: list[str]) -> str:
    """Render the extraction with ``## Page N`` anchor headings (D7)."""

    lines = [f"# Extraction: {title}", ""]
    for number, text in enumerate(page_texts, 1):
        lines.extend([f"## Page {number}", "", text or "*(no extractable text)*", ""])
    return "\n".join(lines).rstrip() + "\n"


def _pdf_source_body(
    request: ProcessRequest,
    page_texts: list[str],
    extraction_rel: str,
) -> str:
    summary = next((text for text in page_texts if text), "")
    summary = " ".join(summary.split())[:280]
    page_links = " · ".join(
        f"[p.{number}](../{extraction_rel}#page-{number})"
        for number in range(1, len(page_texts) + 1)
    )
    lines = [
        f"# {request.title}",
        "",
        f"PDF source; text extracted to [extracted.md](../{extraction_rel}) "
        f"({len(page_texts)} pages).",
        "",
        f"- Classification: `{request.label.name}` ({request.label.confidence})",
    ]
    if request.manifest_relpath:
        lines.append(f"- Provenance: [Derived Manifest](../{request.manifest_relpath})")
    if page_links:
        lines.append(f"- Pages: {page_links}")
    if summary:
        lines.extend(["", summary])
    return "\n".join(lines)


__all__ = [
    "AUDIO_TOOL",
    "IMAGE_TOOL",
    "PDF_TOOL",
    "AudioProcessor",
    "ImageProcessor",
    "PdfProcessor",
    "audio_processor_or_none",
    "image_processor_or_none",
    "pdf_processor_or_none",
]
