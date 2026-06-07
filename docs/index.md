---
layout: default
title: Hermes Wiki
description: Karpathy-style LLM Wikis for the Hermes Agent — persistent, compounding knowledge bases curated by AI agents
---

# Hermes Wiki

Hermes Wiki implements [Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) as a production-ready plugin for the Hermes Agent. Instead of rediscovering knowledge on every query, agents **build and maintain persistent wikis** that compound knowledge over time.

## Why LLM Wikis?

Traditional RAG uploads documents and retrieves chunks at query time. The LLM never accumulates understanding. Karpathy's insight: LLMs should **curate**, not just retrieve.

With Hermes Wiki:
- Agents **ingest** sources into structured, cross-referenced wiki pages
- Knowledge **compounds** — each new source enriches the whole wiki
- Pages stay **current** via automated lint, monitors, and drift detection
- Everything is **attributed** and **git-committed**

## Quick Links

| | |
|---|---|
| [Getting Started](getting-started.md) | Install, create your first wiki, ingest a source |
| [CLI Reference](cli-reference.md) | Full command documentation |
| [Agent Tools](agent-tools.md) | Using wikis from Hermes agent conversations |
| [Architecture](architecture.md) | Storage, pipeline, adapters, privacy |
| [Hooks Architecture](hooks-architecture.md) | Per-wiki executable customization design |
| [Dashboard](dashboard.md) | Web UI setup and views |
| [Karpathy Pattern](karpathy-pattern.md) | How Hermes Wiki implements the LLM Wiki concept |
| [Quality Audit](quality-audit.md) | Audit findings and roadmap for evals, features, and test suites |
| [Media Ingestion Design](media-ingestion-design.md) | Decision record and build plan for multimodal ingestion |

## The Pattern

```
Raw Sources (immutable)     →  Ingest Pipeline  →  Wiki Pages (agent-curated)
articles, papers, transcripts   classify/process     entities, concepts, comparisons
                                                     cross-linked, attributed, versioned
```

Markdown is authoritative. SQLite is a rebuildable projection. Git tracks everything.
