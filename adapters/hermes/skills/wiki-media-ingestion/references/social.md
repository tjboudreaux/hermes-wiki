# Social-Media Links

**Status**: unfurl processor pending (design PR5). The conventions below are
decided and binding.

## Per-platform handling

- **Bluesky / Mastodon** — open public JSON APIs. The processor fetches the
  full post (text, author, timestamps, reply context) and snapshots the API
  response into `raw/social/` as immutable evidence.
- **Any other URL** — generic unfurl: OpenGraph/oEmbed metadata fetched and
  snapshotted as evidence.
- **X / LinkedIn** — generic unfurl only. When it yields too little, fall back
  to *read-and-note*: view the post with your own tools and write attributed
  notes on the source page. Never scrape.

## Conventions

- The snapshot of *what was fetched* is the evidence; reference rot is real
  (1 in 5 scholarly articles suffer it), so capture at ingest time.
- Quote post text faithfully and attribute the author; your commentary stays
  clearly separate, per the `wiki:wiki-writing` protocol.
- Threads: ingest the root post; add reply posts only when they carry
  evidentiary weight of their own.
