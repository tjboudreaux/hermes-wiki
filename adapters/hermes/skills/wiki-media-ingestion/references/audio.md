# Audio Sources

**Status**: transcription processor pending (design PR3 — WhisperX:
faster-whisper ASR + word-level alignment + speaker diarization).

Audio classifies via magic bytes; files over 50MB use the two-tier large-media
path automatically. Requires `hermes-wiki[audio]` + ffmpeg once the processor
lands — missing deps retain the item with a `needs-deps:` status.

When transcription lands, `derived/audio/<source-stem>/transcript.md` will
carry `## [hh:mm:ss] Speaker` headings. Cite moments, not files:
`([source @ 12:34](../derived/audio/<source-stem>/transcript.md#001234-speaker-a))`.

Until then: if you can listen to the audio with your own tools, extend the
stub source page with timestamped notes following the same anchor style.
