---
layout: default
title: Dashboard
description: Hermes Wiki dashboard plugin — React 19 web UI for browsing, searching, and managing wikis
---

# Dashboard

The Hermes Wiki dashboard is a React 19 plugin tab that integrates into the existing Hermes web dashboard at `/wikis`.

## Setup

### Build the Plugin

```bash
cd dashboard
npm install
npm run build
```

This produces `dist/index.js` (IIFE bundle) and `dist/style.css`.

### Run with the Harness

```bash
# From repo root
uv run python -m hermes_wiki.harness --repo-root "$(pwd)" init
uv run python -m hermes_wiki.harness --repo-root "$(pwd)" dashboard start --port 9123
```

Open [http://127.0.0.1:9123](http://127.0.0.1:9123) and click the **Wikis** tab.

### Stop

```bash
uv run python -m hermes_wiki.harness --repo-root "$(pwd)" dashboard stop --port 9123
```

## Views

| View | Path | Description |
|------|------|-------------|
| Landing | `/wikis` | Visible wikis as cards with stats |
| Wiki Detail | `/wikis/<slug>` | Page list, activity timeline, health |
| Page | `/wikis/<slug>/<page_id>` | Rendered markdown, metadata, kanban refs |
| Search | `/wikis/search?q=...` | Cross-wiki or scoped BM25 results |
| Inbox | `/wikis/<slug>/inbox` | Unprocessed files with classifier overrides |
| Health | `/wikis/<slug>/health` | Lint report with severity filter |
| Activity | `/wikis/<slug>/log` | Chronological log, filterable by author |

## Backend API

All routes mount at `/api/plugins/wiki/` and require `X-Hermes-Session-Token`.

```
GET  /wikis                          List visible wikis
POST /wikis                          Create a wiki
GET  /wikis/<slug>                   Wiki summary/stats
POST /wikis/<slug>/archive           Archive/unarchive
DELETE /wikis/<slug>                  Remove wiki

GET  /wikis/<slug>/pages             List pages (+ /pages/facets)
GET  /wikis/<slug>/pages/<page_id>   Page detail with kanban_refs

GET  /search                         Cross-wiki search
GET  /wikis/<slug>/search            Scoped search

POST /wikis/<slug>/ingest            Ingest a source
GET  /wikis/<slug>/inbox             Inbox files
POST /wikis/<slug>/inbox/<file>/classify  Override classification

GET  /wikis/<slug>/health            Lint findings
GET  /wikis/<slug>/log               Activity log (+ /log/facets)
```

## Technical Details

- **Framework**: React 19 + `@nous-research/ui` (dark theme)
- **Bundle**: IIFE format via esbuild; React externalized through `window.__HERMES_PLUGIN_SDK__`
- **Registration**: `window.__HERMES_PLUGINS__.register(...)` in the host dashboard
- **Auth**: Inherits dashboard session-token auth; no separate login
- **Manifest**: `dashboard/manifest.json` declares the tab at position `after:skills`

## Plugin Installation Path

When installed in a Hermes home:

```
<HERMES_HOME>/plugins/wiki/dashboard/
├── manifest.json
├── plugin_api.py
└── dist/
    ├── index.js
    └── style.css
```
