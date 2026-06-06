---
name: wiki-writing
description: "Write and curate Hermes LLM Wiki pages: page types, required frontmatter, taxonomy tags, cross-linking, attribution, and index/log propagation rules."
version: 1.0.0
license: MIT
metadata:
  hermes:
    tags: [Wiki, Writing, Curation, Knowledge]
    related_skills: [wiki-commands, wiki-ingestion]
---

# Hermes Wiki Writing

This is the default writing skill for Hermes LLM Wikis. It describes how to
author and curate Wiki Pages that stay consistent with the wiki's Schema. A
wiki can override this default with `hermes wiki skills set writing <skill-name>`.

## Page types

Choose the narrowest type that fits (defined in each wiki's `SCHEMA.md`):

- `source` — curated summary of one immutable Source Snapshot (created by
  ingestion; rarely written by hand).
- `entity` — people, organizations, products, projects, concrete nouns.
- `concept` — ideas, methods, patterns, claims, mechanisms.
- `comparison` — structured tradeoffs between entities or concepts.
- `query` — a saved research question and its answer trail.
- `summary` — synthesized overview spanning multiple Wiki Pages.

## Creating a page

```bash
hermes wiki create-page "Page Title" \
  --body "Markdown body…" \
  --type concept \
  --tag <taxonomy-tag> \
  --source sources/<source-page-id> \
  [--wiki <slug>] [--author <name>] [--author-kind agent|profile|human|cron]
```

Requires a write grant. Re-running with the same title updates the page
(content merge, `updated` refresh) rather than duplicating it.

## Frontmatter contract

Every page carries YAML frontmatter; the required keys come from the wiki's
`SCHEMA.md` (`required_frontmatter`), by default:

```yaml
id: concepts/agent-memory      # <type-dir>/<slug>, stable forever
title: Agent Memory
type: concept
created: 2026-06-06T12:00:00Z
updated: 2026-06-06T12:00:00Z
author: <who wrote it>
author_kind: agent | profile | human | cron
sources: [sources/2026-06-06-some-article]
tags: [<taxonomy tags only>]
```

- `id` never changes once created — links depend on it.
- `sources` must reference real source pages; claims should trace to sources.
- `tags` must come from the wiki's Taxonomy section in `SCHEMA.md`. Propose a
  taxonomy edit rather than inventing ad-hoc tags.

## Body conventions

- Standard relative Markdown links only (`[Agent Memory](../concepts/agent-memory.md)`),
  no wiki-link syntax, no absolute paths, no bare URLs for internal references.
- Cross-link generously: when a page mentions another page's subject, link it.
- Respect the Schema's `page_line_limit` (default 200 lines) — split into
  multiple pages or a `summary` page instead of growing one page unboundedly.
- Page History does not belong in the body; it is rendered from log.md, git,
  and the projection.

## Propagation (what happens after a write)

Per the wiki's Propagation Rules, a durable page write also:

1. Updates the relevant `index.md` section (sectioned catalog).
2. Appends an attributed row to `log.md`.
3. Refreshes the SQLite projection (`wiki.db`).
4. Commits to the wiki-local git repo with the acting author.

The CLI/tool surfaces do this automatically — never skip them by editing
projection state directly. After manual bulk edits, run `hermes wiki lint` to
verify and repair.

## Kanban linkage

When a page motivates or tracks work, link it:

```bash
hermes wiki link <page-id> <task-id>
hermes wiki refs <page-id>
```

## Curation rules

- Update over duplicate: search first (`hermes wiki search`), then extend.
- Keep claims attributable: cite source pages, keep confidence honest.
- Comparisons need at least two real subject pages — link both.
- Archive superseded content into `_archive/` rather than deleting.
