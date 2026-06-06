---
layout: default
title: Agent Tools
description: Using Hermes Wiki from agent conversations — search, show, ingest, and create pages
---

# Agent Tools

When running inside Hermes, agents discover wikis automatically and use typed tools in conversation.

## Discovery

At session start, the prompt builder injects a `# Available Wikis` block listing visible wikis with their domains, page counts, and health scores. Agents use `wiki_search` when a question is domain-relevant.

```
# Available Wikis
You have access to the following knowledge bases:
- ai-tooling: AI agents, coding tools, research (89 pages, health 0.88)
```

## Read Tools

Available to all profiles for all visible wikis.

### `wiki_list(wiki=None)`

List visible wikis (when `wiki=None`) or pages in a specific wiki.

### `wiki_search(query, wiki=None, limit=5)`

BM25-ranked full-text search. When `wiki=None`, searches across all visible wikis.

### `wiki_show(page_id, wiki=None)`

Returns full page content, YAML frontmatter, and linked kanban tasks.

### `wiki_health_check(wiki=None)`

Returns the lint report as structured JSON.

### `wiki_inbox(wiki=None)`

Lists unprocessed inbox files with their classifier suggestions.

## Write Tools

Require a write grant: profile must have `wiki` toolset enabled, the target wiki in `write_grants`, or `HERMES_WIKI` env set to the target slug.

### `wiki_ingest(path_or_url=None, wiki=None, classifier=None, inbox=False)`

Run the ingest pipeline for one source or (with `inbox=True`) the entire inbox. Exactly one of `path_or_url` or `inbox=True` is required.

### `wiki_create_page(title, body, type, tags, sources, wiki=None)`

Create or update a page with full frontmatter and attribution.

### `wiki_link_kanban(page_id, task_id, wiki=None)`

Create a wiki-owned reference between a page and a kanban task. Updates frontmatter and the `wiki.db:kanban_refs` projection. Never writes to `kanban.db`.

## Write Gating Logic

```python
def _check_wiki_write_mode(wiki: str | None) -> bool:
    # 1. HERMES_WIKI env matches target
    # 2. Profile has 'wiki' toolset enabled
    # 3. Target slug is in profile's write_grants
    # 4. write_grants contains "*"
```

## Slash Command

The `/wiki` slash command forwards to the CLI surface inside a session:

```
/wiki search "transformer architecture"
/wiki ingest https://example.com/paper
/wiki lint
```

## Privacy Model

- Agents only see wikis their profile is authorized to discover
- Invisible wikis return "not found or not visible" (never leak names)
- Write access requires explicit grants beyond read/discovery
- Private wikis (marked in SCHEMA.md) are invisible to all profiles unless whitelisted
