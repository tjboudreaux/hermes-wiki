# Audio Sources

**Status**: live. Audio classifies via magic bytes; with the
`hermes-wiki[audio]` extra installed (faster-whisper — no torch, no system
ffmpeg needed), ingestion transcribes locally on CPU. Files over 50MB use the
two-tier large-media path automatically and are streamed, never loaded into
memory.

## What ingestion produces

- `derived/audio/<source-stem>/transcript.md` — segments under
  `## [hh:mm:ss]` headings (stable citation anchors, D7).
- Provenance manifest with `tool=faster-whisper`, the pinned library version,
  and the model name as `model_id` (configurable via
  `wiki.media.transcribe_model`; default `base`).
- A source page with duration, segment count, and a first-segment summary.

Without the extra (or on transcription failure), ingestion produces the
provenance stub page — install the extra and re-ingest.

## Working with audio evidence

1. **Cite moments, not files**:
   `([source @ 12:34](../derived/audio/<source-stem>/transcript.md#001234))`.
2. **Transcripts are extraction, not ground truth**: ASR mishears names and
   numbers. Verify load-bearing quotes by listening to the moment yourself
   before citing them as exact, and hedge per the `wiki:wiki-writing`
   protocol otherwise.
3. No speaker labels yet — diarization is the `[audio-diarize]` upgrade path.
   When speaker identity matters, attribute it from context and say so.
