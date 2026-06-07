# YouTube Links

**Status**: live. The policy below is binding; the wiki's
`wiki.media.youtube` mode governs what ingestion does.

## Policy (read before ingesting any YouTube URL)

YouTube's Developer Policies prohibit downloading, caching, or storing copies
of audiovisual content without written approval, and cap most stored API data
at 30-day retention. Both conflict with this wiki's append-only snapshots:

- **`notes` (default)** — *watch-and-note*. Ingestion snapshots only public
  oEmbed citation metadata (title, channel) into `raw/youtube/` and creates a
  source page with an empty **Notes** section. You watch/listen with your own
  tools and author timestamped notes — your interpretation, never bulk
  transcript content. Cite YouTube itself as the anchor host:
  `([source @ 12:34](https://www.youtube.com/watch?v=ID&t=754s))`.
- **`captions` (opt-in)** — existing captions are fetched via yt-dlp
  (`hermes-wiki[youtube]` extra) into
  `derived/youtube/<source-stem>/transcript.md` with `## [hh:mm:ss]` anchors;
  the retrieval method, language, and manual-vs-automatic kind are stamped in
  the manifest. The wiki operator enabled this knowingly and carries the ToS
  posture. If the extra is missing, ingestion fails with the install hint
  rather than silently downgrading.
- **Audio/video download is never available through this skill.** A wiki
  needing it must build its own trusted processor and assume that risk.

Link rot is accepted for this modality: note it via honest `confidence`
values rather than by storing content. Caption text is ASR-grade for
auto-generated tracks — verify load-bearing quotes against the moment.
