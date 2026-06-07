---
layout: default
title: The Karpathy Pattern
description: How Hermes Wiki implements Andrej Karpathy's LLM Wiki concept for persistent, compounding knowledge
---

# The Karpathy Pattern

## Background

In April 2026, [Andrej Karpathy published a gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) describing a pattern for building personal knowledge bases using LLMs. The core insight:

> Most people's experience with LLMs and documents looks like RAG: you upload a collection of files, the LLM retrieves relevant chunks at query time, and generates an answer. This works, but the LLM is rediscovering knowledge from scratch on every question. There's no accumulation.

The solution: instead of per-query retrieval, have the LLM **incrementally build and maintain a persistent wiki**.

## The Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1: Raw Sources (Immutable)                       │
│                                                         │
│  Articles, papers, transcripts, images, data files.     │
│  The LLM reads these but NEVER modifies them.           │
│  Append-only — external changes create new snapshots.   │
└─────────────────────────────┬───────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 2: The Wiki (LLM-Maintained)                     │
│                                                         │
│  Summaries, entity pages, concept pages, comparisons.   │
│  Cross-referenced, with contradictions flagged.         │
│  Human reads; LLM writes and maintains.                 │
└─────────────────────────────┬───────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 3: Schema (Configuration)                        │
│                                                         │
│  Defines wiki structure, conventions, workflows.        │
│  Co-evolved over time as the wiki grows.                │
└─────────────────────────────────────────────────────────┘
```

## Key Operations

### Ingest
Add a source → LLM reads it, writes a summary page, updates the index, updates related existing pages. A single source may touch 10-15 wiki pages.

### Query
Ask a question → LLM searches the wiki, reads relevant pages, synthesizes an answer with citations. Good answers can be filed back into the wiki.

### Lint
Periodic health check for contradictions, stale claims, orphan pages, missing cross-references.

## How Hermes Wiki Implements This

| Karpathy Concept | Hermes Wiki Implementation |
|------------------|---------------------------|
| Raw sources (immutable) | `raw/` directory with append-only snapshots, sha256 provenance, drift detection |
| LLM-maintained wiki pages | `entities/`, `concepts/`, `comparisons/`, `sources/` — markdown with YAML frontmatter |
| Schema / CLAUDE.md | `SCHEMA.md` per wiki — domain contract, taxonomy, page thresholds, propagation rules |
| Index | `index.md` — sectioned page catalog with one-line summaries |
| Log | `log.md` — append-only attributed action record |
| Ingest operation | `hermes-wiki ingest` — pluggable classify → process → propagate → commit pipeline |
| Query operation | `hermes-wiki search` / `wiki_search` tool — BM25 FTS5 ranked results |
| Lint operation | `hermes-wiki lint` — 19 automated health checks |
| Knowledge compounds | Propagation rules update related pages on every ingest |
| Human curates sources | Humans drop sources in `raw/inbox/`; agents do the rest |

## What Hermes Wiki Adds Beyond the Pattern

Karpathy's gist describes the conceptual pattern. Hermes Wiki makes it operational:

| Capability | Description |
|---|---|
| **Multi-wiki** | Multiple domain-scoped wikis with independent schemas |
| **Attribution** | Every change tracked to agent, profile, human, or cron job |
| **Privacy** | Profile-scoped visibility with whitelist/blacklist |
| **Agent integration** | Tools injected into agent system prompts; agents use wikis in conversation |
| **Dashboard** | Web UI for browsing, searching, and managing wikis |
| **Kanban linkage** | Bidirectional wiki-page ↔ task references |
| **Pluggable pipeline** | Custom classifiers and processors with trust gating |
| **Monitors** | Automated source sweeps (arxiv, RSS, URLs) via cron |
| **Projection versioning** | SQLite rebuilds are versioned for triage |
| **Standalone-first** | Runs without Hermes installed; adapters wire into real deployments |

## Philosophy

> The human's job is to curate sources, direct the analysis, ask good questions, and think about what it all means. The LLM's job is everything else.
>
> — Andrej Karpathy

Hermes Wiki embodies this division of labor. Humans choose what to learn about (drop sources, ask questions). Agents handle the mechanical work of synthesis, cross-referencing, indexing, and maintenance.
