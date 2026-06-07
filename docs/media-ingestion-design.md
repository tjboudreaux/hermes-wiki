---
layout: default
title: Media Ingestion Design
description: Decision record and build plan for multimodal ingestion — PDFs, images, audio, video, YouTube, and social links — as skills, processors, and evals
---

# Media Ingestion Design

**Status**: decisions locked 2026-06-07 (deep-research pass + design grill). This document is the binding decision record for the SPEC's deferred *"Media Processing Skills + Chunking"* phase and the artifact PR0 builds against.

**Method**: a 108-agent deep-research pass (26 sources, 126 claims extracted, 25 adversarially verified — 21 confirmed / 4 refuted), followed by a full design walk resolving each branch in dependency order. Verified claims are cited; judgment calls are marked as such.

---

## Decision Record

### D1 — Architecture: split on the extraction/interpretation line

- **Mechanical extraction** (PDF parsing, ASR transcription, scene detection) runs in **trusted processor plugins** (SHA-pinned, per-wiki) with tool + version + model identity stamped into provenance manifests.
- **VLM captioning** runs via Hermes' **auxiliary vision router** (`agent/auxiliary_client.py` — the host-native side-task seam with its own vision fallback chain), invoked from the media skill's bundled scripts; the resolved model is recorded in the manifest.
- **Interpretation** (synthesis, summaries, contradiction handling) stays **agent-side** via skills, exactly like text today.

> **Principle amendment**: the core pipeline is *"deterministic, or version-stamped extraction; interpretation is always attributed to a model identity."* Recorded in CONTEXT.md.

### D2 — Derived artifact tier

`derived/<modality>/<source-id>/` holds transcripts, keyframes, extracted markdown, OCR text — plus a `manifest.json` per artifact set:

```json
{"tool": "whisperx", "version": "3.1.5", "model_id": "large-v2",
 "input_sha256": "…", "created": "2026-06-07T00:00:00Z"}
```

Git-tracked, written only by processors, never hand-edited. Semantics: **cached extraction with stamped provenance** — not a projection (no auto-rebuild; a future `derived_stale` lint check can flag input-sha drift). Keyframes capped (default 24 frames, ~100KB target each, overridable via skill config).

### D3 — Dependency delivery: optional extras + preflight-retain

- Python deps ship as pinned optional extras: `hermes-wiki[pdf]`, `[image]`, `[audio]`, `[video]` (pins feed D2 version stamps).
- System binaries (ffmpeg, poppler) get `shutil.which` preflights; missing deps **retain** the inbox item with an actionable status — `needs-deps (ffmpeg, hermes-wiki[audio])` — surfaced like `oversized` today. Never a crash; *unprocessable is a valid outcome.*
- Future escape hatch: per-wiki cloud-ASR config for GPU-less/air-gapped users.

### D4 — Large media: two-tier storage

- **≤ `MAX_INGEST_BYTES` (50MB)**: unchanged — snapshot into `raw/`, git-tracked.
- **> 50MB, ≤ `MAX_MEDIA_BYTES` (~2GB)**: processed but **not git-committed**. Original kept under `raw/large/` (gitignored) with sha256 + size + source ref pinned in the D2 manifest. Config `wiki.media.keep_originals: local` (default) | `none` (delete after derivation) | `all` (force git-track).
- `derived/` is always git-tracked — for large media, **the derived set is the durable evidence**; the original is a sha-pinned local witness.
- Chunking of long media is the extractor's concern (WhisperX VAD), not pipeline machinery.

> **Principle amendment**: for large media, provenance consciously degrades from *bytes-in-git* to *fingerprint-in-git*. Recorded in CONTEXT.md.

### D5 — Eval lanes and the micro-corpus

| Lane | Marker | Cadence | Contents |
|---|---|---|---|
| Plumbing | `eval` (existing) | CI, every PR | Processors run with **stub extractors** returning committed golden derived-sets ("extractor replay"). Asserts manifest schema, storage tiering, `needs-deps` retention, derived-page structure, citation anchor format. No model downloads; fully deterministic. |
| Extraction | `eval_media` (new) | Weekly + pre-release + on-demand | Real tools on the micro-corpus: WhisperX (tiny/base) → **jiwer WER ≤ threshold** vs golden transcript; **DER ≤ threshold** (pyannote.metrics); PySceneDetect scene-count exact; PDF parser vs golden extraction (edit-distance threshold). Thresholds absorb hardware nondeterminism. |
| Interpretation | `eval_llm` (existing) | Scheduled | Caption faithfulness: FaithScore-style claim-decomposition (reference-free — decompose caption into atomic facts, verify each against the image) + CLIPScore as a cheap secondary signal (documented weaknesses: negation, long captions — never a sole gate). |

**Micro-corpus**: committed, **< 5MB total**, CC0/public-domain with a LICENSES file — ~15s speech WAV, ~10s two-scene MP4, 3 PNGs (chart/screenshot/photo), a 2-page PDF with a table, a synthetic social-post HTML. Golden derived-sets double as the stub-extractor payloads — one corpus, two lanes.

### D6 — Skill surface: one skill, progressive disclosure, one new kind

- One `wiki-media-ingestion` skill: thin router SKILL.md (~100 lines — shared D1–D4 conventions + modality table) pointing at **reference files** `references/{pdf,images,audio,video,youtube,social}.md` (Anthropic domain-organization pattern: ingesting a PNG loads only `images.md`). Shared `scripts/` invoked, not read.
- **One** new `SKILL_KINDS` entry: `media` — per-wiki override via existing `hermes wiki skills set` machinery + one dashboard row + one F9 prompt annotation kind.
- Per-modality tuning via `metadata.hermes.config` keys (e.g. `wiki.media.transcribe_model`), not skill slots. Trade accepted: overriding a *single* modality's protocol means forking the media skill.
- `wiki-ingestion` gains a pointer: media sources → load `wiki:wiki-media-ingestion`.

### D7 — Provenance anchors

Anchors live **in the derived artifacts** as stable headings; citations remain ordinary relative-link provenance markers with a human-readable position:

- Transcripts: `## [00:12:34] Speaker A` → `([source @ 12:34](../derived/audio/<id>/transcript.md#001234-speaker-a))`
- PDF extraction: `## Page 12` → `([source p.12](../derived/pdf/<id>/extracted.md#page-12))`
- Keyframes: timecoded filenames (`scene-04-0834s.jpg`), linked directly.

No lint or schema changes — the broken-link checker already resolves relative links; the convention is prose in the modality reference files and asserted by the CI plumbing lane.

> **Phase 2**: structured `evidence:` frontmatter spans (`{source, t0, t1}`) once a dashboard player exists to consume them.

### D8 — YouTube: notes by default, captions opt-in, never AV

Verified policy wall: YouTube Developer Policies prohibit downloading/caching/storing AV copies without written approval (§III.E.1.a verbatim) and cap most stored API data at 30-day retention — both incompatible with append-only `raw/`. The claim that scraping is categorically banned was **refuted (0-3)** — unsettled, not cleared.

Config `wiki.media.youtube`:

- **`notes` (default)** — source page from **oEmbed metadata** (title/channel/duration/chapters); knowledge capture is agent-side **watch-and-note**: timestamped notes citing YouTube itself as the anchor host (`…watch?v=X&t=754`). Nothing stored, nothing on a retention treadmill. Legal shape: notes *about* content, not copies *of* it.
- **`captions` (opt-in)** — yt-dlp fetches existing captions/subtitles only → normal derived-artifact flow, retrieval method stamped in the manifest. Replaces `notes` when enabled. Informed consent: the ToS posture is stated plainly in config docs and `youtube.md`; the user assumes the risk.
- **`full` (audio download → ASR) is never shipped** — it crosses the verbatim prohibition. `youtube.md` documents how a user can build it as a per-wiki trusted processor (the SHA-pinned plugin seam is the user-assumed-risk boundary).

### D9 — Social links: open platforms first-class, fetched-response snapshots

Justification is quantified: reference rot hits 1 in 5 STM articles, 7 in 10 among those with web references (Klein et al., PLOS ONE 2014 — headline figures verified 3-0).

- **Generic unfurl processor**: OpenGraph/oEmbed fetch for any URL; the fetched JSON/HTML responses are snapshotted into `raw/social/` as immutable evidence ("WARC-spirit": archive what we fetched).
- **Bluesky + Mastodon adapters**: open public JSON APIs → full post (text, author, timestamps, reply context), API JSON snapshotted as raw evidence. Compliant by design.
- **X / LinkedIn**: generic unfurl + agent watch-and-note fallback in `social.md`. No scraping shipped.

> **Phase 2**: true WARC page capture (browsertrix-class tooling; the WARC-GPT pattern demonstrates WARC-backed knowledge bases with provenance).

### D10 — PDF parser: license pre-filter, then bake-off

- **Policy**: permissive licenses only. Shortlist: **docling** (MIT), **unstructured** (Apache-2.0), **pdfplumber** (MIT). **Excluded upfront: PyMuPDF (AGPL-3.0), marker (GPL-class)** — copyleft obligations on downstream users of an MIT plugin are disqualifying regardless of benchmark scores.
- **Bake-off results (2026-06-07, PR1)** — selected on dependency weight + license + corpus fidelity per the pre-agreed criteria:

  | Candidate | License | Transitive deps | Corpus extraction |
  |---|---|---|---|
  | **pdfplumber 0.11.9** ✅ pinned in `[pdf]` | MIT | 3 (pdfminer.six, Pillow, pypdfium2) | 2/2 pages exact, ~2ms |
  | docling | MIT | 67 — incl. torch, torchvision, transformers, opencv | not run — disqualified as *default* on weight |
  | unstructured[pdf] | Apache-2.0 | 84 — incl. torch, onnxruntime, opencv | not run — same |

  The design prior ("docling wins on tables/structure") was not contradicted — it was priced: a full torch stack is disproportionate for the default digital-native-text path. docling remains the documented upgrade path (a future `[pdf-ml]` extra for scanned/complex documents); its extraction quality was not evaluated here and must be benchmarked (OmniDocBench slice) if that tier is built.

### D11 — Build order

| PR | Scope |
|---|---|
| **0 — Foundations** | `derived/` tier + manifests (D2) · two-tier storage, `MAX_MEDIA_BYTES`, `keep_originals` (D4) · `needs-deps` retention (D3) · `media` SKILL_KIND + `wiki-media-ingestion` scaffold (D6) · micro-corpus + stub-extractor CI lane + `eval_media` marker/workflow (D5) · media classifier built-ins (extension/magic-byte) · CONTEXT/SPEC principle amendments (D1, D4) |
| **1 — PDF** | Bake-off → pinned winner, processor, `pdf.md`, page-anchor goldens |
| **2 — Images** | Aux-router captioning + OCR, `images.md`, FaithScore/CLIPScore lane |
| **3 — Audio** | WhisperX processor, transcript anchors, WER/DER gates, `audio.md` |
| **4 — Video** | PySceneDetect + composition of audio + image captioning, `video.md` |
| **5 — Social** | Generic unfurl + Bluesky/Mastodon adapters, `social.md` *(parallelizable with 1–4)* |
| **6 — YouTube** | oEmbed notes flow + `captions` flag, `youtube.md` |

Each PR lands **evals-first** with its lane gates.

---

## Phase-2 Register

1. Structured `evidence:` frontmatter spans + dashboard media player (D7)
2. True WARC page capture for social/web sources (D9)
3. Cloud-ASR config escape hatch (D3)
4. `derived_stale` lint check (input-sha drift against manifests) (D2)

## Verified Tooling Summary

| Modality | Tool | License | Eval metric | Verification |
|---|---|---|---|---|
| Audio/video ASR | WhisperX (faster-whisper + wav2vec2 alignment + pyannote VAD/diarization) | BSD-2 | jiwer WER/CER (Apache-2.0); pyannote.metrics DER | 3-0 ×4 claims |
| Video scenes | PySceneDetect (Content/Threshold/Adaptive/Histogram detectors) | BSD | scene-count exact | 3-0 ×3 |
| Image captions | via auxiliary vision router | — | FaithScore (reference-free claim decomposition) + CLIPScore (secondary) | 3-0 ×4 |
| PDF | bake-off winner (docling prior) | MIT/Apache only | OmniDocBench-slice + golden edit-distance | benchmark 3-0; tools unverified |

**Refuted claims — do not build on**: OmniDocBench's exact per-element metric mapping (1-2); "scraping prohibition rules out yt-dlp entirely" (0-3); the 13–17% live-web rot rates and <25% Memento-coverage figures (refuted/split — only the headline reference-rot figures are citable).

**Known gaps (judgment, not evidence)**: platform-API mechanics for X/Bluesky/Mastodon/LinkedIn and skill-packaging specifics for heavy native deps had no surviving verified claims; D6/D9 shapes are engineering judgment within verified constraints.
