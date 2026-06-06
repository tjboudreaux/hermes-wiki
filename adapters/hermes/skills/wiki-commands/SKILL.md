---
name: wiki-commands
description: "Operate Hermes LLM Wikis from the CLI or in-session: create, list, switch, search, open, lint, archive, link to kanban, and manage monitors, plugins, and skills."
version: 1.0.0
license: MIT
metadata:
  hermes:
    tags: [Wiki, Knowledge, CLI]
    related_skills: [wiki-ingestion, wiki-writing]
---

# Hermes Wiki Commands

Hermes LLM Wikis are persistent, curated, attributable knowledge bases following
Karpathy's LLM Wiki pattern. Markdown files and Raw Sources are authoritative;
SQLite projections are rebuildable support views.

All commands are available three ways:

- `hermes wiki <verb> …` — top-level Hermes CLI subcommand
- `/wiki <verb> …` — in-session slash command
- `hermes-wiki <verb> …` — standalone executable

## Resolving the target wiki

Most verbs accept `--wiki <slug>`. Without it, the profile-local current wiki is
used (set via `wiki switch <slug>`). Mutations additionally require a write
grant: `HERMES_WIKI=<slug>` in the environment, `wiki.write_grants` in
config.yaml, or the `wiki` toolset enabled.

## Lifecycle

```bash
hermes wiki create <slug> --domain "What this wiki covers"
hermes wiki list [--archived]
hermes wiki show [<slug>]
hermes wiki switch <slug>          # set the profile-local current wiki
hermes wiki archive <slug>         # reversible; never deletes files
hermes wiki unarchive <slug>
```

## Reading and searching

```bash
hermes wiki search "<fts query>" [--wiki <slug>] [--limit N]
hermes wiki open <page-id>         # print page Markdown, e.g. concepts/agent-memory
hermes wiki list-pages [--type <page-type>] [--tag <tag>]
hermes wiki log [--author <name>] [--kind agent|profile|human|cron] [--page <id>]
```

## Ingesting and writing

See the `wiki:wiki-ingestion` and `wiki:wiki-writing` skills for full workflows.

```bash
hermes wiki ingest <path-or-url>   # classify + snapshot + generate pages
hermes wiki ingest --inbox         # batch-process raw/inbox
hermes wiki inbox                  # list unprocessed inbox files
hermes wiki create-page "Title" --body "Markdown body" [--type concept] [--tag t]
```

## Health

```bash
hermes wiki lint                   # lint + repair the projection; prints JSON report
```

Exit code is 1 when the report status is `failed`.

## Kanban links

```bash
hermes wiki link <page-id> <task-id>
hermes wiki unlink <page-id> <task-id>
hermes wiki refs <page-id>         # tasks linked to a page
hermes wiki refs <task-id> --task  # pages linked to a task
```

## Monitors (recurring sweeps)

```bash
hermes wiki monitor --source arxiv|rss|x [--name n] [--schedule "0 9 * * 1"] [--prompt p] [--skill s]
hermes wiki monitor --setup --yes  # reconcile definitions into Hermes cron
hermes wiki monitor --sweep-url <url> [--name n]
```

Definitions are stored portably in the wiki's `SCHEMA.md`; cron scheduling is a
separate explicit reconcile.

## Custom plugins (trust before execute)

Custom classifier/processor code is never executed merely because a file exists.

```bash
hermes wiki plugins list
hermes wiki plugins trust classifier|processor <name>
hermes wiki plugins untrust <name> [--kind classifier|processor]
```

## Per-wiki skills

Each wiki declares which skills guide ingestion and writing (defaults:
`wiki:wiki-ingestion` and `wiki:wiki-writing`).

```bash
hermes wiki skills show [--wiki <slug>]
hermes wiki skills set ingestion|writing <skill-name>
```

## Conventions to respect

- Raw Sources are append-only — never overwrite a snapshot.
- Every write carries attribution (`author` + `author_kind`).
- Standard relative Markdown links only inside pages and the Index.
- Archive instead of delete; `purge` is intentionally unavailable.
