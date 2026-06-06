# Hermes Wiki Plugin

The Hermes Wiki Plugin gives Hermes agents Karpathy-style, LLM-maintained wikis: living
knowledge bases that agents ingest sources into, organize into pages, search, and link to work.
It is a standalone, integration-ready Python package — markdown is the authoritative store, a
SQLite projection (`wiki.db`) makes it queryable, and every change is attributed and committed.
It is meant for teams running Hermes agents who want durable, auditable, agent-owned documentation
alongside the CLI, agent tools, and a dashboard.

The package is standalone-first: it ships its own `hermes-wiki` console command and runs without a
Hermes install, while thin adapter seams let it wire into a real Hermes deployment.

## Features

- **CLI** — the standalone `hermes-wiki` console command (functionally the `hermes wiki ...`
  surface). Verbs: `create`, `list`, `show`, `switch`, `archive`, `unarchive`, `ingest`, `search`,
  `open`, `list-pages`, `create-page`, `inbox`, `log`, `link`, `unlink`, `refs`, `lint`,
  `plugins` (`list`/`trust`/`untrust`), `monitor`, `purge`.
- **Agent tools + slash command** — read tools (`wiki_list`, `wiki_search`, `wiki_show`,
  `wiki_health_check`, `wiki_inbox`) and write tools (`wiki_ingest`, `wiki_create_page`,
  `wiki_link_kanban`). Writes are gated by a visibility-before-write-grant check, and a
  `# Available Wikis` block is injected into the agent's system prompt. A `/wiki` slash command runs
  the CLI surface inside a session.
- **Dashboard plugin** — a React 19 + `@nous-research/ui` plugin (esbuild IIFE; React is supplied by
  the Hermes Plugin SDK rather than bundled). It serves `/api/plugins/wiki/*` (FastAPI) and renders
  views at `/wikis`, `/wikis/<slug>`, `/wikis/<slug>/<page_id>`, plus search, inbox, health, and
  activity. See `dashboard/README.md`.
- **Adapters** — `adapters/standalone/` (default) and `adapters/hermes/` (real Hermes wiring) sit
  behind typed Protocol seams: config, home resolution, kanban-read, cron, tool-registry,
  prompt-injection, and dashboard-loader.

## Architecture at a glance

- **Markdown is authoritative.** Pages are markdown files with frontmatter; `wiki.db` is a
  rebuildable projection (`lint` repairs/rebuilds it) and is gitignored.
- **Raw sources are append-only.** Ingested sources are preserved verbatim and never rewritten.
- **Attribution + history.** Every action is attributed (`agent`/`profile`/`human`/`cron`) and
  recorded; changes are committed to git.
- **Privacy without disclosure.** Invisible wikis return `not found or not visible` rather than
  acknowledging their existence.
- **Read/write separation.** Read tools cross all visible wikis; write tools require an explicit
  write grant and a current/`HERMES_WIKI`-scoped target.
- **Kanban is read-only.** The wiki owns linkage (frontmatter + `wiki.db:kanban_refs`); it never
  writes `kanban.db`.
- **Trust before execute.** Custom classifier/processor code runs only when trusted by path +
  sha256.

For full product behavior and domain language, see `SPEC.md` and `CONTEXT.md`.

## Requirements

- Python `>=3.11,<3.14` and [uv](https://docs.astral.sh/uv/).
- Node.js + npm (for building the dashboard plugin only).
- An **OpenRouter API key** (`OPENROUTER_API_KEY`) for LLM-backed features. A direct Anthropic key is
  not used or required — LLM calls are routed through OpenRouter.

## Install / setup

```bash
uv sync
```

LLM features read credentials (including `OPENROUTER_API_KEY`) from the active Hermes home's `.env`.
The project follows an **isolated home** convention: set `HERMES_HOME` to a repo-local directory so
all wiki state, config, and credentials live there instead of touching `~/.hermes`. The bundled
harness can seed an isolated home and its `.env`:

```bash
# Create an isolated home at <repo>/.hermes-test and seed its .env from ~/.hermes/.env
uv run python -m hermes_wiki.harness --repo-root "$(pwd)" init
```

All CLI examples below assume `HERMES_HOME` points at such a home, e.g.:

```bash
export HERMES_HOME="$(pwd)/.hermes-test"
```

## Usage

### CLI

Run any verb with `uv run hermes-wiki ...` (against the chosen `HERMES_HOME`):

```bash
# Create a wiki and make it current
uv run hermes-wiki create ai-tooling --domain "AI tooling notes"
uv run hermes-wiki switch ai-tooling

# Ingest a source (local path or http(s) URL) and search the projection
uv run hermes-wiki ingest https://example.com/article --wiki ai-tooling
uv run hermes-wiki search "attention mechanism" --wiki ai-tooling --limit 5

# Author a page, then list pages by type/tag
uv run hermes-wiki create-page "Transformer architecture" \
  --body "..." --type concept --tag transformers
uv run hermes-wiki list-pages --wiki ai-tooling --type concept

# Lint / rebuild the projection and report health
uv run hermes-wiki lint --wiki ai-tooling

# Link a page to a (read-only) kanban task; linkage is wiki-owned
uv run hermes-wiki link concepts/transformer-architecture KB-123 --wiki ai-tooling

# List visible wikis (add --archived to include archived ones)
uv run hermes-wiki list
```

### Agent tools / slash command

The read and write tool functions live in `hermes_wiki.tools` (`READ_TOOLS` / `WRITE_TOOLS`). They
are registered with the host through the adapter's tool-registry seam; the prompt-injection seam adds
the `# Available Wikis` block to the agent's system prompt so it discovers visible wikis. Write tools
are gated by `_check_wiki_write_mode` (target must match `HERMES_WIKI`/current wiki, the `wiki`
toolset must be enabled for the profile, and the slug must be in the profile's write grants). The
`/wiki` slash command (`adapters/hermes/wiki_plugin.py` → `hermes_wiki.slash.run_slash`) runs the CLI
surface inside a session.

### Dashboard

Build the plugin and run an isolated dashboard via the harness (port and home come from the
project's `services.yaml` conventions — do not point this at the live dashboard):

```bash
# Build the plugin bundle (dist/index.js + dist/style.css)
cd dashboard && npm install && npm run build && cd ..

# Start / stop an isolated dashboard on port 9123 against <repo>/.hermes-test
uv run python -m hermes_wiki.harness --repo-root "$(pwd)" dashboard start --port 9123
uv run python -m hermes_wiki.harness --repo-root "$(pwd)" dashboard stop  --port 9123
```

See `dashboard/README.md` for the plugin install path, endpoints, and verification details.

## Development

```bash
uv run pytest             # tests
uv run ruff check .       # lint
uv run ty check           # typecheck
cd dashboard && npm install && npm run build   # dashboard build
```

(`ty` is pinned to `0.0.44` in `pyproject.toml` because it is a pre-release and volatile.)

## Integration with Hermes

The package is **standalone-first**. The `adapters/standalone/` bundle is the default (selected via
`HERMES_WIKI_ADAPTER`, falling back to `standalone`); `adapters/hermes/` wires the same seams to a
real Hermes install (CLI registration, read-only kanban, isolated cron, prompt injection, tool
registry, dashboard loader).

Registering the top-level `hermes wiki` CLI inside an installed Hermes is a **deferred integration
step**. The supported surface today is the standalone `hermes-wiki` entrypoint, which is functionally
identical to the `hermes wiki ...` command described in the spec.

## Project layout

```
hermes_wiki/        Core package: ingest pipeline, projection (wiki.db), search, lint,
                    attribution, visibility, kanban linkage, monitors, tools, slash, harness.
hermes_wiki_cli/    The `hermes-wiki` console entrypoint (argument parsing + dispatch).
adapters/           Typed seams (base.py) with standalone (default) and hermes implementations.
dashboard/          React 19 dashboard plugin: src/, build output dist/, manifest.json, plugin_api.py.
fixtures/           Test-data factory (build_populated_home / build_clean_home) and seed sources.
tests/              Behavioral test suite.
SPEC.md             Product behavior specification (source of truth).
CONTEXT.md          Domain glossary and design context.
```

## Reference

- `SPEC.md` — full product behavior specification.
- `CONTEXT.md` — domain glossary and design context.
