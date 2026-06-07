# Social-Media Links

**Status**: live. Recognized post URLs are fetched through platform APIs and
the *fetched JSON response* is snapshotted into `raw/social/` as immutable
evidence — reference rot is real (1 in 5 scholarly articles suffer it), so we
archive what we fetched at ingest time.

## Adapters

| Platform | URL shape | Source |
|---|---|---|
| Bluesky | `bsky.app/profile/<handle>/post/<id>` | public XRPC (`getPostThread`) |
| Mastodon | `<host>/@<user>/<numeric-id>` | public statuses API |
| X / Twitter | `x.com/<user>/status/<id>` | public oEmbed (no timestamp available) |

Re-ingesting a post whose API response changed creates a new versioned
snapshot with `drift_detected` — edits and deletions stay observable.

## Anything else (LinkedIn, gated posts, other platforms)

Fall back to **read-and-note**: view the post with your own tools and write
attributed notes on a source page citing the URL. Never scrape.

## Conventions

- Quoted text is the author's — keep it verbatim in the blockquote; your
  commentary belongs in your own pages per the `wiki:wiki-writing` protocol.
- Threads: ingest the root post; add replies only when they carry evidentiary
  weight of their own.
