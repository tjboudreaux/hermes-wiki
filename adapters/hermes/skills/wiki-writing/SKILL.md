---
name: wiki-writing
description: "Write and curate Hermes LLM Wiki pages: page types, required frontmatter, taxonomy tags, cross-linking, attribution, synthesis/dedup/contradiction protocol, and index/log propagation rules."
version: 1.1.0
license: MIT
metadata:
  hermes:
    tags: [Wiki, Writing, Curation, Knowledge]
    related_skills: [wiki-commands, wiki-ingestion]
    upstream_skill: research-llm-wiki
    upstream_skill_version: "2.1.0"
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

## Synthesis protocol

Quality rules for what gets written, adapted from the upstream
`research-llm-wiki` skill (see `upstream_skill_version` in this file's
metadata) to this wiki's conventions.

### Page-creation threshold (dedup)

- Create a page when an entity or concept appears in **2+ sources OR is
  central to one source**. Do not create pages for passing mentions, minor
  details, or topics outside the wiki's domain.
- Before creating, search (`hermes wiki search "<title>"`) for the title and
  close variants. If a similar page exists, extend it — never duplicate.

### Contradiction protocol

When new information conflicts with an existing page:

1. Check dates — newer sources generally supersede older ones. Update the
   claim, citing both source pages with their dates, and keep any slice of
   the older claim that still holds.
2. If genuinely contradictory (no clear recency winner), record both
   positions in the body with dates and sources.
3. Set `contested: true` and record the conflicting page id(s) in the
   `contradictions:` frontmatter field. Lint surfaces this for review
   (`unresolved_contested`) until a human or agent resolves it.

Never silently merge conflicting claims or pick a winner without
justification.

### Provenance

- On pages synthesizing **3+ sources**, end each paragraph whose claims come
  from one specific source with a relative link to that source page, e.g.
  `([source](../sources/2026-06-06-some-article.md))`.
- Single-source pages rely on the frontmatter `sources:` field.
- Hedge weakly supported claims in the body ("field reports suggest…") and
  set `confidence:` to honestly reflect sourcing strength — single anecdotal
  sourcing is `low`, not `high`.

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

## Self-check before committing

Verify before every durable write:

- [ ] Every claim is traceable to a page listed in `sources:` — nothing the
      sources do not support, no upgraded certainty.
- [ ] The page-creation threshold is met (2+ sources or central to one), and
      a search confirmed no existing page already covers this subject.
- [ ] Conflicts with existing pages followed the contradiction protocol —
      nothing silently merged.
- [ ] `confidence` honestly reflects sourcing strength.
- [ ] Tags come from the Schema taxonomy, links resolve, and the body stays
      within `page_line_limit`.

If any item fails, fix the page and re-check before writing.
