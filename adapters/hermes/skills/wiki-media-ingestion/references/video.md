# Video Sources

**Status**: processor pending (design PR4 — PySceneDetect keyframes + the
audio transcription pipeline + keyframe captioning).

Video classifies via container magic bytes (ftyp/EBML); most videos exceed
50MB and use the two-tier large-media path automatically.

When the processor lands, `derived/video/<source-stem>/` will hold
`transcript.md` (timestamped headings), `keyframes/scene-NN-<sec>s.jpg`
(capped, timecoded filenames), and the manifest. Cite moments via transcript
anchors and scenes via keyframe files.

Until then: if you can watch the video with your own tools, extend the stub
source page with timestamped notes.
