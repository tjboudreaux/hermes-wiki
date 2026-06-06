# Contributing to Hermes Wiki

## Development Setup

```bash
git clone https://github.com/hermes-wiki/hermes-wiki.git
cd hermes-wiki
uv sync
```

### Run Tests

```bash
uv run pytest              # Full test suite
uv run ruff check .        # Lint
uv run ty check            # Type check
```

### Dashboard Development

```bash
cd dashboard
npm install
npm run build
```

## Code Style

- Python: Ruff with `line-length = 100`, target Python 3.11
- Lint rules: `B, E, F, I, RUF, UP`
- TypeScript/React: esbuild, React 19 externalized via Plugin SDK

## Architecture Conventions

- **Markdown is authoritative** — SQLite is a rebuildable projection
- **Raw sources are append-only** — never overwrite, create new snapshots
- **Attribution on every write** — `author` + `author_kind` in frontmatter, SQLite, and git commit
- **Adapters isolate integration** — `adapters/base.py` defines Protocol seams; standalone and hermes implement them
- **Trust before execute** — custom classifiers/processors need explicit trust (path + sha256)

## Pull Request Process

1. Create a feature branch from `main`
2. Write tests for new behavior
3. Ensure `uv run pytest`, `uv run ruff check .`, and `uv run ty check` pass
4. Keep commits focused and well-described
5. Reference any related issues

## Project Structure

```
hermes_wiki/        Core package
hermes_wiki_cli/    CLI entrypoint
adapters/           Protocol seams (standalone + hermes)
dashboard/          React 19 plugin
fixtures/           Test data
tests/              Test suite
```

## Domain Language

See [CONTEXT.md](CONTEXT.md) for the canonical glossary. Use the defined terms in code, comments, and docs.
