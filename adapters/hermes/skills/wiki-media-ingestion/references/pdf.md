# PDF Sources

**Status**: live. PDFs classify as `paper`; with the `hermes-wiki[pdf]` extra
installed, ingestion extracts text per page via pdfplumber (bake-off winner —
see the media design doc).

## What ingestion produces

- `derived/pdf/<source-stem>/extracted.md` — full text with `## Page N`
  headings (stable citation anchors).
- `derived/pdf/<source-stem>/manifest.json` — provenance: tool, version,
  input sha256, page count.
- A source page summarizing the first page and linking every page anchor.

Without the extra (or for unparseable PDFs), ingestion falls back to the
default text processor — install the extra and re-ingest for real extraction.

## Working with PDF evidence

1. **Cite by page** so claims stay checkable:
   `([source p.12](../derived/pdf/<source-stem>/extracted.md#page-12))`.
2. **Synthesize from the extraction**, not from memory: read `extracted.md`,
   then write concept/entity pages per the `wiki:wiki-writing` protocol.
3. Extraction is text-layer only (no OCR). Scanned PDFs yield
   `*(no extractable text)*` pages — read those visually with your own tools
   and note that the description is your interpretation.
