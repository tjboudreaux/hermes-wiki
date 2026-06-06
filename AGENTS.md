# Hermes Wiki — Agent Instructions

## Project Overview

Hermes Wiki is a Python package implementing Karpathy's LLM Wiki pattern for the Hermes Agent. It provides persistent, compounding knowledge bases where AI agents ingest sources, curate interlinked wiki pages, and maintain knowledge over time.

The codebase follows a layered architecture: core package (`hermes_wiki/`), CLI entrypoint (`hermes_wiki_cli/`), typed adapter seams (`adapters/`), and a React 19 dashboard plugin (`dashboard/`).

## Tech Stack

- **Language**: Python 3.11+ (backend), TypeScript/React 19 (dashboard)
- **Package Manager**: uv (Python), npm (dashboard)
- **Test Framework**: pytest
- **Linter**: ruff (line-length 100, rules: B, E, F, I, RUF, UP)
- **Type Checker**: ty 0.0.44
- **Build**: hatchling (Python), esbuild (dashboard IIFE bundle)
- **Database**: SQLite with FTS5 (rebuildable projection)

## Commands

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest

# Lint
uv run ruff check .

# Type check
uv run ty check

# Run CLI
uv run hermes-wiki --help
uv run hermes-wiki create <slug> --domain <description>
uv run hermes-wiki ingest <path|url> --wiki <slug>
uv run hermes-wiki search <query> --wiki <slug>
uv run hermes-wiki lint --wiki <slug>

# Dashboard
cd dashboard && npm install && npm run build

# Isolated test environment
uv run python -m hermes_wiki.harness --repo-root "$(pwd)" init
uv run python -m hermes_wiki.harness --repo-root "$(pwd)" dashboard start --port 9123
uv run python -m hermes_wiki.harness --repo-root "$(pwd)" dashboard stop --port 9123
```

## Project Structure

```
hermes_wiki/        Core package: ingest pipeline, projection (wiki.db), search, lint,
                    attribution, visibility, kanban linkage, monitors, tools, slash, harness
hermes_wiki_cli/    The `hermes-wiki` console entrypoint (argument parsing + dispatch)
adapters/           Typed Protocol seams (base.py) with standalone and hermes implementations
  standalone/       Default adapter — runs without Hermes installed
  hermes/           Wires into real Hermes deployment (CLI, cron, prompt injection, tools)
dashboard/          React 19 plugin tab for Hermes dashboard
  src/              TypeScript source (esbuild IIFE, React externalized)
  dist/             Built plugin bundle (index.js + style.css)
  manifest.json     Plugin registration manifest
  plugin_api.py     FastAPI backend router
fixtures/           Test data factory (build_populated_home / build_clean_home) + seed sources
tests/              Behavioral test suite (pytest)
```

## Architecture Principles

- **Markdown is authoritative** — wiki pages are `.md` files with YAML frontmatter; SQLite is a rebuildable projection
- **Raw sources are append-only** — immutable evidence; changes create new snapshots
- **Attribution on every write** — `author` + `author_kind` in frontmatter, SQLite, and git commit
- **Adapters isolate integration** — `adapters/base.py` defines Protocol seams; implementations never cross boundaries
- **Trust before execute** — custom classifiers/processors need explicit trust (path + sha256)
- **Privacy without disclosure** — invisible wikis return "not found or not visible"
- **Kanban is read-only** — wiki owns linkage in frontmatter; never writes kanban.db

## Code Style

- Type hints on all function signatures
- Line length: 100 characters
- Ruff rules: B (bugbear), E (pycodestyle), F (pyflakes), I (isort), RUF, UP (pyupgrade)
- Target version: Python 3.11
- No unnecessary comments — code should be self-documenting
- Use `from __future__ import annotations` in all modules

## Testing

- All tests in `tests/` directory
- Fixtures in `fixtures/` provide `build_populated_home()` and `build_clean_home()`
- Tests use isolated homes (never touch `~/.hermes`)
- Run full suite before commits: `uv run pytest`
- Current: 160 tests passing

## Domain Language

See `CONTEXT.md` for the canonical glossary. Key terms:
- **LLM Wiki** — the domain-scoped knowledge base
- **Raw Source** — immutable source material (never rewritten)
- **Wiki Page** — agent-curated knowledge (mutable synthesis)
- **Schema** — domain contract (SCHEMA.md)
- **Projection** — rebuildable SQLite view
- **Ingest** — classify → process → propagate → commit pipeline
- **Surface** — CLI, tool, slash command, or dashboard view

## Boundaries

- **Always**: Run `uv run pytest` and `uv run ruff check .` before commits
- **Always**: Follow the adapter pattern for any Hermes integration code
- **Always**: Attribute changes with `author` and `author_kind`
- **Ask first**: New dependencies, schema changes, new adapter seams
- **Never**: Modify raw sources after ingest
- **Never**: Write to kanban.db from wiki code
- **Never**: Execute untrusted plugin code without explicit trust verification
- **Never**: Expose wiki names for invisible/private wikis in error messages
