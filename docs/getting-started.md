---
layout: default
title: Getting Started
description: Install Hermes Wiki, create your first LLM wiki, and ingest your first source
---

# Getting Started

## Requirements

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Node.js + npm (dashboard only)
- An [OpenRouter API key](https://openrouter.ai/) for LLM-backed features

## Installation

```bash
git clone https://github.com/hermes-wiki/hermes-wiki.git
cd hermes-wiki
uv sync
```

Verify:

```bash
uv run hermes-wiki --help
```

## Setting Up an Isolated Home

For development and testing, use an isolated Hermes home instead of your live `~/.hermes`:

```bash
uv run python -m hermes_wiki.harness --repo-root "$(pwd)" init
export HERMES_HOME="$(pwd)/.hermes-test"
```

This seeds API keys from your live environment into the isolated home.

## Create Your First Wiki

```bash
uv run hermes-wiki create ai-tooling --domain "AI agents and coding tools"
uv run hermes-wiki switch ai-tooling
```

## Ingest a Source

Drop a file in the inbox or ingest directly:

```bash
# Direct ingest from URL
uv run hermes-wiki ingest https://example.com/article --wiki ai-tooling

# Or ingest a local file
uv run hermes-wiki ingest ./paper.pdf --wiki ai-tooling

# Process all inbox items
uv run hermes-wiki ingest --inbox --wiki ai-tooling
```

The pipeline classifies the source, processes it into wiki pages, updates the index, and commits.

## Search Your Wiki

```bash
uv run hermes-wiki search "attention mechanism" --wiki ai-tooling --limit 5
```

## Check Health

```bash
uv run hermes-wiki lint --wiki ai-tooling
```

This runs 19 automated checks for broken links, orphan pages, stale content, and more.

## Start the Dashboard

```bash
cd dashboard && npm install && npm run build && cd ..
uv run python -m hermes_wiki.harness --repo-root "$(pwd)" dashboard start --port 9123
```

Open [http://127.0.0.1:9123](http://127.0.0.1:9123) and navigate to the Wikis tab.

## Next Steps

- [CLI Reference](cli-reference.md) — full command documentation
- [Agent Tools](agent-tools.md) — using wikis from agent conversations
- [Architecture](architecture.md) — how the storage and pipeline work
