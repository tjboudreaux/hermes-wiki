# PDF Sources

**Status**: extraction processor pending (design PR1 — license-filtered
bake-off: docling / unstructured / pdfplumber; AGPL/GPL tools excluded).

Until the processor lands, PDFs classify as `paper` and receive a stub source
page. What you can do now:

1. Read the PDF with your own tools and extend the source page with a faithful
   summary per the `wiki:wiki-writing` protocol.
2. Cite by page using the anchor convention so citations survive the processor
   upgrade: `([source p.12](../derived/pdf/<source-stem>/extracted.md#page-12))`
   once extraction exists; until then cite the source page itself.

When extraction lands, `derived/pdf/<source-stem>/extracted.md` will carry
`## Page N` headings as stable citation anchors.
