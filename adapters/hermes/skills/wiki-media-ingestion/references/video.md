# Video Sources

**Status**: live. Video classifies via container magic bytes (ftyp/EBML);
most videos exceed 50MB and use the two-tier large-media path automatically
(streamed by path, never loaded into memory). Requires the
`hermes-wiki[video]` extra (PySceneDetect + OpenCV + faster-whisper).

## What ingestion produces

- `derived/video/<source-stem>/keyframes/scene-NN-<sec>s.jpg` — one frame per
  detected scene start, capped via `wiki.media.max_keyframes` (default 24).
- `derived/video/<source-stem>/transcript.md` — the audio track transcribed
  under `## [hh:mm:ss]` headings (the container is demuxed directly; a broken
  or missing audio track never costs the visual extraction).
- Provenance manifest with scene/segment counts; a source page listing the
  first scenes with timestamps and a first-segment summary.

## Working with video evidence

1. **Cite moments via transcript anchors**, scenes via keyframe files:
   `([source @ 12:34](../derived/video/<stem>/transcript.md#001234))`,
   `![scene](../derived/video/<stem>/keyframes/scene-03-0834s.jpg)`.
2. **Caption keyframes per the images protocol** (FaithScore-style
   self-check) before citing them — keyframes are extraction; what they show
   is your interpretation.
3. Transcripts are ASR output: verify load-bearing quotes against the moment
   before quoting as exact.
