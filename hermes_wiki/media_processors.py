"""Modality extraction processors (media design PR1+).

Extraction runs in version-stamped processors (design D1): the tool and its
version land in the derived manifest; pages cite the manifest, and citations
into the extraction use stable headings (design D7).
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import io

from hermes_wiki.models import WikiPage
from hermes_wiki.pipeline import (
    DefaultProcessor,
    DerivedArtifact,
    GeneratedPage,
    ProcessRequest,
)

PDF_TOOL = "pdfplumber"


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


__all__ = ["PDF_TOOL", "PdfProcessor", "pdf_processor_or_none"]
