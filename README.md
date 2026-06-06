<p align="center">
  <img src="docs/assets/hermes-wiki-banner.svg" alt="Hermes Wiki — Karpathy-style LLM Wikis for the Hermes Agent" width="600">
</p>

<h1 align="center">Hermes Wiki</h1>

<p align="center">
  <strong>Karpathy-style LLM Wikis for Hermes — persistent, compounding knowledge bases that agents curate over time.</strong>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> •
  <a href="#installation">Installation</a> •
  <a href="https://hermes-wiki.github.io/hermes-wiki/">Documentation</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#faq">FAQ</a> •
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

<p align="center">
  <a href="https://github.com/hermes-wiki/hermes-wiki/actions"><img src="https://img.shields.io/github/actions/workflow/status/hermes-wiki/hermes-wiki/ci.yml?branch=main&style=flat-square" alt="CI"></a>
  <a href="https://pypi.org/project/hermes-wiki/"><img src="https://img.shields.io/pypi/v/hermes-wiki?style=flat-square" alt="PyPI"></a>
  <a href="https://github.com/hermes-wiki/hermes-wiki/blob/main/LICENSE"><img src="https://img.shields.io/github/license/hermes-wiki/hermes-wiki?style=flat-square" alt="License: MIT"></a>
  <img src="https://img.shields.io/pypi/pyversions/hermes-wiki?style=flat-square" alt="Python 3.11+">
</p>

---

## What is Hermes Wiki?

Hermes Wiki is a Python package that gives AI agents persistent, compounding knowledge bases instead of traditional RAG. It implements [Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) for the [Hermes Agent](https://github.com/nous-research/hermes): agents ingest sources, synthesize interlinked wiki pages, and maintain knowledge over time — so they never rediscover context from scratch.

```
┌─────────────────────────────────────────────────────────┐
│  Raw Sources (Immutable)                                │
│  Articles, papers, transcripts — agents read, never     │
│  modify. Append-only with sha256 provenance.            │
└────────────────────────┬────────────────────────────────┘
                         │ ingest
                         ▼
┌─────────────────────────────────────────────────────────┐
│  LLM Wiki (Agent-Maintained)                            │
│  Entity pages, concept pages, comparisons, summaries.   │
│  Cross-referenced, attributed, git-committed.           │
└────────────────────────┬────────────────────────────────┘
                         │ query / lint / monitor
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Surfaces: CLI + Agent Tools + Dashboard                │
│  hermes-wiki CLI, /wiki slash commands, React dashboard │
└─────────────────────────────────────────────────────────┘
```

### The Karpathy Pattern, Implemented

Karpathy's insight: LLMs should **curate**, not just retrieve. Traditional RAG uploads documents and retrieves chunks at query time. The LLM Wiki pattern instead has agents:

1. **Ingest** sources into structured wiki pages with cross-references
2. **Maintain** pages over time — resolve contradictions, update stale claims, link new evidence
3. **Compound** knowledge — each ingestion enriches the whole wiki, not just one answer

Hermes Wiki makes this operational with a CLI, agent tools, and a web dashboard.

## Features

| Feature | Description |
|---------|-------------|
| **CLI** | Full `hermes-wiki` command surface: create, ingest, search, lint, link, monitor |
| **Agent Tools** | `wiki_search`, `wiki_show`, `wiki_ingest`, `wiki_create_page` — agents use wikis in conversation |
| **Dashboard** | React 19 plugin tab in the Hermes dashboard with search, inbox, health, and activity views |
| **Attribution** | Every change is attributed (agent/profile/human/cron) with triple redundancy: frontmatter + SQLite + git |
| **Privacy** | Profile-scoped visibility with whitelist/blacklist — invisible wikis never leak their names |
| **Health & Lint** | 18 automated checks: broken links, orphans, stale content, projection drift, untrusted plugins |
| **Kanban Linkage** | Bidirectional wiki-page ↔ kanban-task references (wiki-owned, read-only to kanban) |
| **Pluggable Pipeline** | Custom classifiers and processors per wiki, with explicit trust-before-execute security |
| **Git-Backed** | Each wiki is its own git repository; projection DBs are rebuildable from markdown |

## Installation

### Requirements

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Node.js + npm (dashboard only)
- An [OpenRouter API key](https://openrouter.ai/) for LLM-backed features

### Install

```bash
git clone https://github.com/hermes-wiki/hermes-wiki.git
cd hermes-wiki
uv sync
```

### Verify

```bash
uv run hermes-wiki --help
```

## Quick Start

```bash
# 1. Create a wiki
uv run hermes-wiki create ai-tooling --domain "AI agents and coding tools"

# 2. Ingest a source
uv run hermes-wiki ingest https://example.com/transformer-paper --wiki ai-tooling

# 3. Search the wiki
uv run hermes-wiki search "attention mechanism" --wiki ai-tooling

# 4. Check health
uv run hermes-wiki lint --wiki ai-tooling
```

### With an Isolated Home (Recommended for Development)

```bash
# Seed an isolated Hermes home at .hermes-test
uv run python -m hermes_wiki.harness --repo-root "$(pwd)" init
export HERMES_HOME="$(pwd)/.hermes-test"

# Start the dashboard
uv run python -m hermes_wiki.harness --repo-root "$(pwd)" dashboard start --port 9123
# Open http://127.0.0.1:9123 → Wikis tab
```

## Architecture

### Markdown is Authoritative

Wiki pages are plain `.md` files with YAML frontmatter. SQLite (`wiki.db`) is a **rebuildable projection** — if it disagrees with the markdown files, the files win and the projection is rebuilt.

```yaml
---
id: concepts/attention-mechanism
title: Attention Mechanism
type: concept
tags: [transformers, nlp, attention]
sources: [raw/papers/vaswani-2017.pdf]
confidence: high
author: claude-opus-4.8
author_kind: agent
---

# Attention Mechanism
...
```

### Storage Layer

```
~/.hermes/wikis/<slug>/
├── .git/              # Per-wiki git repository
├── wiki.db            # Rebuildable FTS5 projection (gitignored)
├── SCHEMA.md          # Domain contract, taxonomy, update policy
├── index.md           # Page catalog
├── log.md             # Attributed action log
├── raw/
│   ├── inbox/         # Drop zone for unprocessed sources
│   ├── articles/
│   └── papers/
├── entities/          # Entity pages
├── concepts/          # Concept pages
├── comparisons/       # Comparison pages
└── sources/           # Curated source summary pages
```

### Processing Pipeline

```
raw/inbox/ → [Classifier] → label → [Processor] → Wiki Pages → [Propagator] → git commit
                                                                      ↓
                                                              wiki.db + index.md + log.md
```

Built-in classifiers: `article`, `paper`, `transcript`, `image`, `audio`, `code-snippet`.
Custom classifiers/processors require explicit trust (`hermes-wiki plugins trust`).

### Adapter Architecture

The package is **standalone-first** with typed Protocol seams:

| Adapter | Use Case |
|---------|----------|
| `adapters/standalone/` | Default — runs without Hermes installed |
| `adapters/hermes/` | Wires into a real Hermes deployment (CLI registration, cron, prompt injection) |

## CLI Reference

```bash
# Wiki management
hermes-wiki create <slug>              # Create a new wiki
hermes-wiki list                       # List visible wikis
hermes-wiki show <slug>                # Wiki summary and stats
hermes-wiki switch <slug>              # Set as current wiki for this profile
hermes-wiki archive <slug>             # Hide from discovery (reversible)

# Content
hermes-wiki ingest <path|url>          # Ingest a source
hermes-wiki ingest --inbox             # Process all inbox items
hermes-wiki search <query>             # BM25 full-text search
hermes-wiki open <page-id>             # Read a page
hermes-wiki create-page <title>        # Author a new page
hermes-wiki list-pages                 # List pages (filterable)

# Maintenance
hermes-wiki lint                       # Run health checks
hermes-wiki log                        # View activity log
hermes-wiki plugins list               # Show classifiers/processors

# Kanban integration
hermes-wiki link <page-id> <task-id>   # Link page to kanban task
hermes-wiki refs <page-id>             # Show linked tasks
```

See `hermes-wiki <command> --help` for full options.

## Agent Tools

When running inside Hermes, agents discover wikis via system prompt injection and use typed tools:

| Tool | Access | Description |
|------|--------|-------------|
| `wiki_list` | Read | List visible wikis or pages |
| `wiki_search` | Read | FTS5 search across visible wikis |
| `wiki_show` | Read | Full page content with metadata |
| `wiki_health_check` | Read | Lint report |
| `wiki_inbox` | Read | Unprocessed inbox items |
| `wiki_ingest` | Write | Run ingest pipeline |
| `wiki_create_page` | Write | Create/update a page |
| `wiki_link_kanban` | Write | Link page to kanban task |

Write tools require a write grant (profile config, `HERMES_WIKI` env, or `wiki` toolset).

## Dashboard

The dashboard is a React 19 plugin tab (`/wikis`) inside the Hermes dashboard, built with `@nous-research/ui`.

**Views:** Wiki Landing | Wiki Detail | Page View | Search | Inbox | Health | Activity Log

**Backend:** FastAPI router at `/api/plugins/wiki/*` with session-token auth.

```bash
# Build and run
cd dashboard && npm install && npm run build && cd ..
uv run python -m hermes_wiki.harness --repo-root "$(pwd)" dashboard start --port 9123
```

## How This Implements Karpathy's LLM Wiki

| Karpathy Concept | Hermes Wiki Implementation |
|------------------|---------------------------|
| Raw sources (immutable) | `raw/` directory with append-only snapshots, sha256 provenance |
| LLM-maintained wiki pages | `entities/`, `concepts/`, `comparisons/`, `sources/` — agent-curated markdown |
| Schema / CLAUDE.md | `SCHEMA.md` per wiki — domain contract, taxonomy, propagation rules |
| Index | `index.md` — sectioned page catalog |
| Log | `log.md` — append-only attributed action record |
| Ingest operation | `hermes-wiki ingest` — classifies, processes, cross-links, commits |
| Query operation | `hermes-wiki search` / `wiki_search` tool — BM25 FTS5 ranked |
| Lint operation | `hermes-wiki lint` — 18 health checks for contradictions, staleness, orphans |
| Knowledge compounds | Each ingest updates related pages, not just the new source's page |
| Human curates sources, LLM does the rest | Agents ingest, synthesize, cross-link; humans drop sources in inbox |

## Development

```bash
uv run pytest              # Run tests
uv run ruff check .        # Lint
uv run ty check            # Type check (pinned to 0.0.44)
cd dashboard && npm run build   # Build dashboard
```

## Project Layout

```
hermes_wiki/        Core: ingest pipeline, projection, search, lint, attribution, tools, harness
hermes_wiki_cli/    Console entrypoint (argument parsing + dispatch)
adapters/           Protocol seams: standalone (default) and hermes implementations
dashboard/          React 19 plugin: src/, dist/, manifest.json, plugin_api.py
fixtures/           Test data factory and seed sources
tests/              Behavioral test suite
```

## Why Hermes Wiki?

- **Knowledge compounds** — each ingestion enriches the entire wiki, not just one answer
- **Markdown is authoritative** — no vendor lock-in; SQLite is a rebuildable projection
- **Full attribution** — every change tracked to agent, profile, human, or cron job
- **Privacy by default** — invisible wikis never leak their names
- **Standalone-first** — runs without Hermes installed; adapters wire into real deployments
- **18 health checks** — automated lint catches broken links, stale content, orphan pages

## FAQ

### What is an LLM Wiki?

An LLM Wiki is a domain-scoped knowledge base where AI agents compile, cross-reference, and maintain durable knowledge from human-curated sources. Unlike traditional RAG (which retrieves document chunks at query time), an LLM Wiki has agents incrementally build structured, interlinked pages that persist and compound over time.

### How does Hermes Wiki differ from RAG?

RAG retrieves document chunks at query time — the LLM rediscovers knowledge from scratch on every question. Hermes Wiki instead has agents ingest sources into structured wiki pages with cross-references, contradictions flagged, and provenance tracked. Knowledge accumulates rather than being forgotten between sessions.

### What is the Karpathy Pattern?

The Karpathy Pattern refers to [Andrej Karpathy's LLM Wiki concept](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f): immutable raw sources are ingested by an LLM into agent-curated, interlinked wiki pages governed by a schema, index, and log. The human curates sources and asks questions; the LLM handles synthesis, cross-referencing, and maintenance.

### Do I need Hermes installed to use this?

No. Hermes Wiki is standalone-first. The `hermes-wiki` CLI works independently. The `adapters/hermes/` layer wires it into a full Hermes deployment when available, enabling agent tools, slash commands, and dashboard integration.

### What storage does Hermes Wiki use?

Markdown files with YAML frontmatter are the source of truth. Each wiki has its own git repository. A SQLite database with FTS5 provides full-text search, but it is a rebuildable projection — if markdown and SQLite disagree, the files win.

### How does the ingest pipeline work?

Sources are classified (article, paper, transcript, etc.), processed into one or more wiki pages, propagated to update cross-references and the index, then committed to git with full attribution. Custom classifiers and processors can be added per-wiki with explicit trust gating.

### Can multiple agents share a wiki?

Yes. Wikis are profile-scoped with configurable visibility (whitelist/blacklist). Multiple agents can read and search any visible wiki. Write access requires explicit grants. Each agent's contributions are attributed separately.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding standards, and PR guidelines.

## License

[MIT](LICENSE) — Hermes Wiki contributors

---

<p align="center">
  <sub>Implements <a href="https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f">Karpathy's LLM Wiki pattern</a> for the <a href="https://github.com/nous-research/hermes">Hermes Agent</a></sub>
</p>
