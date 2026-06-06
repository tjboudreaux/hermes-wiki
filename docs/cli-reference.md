---
layout: default
title: CLI Reference
description: Complete command reference for the hermes-wiki CLI
---

# CLI Reference

The `hermes-wiki` command is the standalone CLI surface. When integrated with Hermes, it also runs as `hermes wiki ...`.

## Wiki Management

### `create`

Create a new wiki.

```bash
hermes-wiki create <slug> --domain <description>
```

### `list`

List visible wikis.

```bash
hermes-wiki list [--archived]
```

### `show`

Display wiki summary and stats.

```bash
hermes-wiki show [slug]
```

### `switch`

Set the current wiki for this profile.

```bash
hermes-wiki switch <slug>
```

### `archive` / `unarchive`

Hide a wiki from discovery (reversible).

```bash
hermes-wiki archive <slug>
hermes-wiki unarchive <slug>
```

### `purge`

Permanently delete a wiki (destructive, requires confirmation).

```bash
hermes-wiki purge <slug>
```

## Content

### `ingest`

Ingest a source (local file or URL) or process the inbox.

```bash
hermes-wiki ingest <path|url> [--wiki <slug>] [--classifier <name>]
hermes-wiki ingest --inbox [--wiki <slug>]
```

### `search`

Full-text search across wiki pages (BM25 ranked).

```bash
hermes-wiki search <query> [--wiki <slug>] [--limit N]
```

### `open`

Display a page's content.

```bash
hermes-wiki open <page-id> [--wiki <slug>]
```

### `create-page`

Author a new wiki page.

```bash
hermes-wiki create-page <title> --body <text> --type <type> --tag <tag> [--wiki <slug>]
```

Page types: `entity`, `concept`, `comparison`, `query`, `summary`, `source`.

### `list-pages`

List pages with optional filters.

```bash
hermes-wiki list-pages [--wiki <slug>] [--type <type>] [--tag <tag>]
```

### `inbox`

Show unprocessed inbox files.

```bash
hermes-wiki inbox [--wiki <slug>]
```

## Maintenance

### `lint`

Run health checks on a wiki.

```bash
hermes-wiki lint [--wiki <slug>]
```

### `log`

View the activity log.

```bash
hermes-wiki log [--wiki <slug>] [--author <name>] [--kind <agent|profile|human|cron>]
```

### `plugins`

Manage classifiers and processors.

```bash
hermes-wiki plugins list [--wiki <slug>]
hermes-wiki plugins trust classifier <name> [--wiki <slug>]
hermes-wiki plugins trust processor <name> [--wiki <slug>]
hermes-wiki plugins untrust <name> [--wiki <slug>]
```

### `monitor`

Configure recurring source monitoring.

```bash
hermes-wiki monitor [--wiki <slug>] --source <arxiv|rss|x>
```

## Kanban Integration

### `link` / `unlink`

Link or unlink a wiki page to a kanban task.

```bash
hermes-wiki link <page-id> <task-id> [--wiki <slug>]
hermes-wiki unlink <page-id> <task-id> [--wiki <slug>]
```

### `refs`

Show linked kanban tasks for a page.

```bash
hermes-wiki refs <page-id> [--wiki <slug>]
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `HERMES_HOME` | Path to Hermes home directory (default: `~/.hermes`) |
| `HERMES_WIKI` | Override the current wiki for this session (also grants write access) |
| `HERMES_WIKI_ADAPTER` | Adapter selection: `standalone` (default) or `hermes` |
