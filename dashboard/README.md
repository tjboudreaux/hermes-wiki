# Hermes Wiki Dashboard Plugin

The dashboard plugin is the web surface for the Hermes Wiki Plugin. It is a React 19 +
`@nous-research/ui` plugin that registers a "Wikis" tab in the Hermes dashboard, serving a FastAPI
backend at `/api/plugins/wiki/*` and views for browsing wikis, pages, search, inbox, health, and
activity.

The bundle is a classic IIFE. React and the design-system components are supplied by the host's
Hermes Plugin SDK (`window.__HERMES_PLUGIN_SDK__`), so this bundle does not ship its own React
runtime; it registers itself via `window.__HERMES_PLUGINS__.register(...)`.

## Prerequisites

- Node.js + npm.
- React 19 — provided at runtime by the Hermes Plugin SDK (declared as a dependency here for the
  type/build surface). `@nous-research/ui` `0.19.1` requires React `^19`.
- A built core package and an isolated Hermes home for running/verifying (see the repo `README.md`).

## Build

```bash
npm install
npm run build
```

`npm run build` runs esbuild and produces:

- `dist/index.js` — the IIFE plugin bundle (`esbuild src/index.tsx --bundle --format=iife --target=es2022`).
- `dist/style.css` — copied from `src/style.css`.

## Install location

A Hermes dashboard discovers plugins under a home's `plugins/<name>/dashboard/`. Install the wiki
plugin into the (isolated) Hermes home as `plugins/wiki/dashboard/`, containing:

```
<HERMES_HOME>/plugins/wiki/dashboard/
  manifest.json     # name "wiki", label "Wikis", icon "FileText", tab /wikis/*, entry/css/api
  plugin_api.py     # FastAPI router mounted at /api/plugins/wiki/
  dist/
    index.js
    style.css
```

Restart the dashboard after installing or rebuilding to trigger a rescan. The harness `init`
(`uv run python -m hermes_wiki.harness --repo-root <repo> init`) wires this into `<repo>/.hermes-test`
for you.

## Backend API

All routes are mounted under `/api/plugins/wiki` and require the `X-Hermes-Session-Token` header
(even in local no-auth mode; the SPA supplies it automatically, so only direct probes need it):

- `GET  /wikis` — list visible wikis
- `POST /wikis` — create a wiki
- `GET  /wikis/{slug}` — wiki summary/stats
- `POST /wikis/{slug}/archive` — archive/unarchive
- `DELETE /wikis/{slug}` — remove
- `GET  /wikis/{slug}/pages` — list pages (with `/pages/facets`)
- `GET  /wikis/{slug}/pages/{page_id:path}` — page detail (includes `kanban_refs`)
- `GET  /search` and `GET /wikis/{slug}/search` — cross-wiki and scoped search
- `POST /wikis/{slug}/ingest` — ingest a source
- `GET  /wikis/{slug}/inbox` and `POST /wikis/{slug}/inbox/{filename}/classify` — inbox
- `GET  /wikis/{slug}/health` — health/lint findings
- `GET  /wikis/{slug}/log` (with `/log/facets`) — attributed activity

## Views

- `/wikis` — wiki landing/list (archived wikis are excluded)
- `/wikis/<slug>` — wiki detail (pages, search, inbox, health, activity)
- `/wikis/<slug>/<page_id>` — page detail, including the "Linked Kanban Tasks" panel

## Run / verify against an isolated home

Build the plugin first, then run the isolated dashboard on its dedicated port (see
`library/user-testing.md` for the authoritative run/auth details). Never run `hermes dashboard --stop`
and never target the live dashboard.

```bash
# From the repo root
uv run python -m hermes_wiki.harness --repo-root "$(pwd)" dashboard start --port 9123
# ... verify, then:
uv run python -m hermes_wiki.harness --repo-root "$(pwd)" dashboard stop  --port 9123
```

The dashboard serves on `http://127.0.0.1:9123`. For direct backend probes, extract the session token
from the served HTML and pass it as a header (browser/UI flows do not need this):

```bash
TOKEN=$(curl -s http://127.0.0.1:9123/ \
  | grep -oE '__HERMES_SESSION_TOKEN__="[^"]+"' \
  | sed -E 's/.*="([^"]+)"/\1/')

curl -s -H "X-Hermes-Session-Token: $TOKEN" \
  http://127.0.0.1:9123/api/plugins/wiki/wikis
```
