# YouTube Links

**Status**: processor pending (design PR6). The *policy* below is decided and
binding regardless of implementation status.

## Policy (read before ingesting any YouTube URL)

YouTube's Developer Policies prohibit downloading, caching, or storing copies
of audiovisual content without written approval, and cap most stored API data
at 30-day retention. Both conflict with this wiki's append-only snapshots, so
the wiki's `wiki.media.youtube` mode governs what is allowed:

- **`notes` (default)** — *watch-and-note*. The source page holds only oEmbed
  metadata (title, channel, duration, chapters). You watch/listen with your
  own tools and author timestamped notes on the page. Cite YouTube itself as
  the anchor host: `([source @ 12:34](https://youtube.com/watch?v=ID&t=754))`.
  Never paste bulk transcript content; notes are your interpretation, not a
  copy.
- **`captions` (opt-in)** — existing captions/subtitles are fetched into
  `derived/youtube/<source-stem>/transcript.md` with the retrieval method
  stamped in the manifest. The wiki operator enabled this knowingly; the
  ToS posture is theirs to carry.
- **Audio/video download is never available through this skill.** A wiki
  needing it must build its own trusted processor and assume that risk.

Link rot is accepted for this modality: note it via honest `confidence` values
rather than by storing content.
