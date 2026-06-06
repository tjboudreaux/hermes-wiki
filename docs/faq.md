---
layout: default
title: FAQ
description: Frequently asked questions about Hermes Wiki — LLM wikis, RAG comparison, installation, and usage
---

# Frequently Asked Questions

## General

### What is Hermes Wiki?

Hermes Wiki is a Python package that gives AI agents persistent, compounding knowledge bases. It implements Karpathy's LLM Wiki pattern for the Hermes Agent: agents ingest sources, synthesize interlinked wiki pages, and maintain knowledge over time.

### What is an LLM Wiki?

An LLM Wiki is a domain-scoped knowledge base where AI agents compile, cross-reference, and maintain durable knowledge from human-curated sources. Unlike traditional document stores, the knowledge compounds — each ingestion enriches the entire wiki, not just one document.

### What is the Karpathy Pattern?

The Karpathy Pattern refers to Andrej Karpathy's LLM Wiki concept (published April 2026): immutable raw sources are ingested by an LLM into agent-curated, interlinked wiki pages governed by a schema, index, and log. The human curates sources and asks questions; the LLM handles synthesis, cross-referencing, and maintenance.

### How does Hermes Wiki differ from RAG?

| | Traditional RAG | Hermes Wiki (LLM Wiki) |
|---|---|---|
| **Knowledge** | Retrieved per-query, forgotten between sessions | Persistent, compounding over time |
| **Structure** | Flat document chunks | Interlinked pages with types, tags, cross-references |
| **Maintenance** | None — stale chunks accumulate | Active — lint detects staleness, drift, contradictions |
| **Attribution** | None | Every change tracked to agent/profile/human/cron |
| **Provenance** | Document → chunk | Source snapshot → curated page with citations |

## Installation

### What are the requirements?

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Node.js + npm (for the dashboard plugin only)
- An OpenRouter API key for LLM-backed features

### Do I need Hermes installed?

No. Hermes Wiki is standalone-first. The `hermes-wiki` CLI works without Hermes. When Hermes is available, the `adapters/hermes/` layer enables agent tools, slash commands, prompt injection, and dashboard integration.

### How do I install it?

```bash
git clone https://github.com/hermes-wiki/hermes-wiki.git
cd hermes-wiki
uv sync
uv run hermes-wiki --help
```

## Usage

### How do I create a wiki?

```bash
uv run hermes-wiki create ai-tooling --domain "AI agents and coding tools"
uv run hermes-wiki switch ai-tooling
```

### How does ingestion work?

Sources are classified (article, paper, transcript, etc.), processed into wiki pages, cross-linked with existing pages, and committed to git with attribution:

```bash
uv run hermes-wiki ingest https://example.com/article --wiki ai-tooling
```

### Can multiple agents share a wiki?

Yes. Wikis are profile-scoped with configurable visibility. Multiple agents can read and search any visible wiki. Write access requires explicit grants per profile.

### What storage does Hermes Wiki use?

Markdown files with YAML frontmatter are the source of truth. Each wiki has its own git repository. SQLite with FTS5 provides full-text search as a rebuildable projection.

## Architecture

### What does "markdown is authoritative" mean?

Wiki pages are `.md` files with YAML frontmatter. The SQLite database (`wiki.db`) is a computed index derived from those files. If they disagree, the files win and the database is rebuilt.

### How are raw sources handled?

Raw sources are append-only and immutable. When an external URL changes, a new source snapshot is created — the original is never modified. Wiki pages cite specific snapshots.

### What classifiers are built in?

Article, paper, transcript, image, audio, and code-snippet. Custom classifiers can be added per-wiki but require explicit trust (path + sha256 verification) before execution.

### How does privacy work?

Profiles configure wiki visibility with whitelist/blacklist rules. Invisible wikis return "not found or not visible" — they never leak their names in prompts, tool outputs, or error messages.

## Dashboard

### How do I run the dashboard?

```bash
cd dashboard && npm install && npm run build && cd ..
uv run python -m hermes_wiki.harness --repo-root "$(pwd)" dashboard start --port 9123
```

Open http://127.0.0.1:9123 and click the Wikis tab.

### What views does the dashboard have?

Wiki Landing, Wiki Detail, Page View, Search, Inbox, Health (lint report), and Activity Log. All views use the `@nous-research/ui` dark theme component library.
