---
name: wiki-media-ingestion
description: "Ingest media sources into a Hermes LLM Wiki: PDFs, images, audio, video, YouTube links, and social posts — derived artifacts, provenance manifests, two-tier storage, and per-modality protocols."
version: 0.1.0
license: MIT
metadata:
  hermes:
    tags: [Wiki, Ingestion, Media, Knowledge]
    related_skills: [wiki-ingestion, wiki-writing]
---

# Hermes Wiki Media Ingestion

Default media skill for Hermes LLM Wikis (override with
`hermes wiki skills set media <skill-name>`). Text sources are covered by
`wiki:wiki-ingestion`; this skill covers everything else. Load only the
modality reference you need:

| Source | Reference |
|---|---|
| PDF documents | [references/pdf.md](references/pdf.md) |
| Images, screenshots, diagrams | [references/images.md](references/images.md) |
| Audio (podcasts, recordings) | [references/audio.md](references/audio.md) |
| Video files | [references/video.md](references/video.md) |
| YouTube links | [references/youtube.md](references/youtube.md) |
| Social-media links | [references/social.md](references/social.md) |

## Shared conventions (all modalities)

- **Derived artifacts** live in `derived/<modality>/<source-stem>/` next to a
  `manifest.json` recording tool, version, model identity, and the input's
  sha256. Manifests are written by processors — never edit them by hand.
- **Two-tier storage**: media ≤50MB snapshots into `raw/` (git-tracked).
  Larger media (≤2GB) is processed with the original kept gitignored under
  `raw/large/` and sha-pinned in the manifest (`wiki.media.keep_originals`:
  `local` default | `none` | `all`). The derived artifacts are the durable
  evidence for large media.
- **Provenance anchors**: cite into media via the derived artifacts' stable
  headings — `## [00:12:34] Speaker A` in transcripts, `## Page 12` in PDF
  extractions, timecoded keyframe filenames. Citations stay ordinary relative
  links: `([source @ 12:34](../derived/audio/<id>/transcript.md#001234-speaker-a))`.
- **Missing dependencies**: ingestion never crashes on absent tools. Items are
  retained with a `needs-deps:` status naming the extras to install (e.g.
  `hermes-wiki[audio]`, `brew install ffmpeg`). Install, then re-process.
- **Interpretation is yours**: extraction (transcripts, page text, keyframes)
  comes from version-stamped processors; captions, syntheses, and
  contradiction handling follow the `wiki:wiki-writing` protocol and are
  attributed to you.

## Pitfalls

- Never write into `derived/` or `raw/large/` by hand.
- Never store YouTube audiovisual content or captions beyond what
  [references/youtube.md](references/youtube.md) permits for the wiki's
  configured mode.
- A media source page without extraction yet ("Binary media Source Snapshot")
  is valid — extend it after the modality processor or your own analysis runs.
