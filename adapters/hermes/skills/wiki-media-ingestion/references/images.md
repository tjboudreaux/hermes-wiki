# Image Sources

**Status**: extraction processor pending (design PR2).

Images classify via magic bytes and snapshot into `raw/images/` with a stub
source page + provenance manifest. What you can do now:

1. **Describe what you see** — view the snapshot and extend the source page
   with a faithful caption: what the image shows, any text it contains (OCR by
   reading), chart values, diagram structure. Your caption is interpretation:
   hedge what is uncertain, and never state image content you have not seen.
2. **Cite the image directly** in pages that use it as evidence:
   `![diagram](../raw/images/<snapshot>.png)` plus the source page citation.

When the modality processor lands, OCR text and metadata will live in
`derived/image/<source-stem>/` for citation.
