---
layout: default
title: Architecture
description: Hermes Wiki architecture — storage layer, processing pipeline, adapter system, and privacy model
---

# Architecture

## Design Principles

1. **Markdown is authoritative** — files are the source of truth; SQLite is a rebuildable projection
2. **Raw sources are append-only** — immutable evidence; external changes create new snapshots
3. **Attribution everywhere** — triple redundancy: YAML frontmatter + SQLite + git commit
4. **Trust before execute** — custom plugins need explicit trust (path + sha256 verification)
5. **Privacy without disclosure** — invisible wikis never leak their names

## Layers

```
┌──────────────────────────────────────────────────────────┐
│ DISCOVERY LAYER                                          │
│ System prompt injection, wiki_search/wiki_show tools,    │
│ profile-scoped whitelist/blacklist visibility            │
├──────────────────────────────────────────────────────────┤
│ SURFACE LAYER                                            │
│ CLI (hermes-wiki), Agent tools, /wiki slash command,     │
│ Dashboard plugin tab (/wikis)                            │
├──────────────────────────────────────────────────────────┤
│ PROCESSING LAYER                                         │
│ Pluggable pipeline: Classifier → Processor → Propagator │
│ Built-in + trusted custom plugins per wiki               │
├──────────────────────────────────────────────────────────┤
│ STORAGE LAYER                                            │
│ Markdown files (authoritative) + SQLite projection       │
│ Per-wiki git repositories                                │
└──────────────────────────────────────────────────────────┘
```

## Storage

### Filesystem Layout

```
~/.hermes/wikis/
├── wikis.db              # Registry (all wikis, slugs, domains)
└── <slug>/
    ├── .git/             # Per-wiki git repository
    ├── wiki.db           # Rebuildable FTS5 projection (gitignored)
    ├── db_versions/      # Prior projection snapshots + manifest
    ├── SCHEMA.md         # Domain contract, taxonomy, propagation rules
    ├── index.md          # Sectioned page catalog
    ├── log.md            # Attributed chronological action log
    ├── raw/
    │   ├── inbox/        # Drop zone for unprocessed sources
    │   ├── articles/
    │   └── papers/
    ├── entities/
    ├── concepts/
    ├── comparisons/
    ├── sources/          # Curated source summary pages
    └── _archive/
```

### Wiki Resolution Cascade

When `--wiki` is omitted:

1. `wiki=` parameter or `HERMES_WIKI` env
2. Profile-local current wiki
3. `~/.hermes/wikis/default`

### Projection Versioning

SQLite projections are rebuilt safely:

1. Build new DB as `wiki.db.tmp`
2. Validate against filesystem
3. Snapshot old DB to `db_versions/wiki-<timestamp>.db`
4. Append manifest row to `db_versions/manifest.jsonl`
5. Atomic swap only after validation passes

## Processing Pipeline

```
raw/inbox/ → [Classifier] → label → [Processor] → List[WikiPage] → [Propagator] → commit
```

### Built-in Classifiers

| Classifier | Detects |
|---|---|
| `article` | Markdown, blog posts, news |
| `paper` | PDF with DOI, academic structure |
| `transcript` | Speaker-labeled notes, Whisper output |
| `image` | JPG/PNG/HEIC → vision caption |
| `audio` | MP3/WAV/M4A → whisper transcript |
| `code-snippet` | Files with code blocks |

### Custom Plugins

Place in `plugins/classifiers/<name>.py` or `plugins/processors/<name>.py`, then:

```bash
hermes-wiki plugins trust classifier <name> --wiki <slug>
```

Untrusted plugin files are visible in lint but never loaded or executed.

### Re-ingestion and Drift

When a source URL is re-ingested:
1. Compute sha256 of new content
2. Compare to latest stored snapshot
3. If different: create new append-only snapshot, run processor, flag `drift_detected=1`

## Adapter System

The package is **standalone-first** with typed Protocol seams in `adapters/base.py`:

| Seam | Purpose |
|------|---------|
| `ConfigAdapter` | Home resolution, profile config, env loading |
| `KanbanAdapter` | Read-only kanban task validation |
| `CronAdapter` | Monitor scheduling and run state |
| `ToolRegistryAdapter` | Agent tool registration |
| `PromptInjectionAdapter` | System prompt wiki block |
| `DashboardLoaderAdapter` | Plugin tab registration |

### Implementations

- **`adapters/standalone/`** (default) — runs without Hermes installed
- **`adapters/hermes/`** — wires into a real Hermes deployment

Selected via `HERMES_WIKI_ADAPTER` env (falls back to `standalone`).

## Privacy Model

### Profile Configuration

```yaml
wiki:
  current: ai-tooling
  default_access: discoverable
  blacklist: []
  whitelist: []
  write_grants: []
```

### Rules

- `whitelist` set → profile sees ONLY those wikis
- `blacklist` set → profile sees all EXCEPT those
- Neither → all non-private wikis visible
- Private wikis (`private: true` in SCHEMA.md) invisible unless whitelisted
- Archived wikis hidden from default discovery
- Invisible wikis return "not found or not visible" — never acknowledge existence

## Health Checks (Lint)

18 automated checks with severity levels:

| Severity | Examples |
|----------|----------|
| High | Broken links, missing citations, invalid tags, projection drift |
| Medium | Orphan pages, stale content, unresolved contradictions |
| Low | Pages over 200 lines, log over 500 entries |
