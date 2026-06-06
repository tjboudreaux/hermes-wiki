---
name: wiki-ingestion
description: "Ingest sources into a Hermes LLM Wiki: classify articles/papers/transcripts, manage the raw inbox, snapshot sources append-only, and handle oversized or unknown files."
version: 1.0.0
license: MIT
metadata:
  hermes:
    tags: [Wiki, Ingestion, Knowledge]
    related_skills: [wiki-commands, wiki-writing]
---

# Hermes Wiki Ingestion

This is the default ingestion skill for Hermes LLM Wikis. It describes how raw
material becomes attributable Wiki Pages. A wiki can override this default with
`hermes wiki skills set ingestion <skill-name>`.

## The pipeline

Every ingest follows the same deterministic flow:

1. **Snapshot** — the source bytes are stored append-only under `raw/` (never
   overwritten; re-ingesting changed content creates a new versioned snapshot
   and flags `drift_detected`).
2. **Classify** — built-in classifiers detect `article`, `paper`, or
   `transcript`. If none match, trusted custom classifiers (see
   `wiki plugins`) get a chance. Anything else lands as `unknown` and is
   retained for review, never silently dropped.
3. **Process** — the processor for the classified label generates or updates
   Wiki Pages (a `source` page plus extracted `concept`/`entity` pages),
   cross-linking existing pages.
4. **Propagate** — index.md sections, log.md attribution rows, the SQLite
   projection, and a git commit are all updated atomically; failures roll back.

## Ingesting one source

```bash
hermes wiki ingest <local-path-or-https-url> [--wiki <slug>] [--author <name>]
```

- Requires a write grant (`HERMES_WIKI=<slug>` or config write grant).
- URLs are fetched and deduplicated by sha256 — unchanged content is a no-op
  (`no change: <source-id>`).
- The 50MB Phase-1 cap applies; larger sources are refused.

## The inbox flow

Drop files into `<wiki-root>/raw/inbox/` (or let monitors deliver them), then:

```bash
hermes wiki inbox                  # list pending files with status + classifier
hermes wiki ingest --inbox         # batch-process everything processable
```

Per-file outcomes:

- `Ingested <name> class=<label>` — pages were generated.
- `Retained <name> class=unknown` — kept in the inbox for a human/agent to
  classify. Override via the dashboard inbox view or the classify API, then
  re-process.
- `Skipped <name> status=oversized` — exceeds the 50MB cap; not processable
  in this phase. Delete it or handle it out-of-band.

Classifier overrides persist in `raw/inbox_status.json` and survive failed
attempts; an override pins the label for the next `ingest --inbox` run.

## Recurring ingestion (monitors)

For sources that update on a schedule, define a portable monitor instead of
ingesting manually:

```bash
hermes wiki monitor --source rss --schedule "0 8 * * *" --prompt "Sweep feeds…"
hermes wiki monitor --setup --yes
```

Monitor sweeps run with `author_kind=cron` and full attribution.

## Custom classification

When the built-ins misclassify a domain-specific format, write a classifier at
`plugins/classifiers/<name>.py` exposing
`classify(source_path) -> ClassLabel | str | None`, then trust it explicitly:

```bash
hermes wiki plugins trust classifier <name>
```

Trust is recorded canonically in `SCHEMA.md` (path + sha256) — editing the file
after trusting silently disables it until re-trusted.

## Rules

- Never write into `raw/` by hand during ingestion — let the pipeline snapshot.
- Never re-classify by renaming files; use the override surfaces.
- Unknown is a valid outcome: retain, review, re-classify. Do not force-fit.
- Check `hermes wiki lint` after large batches; it repairs the projection.
