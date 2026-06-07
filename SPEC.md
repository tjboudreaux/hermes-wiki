# Hermes Wiki Plugin — Design Specification

**Status:** Draft v1.1 · 2026-06-05
**Decisions locked:** pilot=ai-tooling, inbox=per-wiki, privacy=default-discoverable+whitelist/blacklist, dashboard=integrated into existing Hermes plugin system, build order=storage→agent→health→cron→dashboard
**Build tool:** Codex CLI (Python backend + CLI), Claude Code (React dashboard tab)
**Pattern basis:** adopts Karpathy's LLM Wiki pattern conceptually — immutable raw sources → agent-curated interlinked pages → schema/index/log/provenance — while remaining Hermes-native: standard relative Markdown links, SQLite/FTS5 search, CLI/tools/dashboard surfaces, and no Obsidian dependency.

---

## 0. Non-Goals

- Not Obsidian. No wikilinks, no vault metadata, no Sync dependency.
- Not a standalone web server. Dashboard is a **plugin tab inside `hermes dashboard`** (the existing React SPA on port 9119).
- Not a CMS. No user accounts, no edit locking, no collaborative WYSIWYG.
- Not a vector DB. BM25 + FTS5 at Phase 1. Embedding-based retrieval is a documented extension point.

---

## 1. Requirements

```
SHALL NOT use Obsidian or any Obsidian-specific metadata
SHALL     integrate as a tab in the existing Hermes web dashboard (port 9119)
SHALL     provide a full CLI interface (hermes wiki …)
SHALL     support extensible classification + raw→processed pipelines
SHALL     provide an inbox (per-wiki raw/inbox/ drop zone)
SHALL     attribute every change to an agent, profile, or human
MAY       link to kanban tasks (bidirectional, like JIRA ↔ Confluence)
SHALL     be discoverable and searchable by agents in any authorized profile in conversation
```

**Pilot wiki:** `ai-tooling` (AI agents, coding tools, research).
**Build order:** 1. Storage+CLI  →  2. Agent tools+discovery  →  4. Health+attribution+kanban  →  5. Cron+monitor  →  3. Dashboard (last).

---

## 2. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                         DISCOVERY LAYER                              │
│                                                                      │
│  System prompt injection: agent sees "Available Wikis:" block        │
│  with slugs + domains + page counts + health.                        │
│  Agent calls wiki_search / wiki_show on demand.                      │
│  Profile config whitelists/blacklists wikis per-profile.             │
│  Default: non-private wikis discoverable by all profiles.            │
│                                                                      │
│  CLI:   hermes wiki search <query> [--wiki <slug>]                   │
│  Tool:  wiki_search(query, wiki=None, limit=5)                       │
└──────────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────────┐
│                       STORAGE LAYER                                  │
│                                                                      │
│  ~/.hermes/wikis/                                                    │
│  ├── wikis.db              # registry (all wikis, slugs, domains)    │
│  ├── default               # optional global fallback wiki slug      │
│  └── <slug>/                                                         │
│      ├── .git/             # per-wiki git repository                 │
│      ├── .gitignore        # ignores projection DB binaries          │
│      ├── wiki.db           # current versioned projection + FTS5     │
│      ├── db_versions/      # prior projection snapshots + manifest   │
│      ├── SCHEMA.md         # domain + taxonomy + propagation rules   │
│      ├── index.md          # sectioned page catalog                  │
│      ├── log.md            # attributed chronological action log     │
│      ├── raw/                                                        │
│      │   ├── inbox/        # per-wiki drop zone                      │
│      │   ├── articles/                                              │
│      │   ├── papers/                                                │
│      │   └── ... (extensible subdirs per classifier)                 │
│      ├── entities/                                                  │
│      ├── concepts/                                                  │
│      ├── comparisons/                                               │
│      ├── sources/                                                   │
│      ├── queries/                                                   │
│      └── _archive/                                                  │
│                                                                      │
│  Resolution cascade (mirrors kanban):                                │
│    1. wiki= param / HERMES_WIKI env                                  │
│    2. profile-local current wiki                                     │
│    3. ~/.hermes/wikis/default                                        │
└──────────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────────┐
│                     PROCESSING LAYER                                 │
│                                                                      │
│  Pluggable pipeline:                                                 │
│    inbox → [Classifier] → class label → [Processor] → wiki pages    │
│                         → [Propagator] → index updates → git commit  │
│                                                                      │
│  Built-in classifiers: article | paper | transcript | image          │
│                        | audio | code-snippet | unknown               │
│                                                                      │
│  Custom classifiers/processors: explicit per-wiki trusted plugins    │
│    ~/.hermes/wikis/<slug>/plugins/classifiers/<name>.py              │
│    ~/.hermes/wikis/<slug>/plugins/processors/<name>.py               │
└──────────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────────┐
│                        SURFACE LAYER                                 │
│                                                                      │
│  CLI:          hermes wiki <verb> …                                  │
│  Agent tools:  read tools visible; write tools separately gated      │
│  Slash cmd:    /wiki <verb> … (forwards to CLI)                      │
│  Dashboard:    plugin tab at /wikis in existing Hermes web UI        │
│                (sidebar nav item, appears after Skills)              │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Storage

### 3.1 Filesystem = Content

All wiki pages are plain `.md` with YAML frontmatter. Portable, git-friendly, readable by any editor or agent.

```yaml
---
id: concepts/attention-mechanism
title: Attention Mechanism
type: concept
created: 2026-06-01
updated: 2026-06-05
tags: [transformers, nlp, attention]
sources: [raw/papers/vaswani-2017.pdf]
confidence: high
contested: false
author: claude-opus-4.8
author_kind: agent
links:
  - entities/google-brain
  - concepts/transformer-architecture
kanban_refs:
  - task_id: KB-123
    direction: page->task
---

# Attention Mechanism
...
```

**Link format:** standard relative markdown links `[text](../path.md)`. Portable to any renderer.

**Source pages:** processed `sources/*.md` pages are curated summaries of one or more immutable raw source snapshots. They are searchable Wiki Pages (`type: source`), distinct from `raw/` evidence files.

### 3.2 SQLite = Metadata + Search

Markdown files and raw sources are the source of truth for wiki knowledge and provenance. SQLite is a **versioned, rebuildable projection** used for search, metadata, health checks, and operational joins. If Markdown and SQLite disagree, files win; the database is rebuilt or repaired, and the inconsistency is reported by lint.

Projection rebuilds are versioned so agents and humans can triage regeneration failures:
- Build the new DB as `wiki.db.tmp`.
- Validate it against the filesystem before swapping.
- Snapshot the old `wiki.db` into `db_versions/wiki-<timestamp>.db`.
- Append a manifest row to `db_versions/manifest.jsonl`.
- Atomically replace `wiki.db` only after validation succeeds.

Search projection normalizes technical terms before FTS indexing: preserve acronyms, split camelCase/snake_case/kebab-case identifiers, and index both original and normalized forms in `search_text`. Phase 1 uses FTS5 BM25 with `unicode61`; Porter stemming is not the default for technical wikis.

**Registry DB:** `~/.hermes/wikis/wikis.db`
```sql
CREATE TABLE wikis (
    slug TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    domain TEXT,
    created TEXT,
    updated TEXT,
    page_count INTEGER DEFAULT 0,
    source_count INTEGER DEFAULT 0,
    last_ingest TEXT,
    last_lint TEXT,
    health_score REAL DEFAULT 1.0,
    archived INTEGER DEFAULT 0,
    archived_at TEXT
);
```

**Per-wiki DB:** `~/.hermes/wikis/<slug>/wiki.db`
```sql
CREATE TABLE pages (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    type TEXT NOT NULL,           -- entity|concept|comparison|query|summary|source
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    tags TEXT,                    -- JSON array
    sources TEXT,                 -- JSON array
    confidence TEXT DEFAULT 'medium',
    contested INTEGER DEFAULT 0,
    contradictions TEXT,
    author TEXT,
    author_kind TEXT,             -- agent|profile|human|cron
    sha256 TEXT,
    word_count INTEGER,
    inbound_links INTEGER DEFAULT 0,
    snippet TEXT,
    body_text TEXT,                 -- projected markdown body, excluding frontmatter/history
    search_text TEXT                -- normalized body/title/tags with camel/snake/kebab splits
);

CREATE VIRTUAL TABLE pages_fts USING fts5(
    id, title, tags, snippet, search_text,
    content='pages',
    content_rowid='rowid',
    tokenize='unicode61'
);

CREATE TABLE ingest_log (
    id INTEGER PRIMARY KEY,
    ingested_at TEXT,
    source_type TEXT,
    source_url TEXT,
    source_path TEXT,
    sha256 TEXT,
    pages_created TEXT,
    pages_updated TEXT,
    drift_detected INTEGER DEFAULT 0,
    author TEXT,
    author_kind TEXT
);

CREATE TABLE sources (
    id TEXT PRIMARY KEY,
    ingested_at TEXT,
    sha256 TEXT,
    source_url TEXT,
    source_path TEXT,
    version INTEGER DEFAULT 1,
    previous_source_id TEXT,
    is_latest INTEGER DEFAULT 1,
    classified_as TEXT
);

CREATE TABLE taxonomy (
    tag TEXT PRIMARY KEY,
    created TEXT
);

-- Projection from SCHEMA.md trusted_plugins; canonical trust records live in Markdown.
CREATE TABLE trusted_plugins (
    name TEXT NOT NULL,
    kind TEXT NOT NULL,              -- classifier|processor
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    trusted_at TEXT NOT NULL,
    author TEXT,
    author_kind TEXT,
    PRIMARY KEY (name, kind)
);

-- Projection from Wiki Page frontmatter; canonical wiki-side refs live in Markdown.
CREATE TABLE kanban_refs (
    page_id TEXT,
    task_id TEXT,
    direction TEXT,
    created TEXT,
    PRIMARY KEY (page_id, task_id, direction)
);

CREATE TABLE projection_versions (
    version_id TEXT PRIMARY KEY,
    created TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    source_tree_sha256 TEXT NOT NULL,
    db_sha256 TEXT,
    previous_version_id TEXT,
    rebuild_reason TEXT,             -- initial|ingest|lint-repair|migration|manual
    status TEXT NOT NULL,            -- active|superseded|failed
    notes TEXT,
    author TEXT,
    author_kind TEXT
);
```

### 3.3 Git boundary

Each wiki root (`~/.hermes/wikis/<slug>/`) is its own git repository. Git tracks durable knowledge artifacts: Markdown pages, raw source snapshots, `SCHEMA.md`, `index.md`, `log.md`, trusted-plugin records, and lightweight manifests.

Projection binaries are local and ignored by git:
- `wiki.db`
- `wiki.db.tmp`
- `db_versions/*.db`

`db_versions/manifest.jsonl` is tracked so agents can inspect projection history even when binary DB snapshots are local-only.

---

## 4. Ingest Pipeline

The pipeline is a plugin chain. Users can register custom classifiers and processors per-wiki, but custom Python is never executed until explicitly trusted for that wiki.

```
inbox/ → [Classifier] → class label → [Processor] → List[WikiPage] → [Propagator] → commit
                    ↓
              wiki.db:ingest_log row
```

### 4.1 Built-in classifiers

Phase 1 has a default max ingest size of 50MB. Files over the limit stay in `raw/inbox/` with an `oversized` status and are not processed until a later media/chunking workflow is available.

| Classifier | Detects |
|---|---|
| `article` | HTML-clipped markdown, blog posts, news |
| `paper` | PDF with DOI, academic structure (abstract/sections/refs) |
| `transcript` | Whisper output, speaker-labeled notes |
| `image` | JPG/PNG/HEIC → vision tool caption → classification |
| `audio` | MP3/WAV/M4A → local whisper → transcript classifier |
| `video` | MP4/MOV/WebM → transcript/frame extraction skill (future) |
| `code-snippet` | Files with code blocks or frontmatter declaring language |
| `unknown` | Fallback — logged for human review |

**Custom classifier registration:** place `plugins/classifiers/<name>.py` in the wiki root, exporting `classify(path: Path) -> ClassLabel | None`, then explicitly trust it with `hermes wiki plugins trust classifier <name> --wiki <slug>`. The canonical trust record lives in `SCHEMA.md` and stores the plugin path and sha256; changed plugin files are disabled until re-trusted. Pipeline runs built-ins first, then trusted custom classifiers in declared order.

### 4.2 Built-in processors

Each processor: `(raw_path: Path, class_label: ClassLabel) -> List[WikiPage]`

A `WikiPage` dataclass: `id, title, type, tags, body, sources, links, author, author_kind`.

Default processor per class produces a `sources/<date>-<slug>.md` summary + one or more entity/concept pages.

**Custom processor registration:** place `plugins/processors/<class>.py` exporting `process(...)`, then explicitly trust it with `hermes wiki plugins trust processor <class> --wiki <slug>`. The canonical trust record lives in `SCHEMA.md`; untrusted processor files are visible in lint but never loaded.

### 4.3 Propagation rules

Defined in `SCHEMA.md` per wiki. The plugin reads them at ingest time and updates:
- `index.md` — adds new page entries
- `log.md` — appends action with attribution
- `wiki.db` — updates `pages` table, refreshes FTS5 index
- Cross-links on affected existing pages when the new source mentions them

### 4.4 Re-ingestion

On re-ingesting a source URL:
1. Compute sha256 of new content
2. Compare to latest stored source snapshot for that URL in `sources`
3. If identical → skip (log "no change")
4. If different → write a new append-only raw source snapshot, increment `sources.version`, mark the prior row `is_latest=0`, run processor, flag as `drift_detected=1`

Raw files are never overwritten. Wiki pages cite the specific source snapshot they used, while `sources` tracks the latest snapshot for each URL.

---

## 5. Attribution

### 5.1 Every write carries an author

`wiki_db.record_change(page_id, author, author_kind)` is called on every file write.

| Source | `author` | `author_kind` |
|---|---|---|
| Agent in chat | model name (e.g. `claude-opus-4.8`) | `agent` |
| Cron job | `cron:<job-name>` | `cron` |
| Profile worker | `profile:<slug>` | `profile` |
| Human via CLI | `$USER` or email from config | `human` |
| Human via dashboard | email from auth (future) | `human` |

### 5.2 Three-layer redundancy

1. **YAML frontmatter** `author` / `author_kind` — survives git, visible in any reader.
2. **SQLite `pages.author`** — fast query, powers dashboard activity log.
3. **Git commit message** — `wiki: ingest <what> [<author>]` — survives DB loss.

### 5.3 Page history outside page bodies

Full page history is not embedded in page markdown. The current author lives in frontmatter, while chronological history is reconstructed from `log.md`, git commits, and the SQLite projection. CLI and dashboard views render this history outside the page body so search and reading stay focused on knowledge content.

---

## 6. Discovery: Cross-Wiki Search in Conversation

### 6.1 Privacy model

Per-profile config in `config.yaml`:
```yaml
wiki:
  current: ai-tooling                  # profile-local default when --wiki is omitted
  default_access: discoverable          # default for all wikis not explicitly listed
  blacklist: []                         # wikis this profile CANNOT see
  whitelist: []                         # only these wikis visible (if set, overrides default)
  write_grants: []                      # wikis this profile may mutate; "*" means all visible
```

**Rules:**
- `whitelist` set → profile sees ONLY those wikis (ignores `default_access`).
- `blacklist` set → profile sees all EXCEPT those wikis.
- Neither set → profile sees all wikis (`default_access: discoverable`).
- A wiki can also mark itself `private: true` in its own SCHEMA.md, which makes it invisible to all profiles unless explicitly whitelisted.
- Archived wikis are hidden from default discovery and mutation unless explicitly requested with an admin/archive flag.
- Prompt injection and ordinary tool/API errors never name invisible wikis. A denied lookup returns "not found or not visible"; admin/debug logs may record the real denial reason.
- Visibility grants read/search access only. Mutations require `write_grants`, `HERMES_WIKI`, or the profile's `wiki` toolset.

### 6.2 System prompt injection

At session start, the prompt builder reads the active profile's config, resolves visible wikis, and injects:

```
# Available Wikis
You have access to the following knowledge bases:
- ai-tooling: AI agents, coding tools, research (89 pages, health 0.88)
- ungodly-economy: game economy, balance, player metrics (147 pages, health 0.94)

Use wiki_search to consult them when a question is domain-relevant.
```

### 6.3 Agent tool

```python
wiki_search(query, wiki=None, limit=5)
# wiki=None → search all visible wikis
# wiki="ai-tooling" → scope to one wiki

wiki_show(page_id, wiki=None)
# Returns full content + frontmatter + linked kanban tasks
```

---

## 7. Web UI: Hermes Dashboard Plugin Tab

### 7.1 Integration mechanism

The existing dashboard (`hermes dashboard`, port 9119) has a plugin manifest system.
The wiki plugin registers as a **dashboard plugin** via `dashboard/manifest.json`:

```json
{
  "name": "wiki",
  "version": "1.0.0",
  "label": "Wikis",
  "icon": "FileText",
  "tab": {
    "path": "/wikis",
    "position": "after:skills"
  },
  "entry": "dist/index.js",
  "css": "dist/style.css",
  "api": "plugin_api.py"
}
```

This gives the plugin:
- A "Wikis" entry in the sidebar nav (after Skills, before Plugins)
- A dedicated route at `/wikis` rendered by `PluginPage`
- API endpoints at `/api/plugins/wiki/*` backed by the Python FastAPI router

### 7.2 Backend API (Python, mounted by the plugin)

```
GET  /api/plugins/wiki/wikis                          # list visible wikis (metadata only)
GET  /api/plugins/wiki/wikis/<slug>                   # visible wiki summary + stats
GET  /api/plugins/wiki/wikis/<slug>/pages             # list pages (paginated, filterable)
GET  /api/plugins/wiki/wikis/<slug>/pages/<page_id>   # full page content
GET  /api/plugins/wiki/wikis/<slug>/search?q=<query>  # FTS5 search, ranked
POST /api/plugins/wiki/wikis/<slug>/ingest            # upload source or {inbox:true}
GET  /api/plugins/wiki/wikis/<slug>/inbox             # list inbox files
GET  /api/plugins/wiki/wikis/<slug>/health            # latest lint report
GET  /api/plugins/wiki/wikis/<slug>/log               # activity log (paginated)

POST /api/plugins/wiki/wikis                          # create wiki
POST /api/plugins/wiki/wikis/<slug>/archive           # archive/disable wiki
DELETE /api/plugins/wiki/wikis/<slug>                 # purge wiki files (future, explicit confirmation only)
```

The backend is FastAPI (`dashboard/plugin_api.py` exposes `router = APIRouter()`) and inherits dashboard auth for `/api/plugins/...`.

### 7.3 Dashboard views (React, inside the plugin tab)

1. **Landing `/wikis`** — visible wikis as cards: slug, domain, page count, health score, last ingest date.
2. **Wiki view `/wikis/<slug>`** — paginated page list (filterable by type/tags), recent activity timeline, health indicators.
3. **Page view `/wikis/<slug>/<page_id>`** — rendered markdown with frontmatter sidebar, inbound/outbound links, author history, kanban task refs.
4. **Search `/wikis/search?q=...`** — global across all visible wikis OR scoped to one. BM25-ranked results. Click-throughs go to page view.
5. **Inbox `/wikis/<slug>/inbox`** — unprocessed files with classifier assignments, one-click re-classify override.
6. **Health `/wikis/<slug>/health`** — lint report with severity-filterable list.
7. **Activity `/wikis/<slug>/log`** — chronological, filterable by `author`/`author_kind`.

### 7.4 Styling

The dashboard uses `@nous-research/ui` component library (dark theme). The wiki plugin inherits those styles automatically through the `PluginPage` wrapper — no separate CSS required beyond page-specific layout.

---

## 8. CLI Surface

```
# Wiki instance management
hermes wiki list                                     # visible wikis
hermes wiki create <slug>                            # init new wiki
hermes wiki switch <slug>                            # set profile-local current wiki
hermes wiki show [slug]                              # summary
hermes wiki archive <slug>                           # hide from normal discovery, preserve files
hermes wiki purge <slug>                             # future destructive removal, explicit confirmation

# Content
hermes wiki ingest <path|url> [--wiki <slug>]        # process one source
hermes wiki ingest --inbox [--wiki <slug>]           # process that wiki's inbox
hermes wiki inbox [--wiki <slug>]                    # list unprocessed files
hermes wiki research <topic> [--wiki <slug>]         # deep-dive, file back

# Navigation
hermes wiki search <query> [--wiki <slug>]           # BM25 search
hermes wiki open <page-id> [--wiki <slug>]           # print page content
hermes wiki list-pages [--wiki <slug>] [--type X] [--tag Y]

# Consumable outputs
hermes wiki brief [--wiki <slug>]                    # current-state briefing
hermes wiki status [--wiki <slug>]                   # plain-language summary

# Maintenance
hermes wiki lint [--wiki <slug>]                     # health check
hermes wiki tags [add|remove] --wiki <slug>          # taxonomy management
hermes wiki plugins list [--wiki <slug>]             # built-in + trusted/untrusted custom plugins
hermes wiki plugins trust classifier <name> [--wiki <slug>]
hermes wiki plugins trust processor <class> [--wiki <slug>]
hermes wiki plugins untrust <name> [--wiki <slug>]

# Surveillance
hermes wiki monitor [--wiki <slug>] --source arxiv|rss|x

# Activity
hermes wiki log [--wiki <slug>] [--author X] [--kind agent|profile|human|cron]

# Kanban linkage
hermes wiki link <page-id> <task-id> [--wiki <slug>]
hermes wiki unlink <page-id> <task-id> [--wiki <slug>]
hermes wiki refs <page-id> [--wiki <slug>]           # show linked tasks

# Dashboard
hermes wiki serve                                    # no-op: uses hermes dashboard
# (wiki tab appears automatically when plugin is enabled)
```

---

## 9. Agent Tools

Read tools are available to every authorized profile and enforce visible-wiki filtering. Write tools require `HERMES_WIKI`, the profile's `wiki` toolset, or an explicit `write_grants` match.

```python
READ_TOOLS = {"wiki_list", "wiki_search", "wiki_show", "wiki_health_check", "wiki_inbox"}
WRITE_TOOLS = {"wiki_ingest", "wiki_create_page", "wiki_link_kanban"}

def _check_wiki_write_mode(wiki: str | None) -> bool:
    env_wiki = os.environ.get("HERMES_WIKI")
    if env_wiki and (not wiki or env_wiki == wiki): return True
    try:
        cfg = load_config()
        wiki_cfg = cfg.get("wiki", {})
        grants = set(wiki_cfg.get("write_grants", []))
        return (
            "wiki" in cfg.get("toolsets", [])
            or "*" in grants
            or (wiki is not None and wiki in grants)
        )
    except Exception:
        return False
```

Tools:
```
Read tools:
wiki_list(wiki=None)
    → Visible wikis or pages in one visible wiki, for navigation context.

wiki_search(query, wiki=None, limit=5)
    → FTS5-ranked results. Crosses all visible wikis when wiki=None.

wiki_show(page_id, wiki=None)
    → Full page content + frontmatter + linked kanban tasks.

wiki_health_check(wiki=None)
    → Full lint report for visible/readable wiki (structured JSON).

wiki_inbox(wiki=None)
    → List unread inbox files with classifier suggestions.

Write tools:
wiki_ingest(path_or_url=None, wiki=None, classifier=None, inbox=False)
    → Run pipeline for one source or, with inbox=True, for the wiki inbox. Exactly one of path_or_url/inbox is required.

wiki_create_page(title, body, type, tags, sources, wiki=None)
    → Create/update with frontmatter + attribution.

wiki_link_kanban(page_id, task_id, wiki=None)
    → Create/update the wiki-owned reference (frontmatter + wiki.db projection). Never writes kanban.db.
```

---

## 10. Kanban Linkage (MAY HAVE)

Bidirectional. Canonical wiki-side refs live in Wiki Page frontmatter so links survive `wiki.db` regeneration.

**Wiki page frontmatter (canonical wiki side):**
```yaml
kanban_refs:
  - task_id: KB-123
    direction: page->task
    created: 2026-06-05
```

**Wiki DB projection** (`wiki.db:kanban_refs`):
```sql
kanban_refs(page_id, task_id, direction, created)
-- direction: 'page->task' | 'task->page'
```

**Kanban side (read-only; no schema modification):**
The wiki does **not** own the kanban plugin and never mutates its schema or tables. The Kanban Reference is owned entirely on the wiki side — canonical in Wiki Page frontmatter, projected into `wiki.db:kanban_refs`. The wiki MAY read kanban (e.g., to validate that a `task_id` exists and to display task titles), but it never writes back into `kanban.db`. "Bidirectional" navigation is satisfied by the wiki-owned projection: `task->page` lookups are answered from `wiki.db:kanban_refs`, not from a kanban-side mirror column.

**Auto-link detection (opt-in):** ingest pipeline scans source content for task-id patterns. Creates linkage only if explicitly enabled in `SCHEMA.md`.

**Display:**
- Dashboard: "Linked Kanban Tasks" panel on page view
- CLI: `hermes wiki refs <page-id>`
- Agent tool: `wiki_show` returns linked tasks

**Creation:**
- CLI: `hermes wiki link <page-id> <task-id>`
- Agent tool: `wiki_link_kanban(page_id, task_id)`
- Updates Wiki Page frontmatter and refreshes the `wiki.db:kanban_refs` projection (no write into `kanban.db`)
- `hermes wiki lint` reports frontmatter ↔ `wiki.db:kanban_refs` projection drift, and (optionally) refs whose `task_id` no longer exists in a reachable kanban

---

## 11. Health Check & Lint

| Check | Severity |
|---|---|
| Orphan pages (no inbound links) | ⚠️ medium |
| Broken relative links | 🔴 high |
| Missing citations on factual claims | 🔴 high |
| Unresolved citations (`sources:` entry matches no page or wiki-local file) | 🔴 high |
| `[unverified]` flags older than 14 days | ⚠️ medium |
| Page not in `index.md` | ⚠️ medium |
| Page over 200 lines | 💡 low |
| Stale content (updated >90 days before most recent related source) | ⚠️ medium |
| Invalid tags (not in taxonomy) | 🔴 high |
| Frontmatter missing required fields | 🔴 high |
| `contested: true` unresolved | ⚠️ medium |
| `log.md` over 500 entries | 💡 low |
| Raw snapshot mutation (sha256 mismatch in raw/) | 🔴 high |
| External source drift (URL differs from latest snapshot) | ⚠️ medium |
| Projection version/rebuild mismatch | 🔴 high |
| Kanban frontmatter ↔ `wiki.db:kanban_refs` projection mismatch | ⚠️ medium |
| Trusted plugin hash mismatch | 🔴 high |
| Untrusted plugin file present | ⚠️ medium |
| Oversized inbox item awaiting media/chunking workflow | ⚠️ medium |
| Cross-consistency failures | 🔴 high |

Output: structured JSON via API + CLI, rendered in dashboard health view.

---

## 12. Per-Wiki Inbox

Each wiki has its own `raw/inbox/` directory. Files dropped there are processed by that wiki's pipeline using that wiki's classifiers and processors.

**Behavior:**
- Files in `inbox/` are invisible to `index.md` and search until processed.
- `hermes wiki inbox --wiki <slug>` shows unprocessed files with their last classification attempt (if any).
- `hermes wiki ingest --inbox --wiki <slug>` processes the inbox for that wiki.
- Files over 50MB stay in `raw/inbox/` with `oversized` status in Phase 1.
- Processed files are moved to the appropriate `raw/<subdir>/` and renamed with date/version prefix.
- Failed-to-classify files stay in inbox with a `unknown` classification tag and a note in the ingest log.

**No shared inbox.** Cross-wiki routing (e.g., "this PDF belongs to ai-tooling but was dropped in ungodly-economy's inbox") is a future feature. For now, drop in the right wiki's inbox.

---

## 13. Cron Integration

Each wiki can have associated monitors. The wiki stores desired monitor definitions in `SCHEMA.md`/wiki config for portability; global Hermes cron owns actual scheduling, run state, retries, and delivery.

```yaml
monitors:
  - name: weekly-arxiv-sweep
    schedule: "0 9 * * 1"
    skills: [wiki-ingest]
    env: { HERMES_WIKI: ai-tooling }
    prompt: "Sweep arxiv for new AI agent and tooling papers, ingest any matches into the wiki"

  - name: daily-health-check
    schedule: "0 8 * * *"
    env: { HERMES_WIKI: ai-tooling }
    prompt: "Run wiki_health_check, report any high-severity issues"
```

Cron runs set `HERMES_WIKI` in the subprocess env, which grants write access for the scoped wiki. The `author` field on all writes is `cron:<job-name>`.

`hermes wiki monitor --setup` writes/updates the wiki's desired monitor definition, then syncs it into global Hermes cron after user confirmation.

---

## 14. Plugin File Structure

```
~/.hermes/hermes-agent/plugins/wiki/
├── plugin.yaml                     # optional CLI/gateway plugin metadata
├── __init__.py
├── wiki_db.py                      # SQLite schema + CRUD + resolution cascade
├── wiki_tools.py                   # Agent tool surface (wiki_search, wiki_show, etc.)
├── wiki_pipeline.py                # Ingest pipeline + classifier/processor registry
├── wiki_search.py                  # FTS5 search + BM25 ranking
└── dashboard/
    ├── manifest.json               # dashboard plugin manifest
    ├── plugin_api.py               # FastAPI router mounted at /api/plugins/wiki/
    ├── src/                        # React source (Claude Code)
    │   ├── WikiLanding.tsx         # /wikis (visible wikis)
    │   ├── WikiView.tsx            # /wikis/<slug>
    │   ├── WikiPage.tsx            # /wikis/<slug>/<page_id>
    │   ├── WikiSearch.tsx          # /wikis/search
    │   ├── WikiInbox.tsx           # /wikis/<slug>/inbox
    │   └── WikiHealth.tsx          # /wikis/<slug>/health
    └── dist/
        ├── index.js                # pre-built IIFE bundle, React externalized
        └── style.css               # optional plugin CSS
```

**CLI module:** `hermes_cli/wiki.py` (mirrors `hermes_cli/kanban.py`)
**Slash command:** `/wiki …` registered in `hermes_cli/commands.py` forwarding to CLI
**Agent tool gating:** read tools enforce visibility; write tools mirror kanban's gated mode

---

## 15. Implementation Phases (in order)

### Phase 1 — Storage + CLI + Inbox (2 weeks, Codex)
**Goal:** a working wiki from the CLI, no UI.

- `wiki_db.py`: registry DB, per-wiki DB, FTS5 index, resolution cascade
- `hermes wiki create/switch/list/show/archive`
- `hermes wiki ingest <path|url>` and `hermes wiki ingest --inbox` with 3 built-in classifiers (article, paper, transcript)
- 50MB max ingest limit in Phase 1; larger files remain in inbox as oversized
- Default processor pipeline
- Trusted plugin allowlist metadata + `hermes wiki plugins list/trust/untrust`
- `hermes wiki inbox` (list + status per wiki)
- `hermes wiki search` (FTS5 with BM25 ranking)
- `hermes wiki list-pages` with type/tag filters
- Per-wiki git integration (commit per ingest with attribution in message; projection DB binaries ignored)
- Per-wiki `SCHEMA.md` template generation
- **Pilot deliverable:** `ai-tooling` wiki populated with 10–20 sources manually

### Phase 2 — Agent Tools + Discovery (1 week, Codex)
**Goal:** agents can search and contribute to wikis in any session.

- `wiki_tools.py` with split read/write gating
- `wiki_search` / `wiki_show` / `wiki_ingest` / `wiki_create_page` / `wiki_list` / `wiki_inbox`
- System prompt injection: visible wikis block in prompt builder
- Profile-scoped wiki access: whitelist/blacklist config
- Slash command `/wiki …`
- **Pilot deliverable:** `hermes` session where agent searches `ai-tooling` wiki and files research back

### Phase 3 — Health + Attribution + Kanban Linkage (1 week, Codex)
**Goal:** quality assurance layer + cross-system linkage.

- Full lint tool with 13 checks, severity levels
- Page history rendered from `log.md`, git commits, and the SQLite projection
- Enforcement that page history stays outside page bodies
- `hermes wiki link/unlink/refs` (kanban bridge)
- Auto-link detection opt-in during ingest
- `hermes wiki log` with author/author_kind filters
- **Pilot deliverable:** health score >0.9 on `ai-tooling`; at least one kanban↔wiki task linkage

### Phase 4 — Cron + Monitor (1 week, Codex)
**Goal:** the wiki stays current without manual intervention.

- `hermes wiki monitor --source arxiv|rss|xurl` CLI
- Cron job templates per wiki
- `hermes wiki monitor --setup` scaffolding
- External source sweep with dedup (sha256-based)
- Re-ingestion with drift detection
- **Pilot deliverable:** weekly arxiv sweep running, at least one drift detection event processed

### Phase 5 — Dashboard Plugin Tab (2 weeks, Claude Code frontend + Codex backend)
**Goal:** visual management surface inside the existing `hermes dashboard`.

- `dashboard/manifest.json` with tab path `/wikis`, position `after:skills`
- `dashboard/plugin_api.py` FastAPI routes mounted at `/api/plugins/wiki/`
- Pre-built `dashboard/dist/index.js` IIFE bundle with React externalized through the Hermes Plugin SDK
- 7 React views using `@nous-research/ui` components:
  - Landing (visible wikis)
  - Wiki view (page list + activity timeline)
  - Page view (rendered markdown + metadata sidebar)
  - Search (BM25 results)
  - Inbox (queue + classifier override)
  - Health (lint report with severity filter)
  - Activity log (filterable by author/author_kind)
- Dark theme inherited from dashboard
- `hermes wiki serve` becomes a no-op (dashboard is the UI)
- **Pilot deliverable:** dashboard running on :9119 with Wikis tab functional

### Future Phase — Media Processing Skills + Chunking
**Goal:** safely process files too large or too multimodal for Phase 1 synchronous ingest.

- Hermes skills for PDFs, video, images, and audio that produce transcripts or decomposed source material
- Chunking/decomposition strategies for files over 50MB
- Reprocess `oversized` inbox items once a suitable media skill exists

---

## 16. Key Design Decisions (locked)

1. **No Obsidian.** Markdown + FTS5 + custom renderer. Portable to any tool.
2. **Markdown is authoritative.** Raw sources and wiki pages win over SQLite. SQLite is a versioned rebuildable projection with snapshot history for triage.
3. **Raw sources are append-only.** Changed URLs create new source snapshots; raw files are never overwritten.
4. **Source pages are curated summaries.** `sources/*.md` are searchable synthesis pages distinct from immutable `raw/` snapshots.
5. **Per-wiki git repos.** Each wiki root is its own git repository; projection DB binaries are ignored.
6. **Per-wiki inbox.** Each wiki is self-contained. No shared routing.
7. **Phase 1 max ingest is 50MB.** Larger files stay in inbox as oversized until future media skills/chunking process them.
8. **Archive, don't delete.** Normal removal archives/hides a wiki while preserving files. Permanent purge is a separate future destructive operation.
9. **Current wiki is profile-scoped.** `hermes wiki switch` changes the active profile's default, not a global default for every profile.
10. **Default-discoverable without disclosure leaks.** All non-private wikis are visible to all profiles unless profile explicitly blacklists/whitelists. Private or blacklisted wikis are not named in prompts or ordinary errors.
11. **Dashboard as plugin tab.** The wiki registers as `/wikis` via `dashboard/manifest.json`; backend routes mount under `/api/plugins/wiki/`. No separate server. No standalone web app.
12. **Attribution triple-redundant without page-body history.** Git commit + YAML frontmatter + SQLite/log projection. Every change signed; history renders outside page content.
13. **FTS5 over vector DB.** BM25 at Phase 1 for 100–500 pages/wikis, using `unicode61` plus normalized technical `search_text`. Embedding search is a documented extension point (`wiki_search.py` accepts a pluggable ranker).
14. **Kanban linkage is wiki-owned (no kanban-schema modification).** Wiki Page frontmatter is canonical; `wiki.db:kanban_refs` projects it. The wiki never mutates `kanban.db` (we don't own that plugin); it may read kanban to validate/display tasks. Both link directions are answered from the wiki-owned projection. Auto-link opt-in to avoid noise.
15. **Pipeline at every layer, with explicit plugin trust.** Classifier and processor are separate plugin points. Custom code can live in per-wiki plugin dirs, but only trusted path+sha records execute.
16. **Monitor definitions live with the wiki; execution lives in global cron.** `monitor --setup` syncs portable per-wiki desired config into Hermes cron with `HERMES_WIKI` scoped.
17. **Build order puts dashboard last.** The foundation (storage, CLI, agent tools, health, cron) must be solid before any UI work. Dashboard is the consumption layer, validated last.

---

## 17. Open Implementation Questions

(Questions for implementation as they arise; none block Phase 1)

1. **None currently blocking Phase 1.** Dashboard backend framework, bundle format, and auth were resolved from the existing Hermes dashboard plugin docs/code.
