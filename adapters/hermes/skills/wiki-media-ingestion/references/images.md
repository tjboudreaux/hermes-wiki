# Image Sources

**Status**: live. Images classify via magic bytes; with the
`hermes-wiki[image]` extra installed, ingestion extracts mechanical metadata
(dimensions, format, EXIF timestamps) and — when tesseract is present —
best-effort OCR text.

## What ingestion produces

- `derived/image/<source-stem>/metadata.md` + provenance manifest (Pillow
  version stamped; width/height/format/EXIF in details).
- `derived/image/<source-stem>/ocr.md` — only when pytesseract + the
  tesseract binary are available.
- A source page **embedding the image** with its metadata, ready for your
  caption.

## Captioning protocol (interpretation is yours — D1)

1. **Look at the image** (the source page embeds the snapshot), then extend
   the page with a caption: what it shows, text it contains, chart values,
   diagram structure.
2. **Self-check like FaithScore**: break your caption into atomic claims and
   verify each against the image before committing. Drop or hedge any claim
   you cannot see. Never describe an image you have not viewed.
3. OCR output is mechanical extraction — trust it for text content but verify
   layout-sensitive readings (tables, axis labels) visually.
4. Cite image evidence by embedding (`![…](../raw/images/<snapshot>)`) plus
   the source-page citation; for OCR-backed claims cite
   `([source OCR](../derived/image/<source-stem>/ocr.md))`.
