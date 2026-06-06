---
layout: default
title: Per-Wiki Hooks Architecture
description: Design for per-wiki executable customization — hook points for classification, taxonomy, processing, and lint, built on the existing trust-before-execute plugin system
---

# Per-Wiki Hooks Architecture

**Status:** Accepted design, phased implementation. Phase 1 already ships
(classifier + processor plugins); later phases generalize the same machinery
into a uniform hook system.

## Problem

Each wiki covers a different domain, and domains disagree about what a
"paper" looks like, which taxonomy tags are legal, how a transcript should be
split into pages, and what counts as a lint violation. Hard-coding these
policies in `hermes_wiki` forces every wiki to share one behavior. Wikis need
**their own code** — versioned inside the wiki, attributable, and safe to sync
across machines without silently executing whatever arrives.

## Existing foundation (Phase 1, shipped)

The trust-before-execute plugin system already implements the core pattern for
two hook points:

| Piece | Location |
| --- | --- |
| Plugin code | `<wiki>/plugins/classifiers/<name>.py`, `<wiki>/plugins/processors/<name>.py` |
| Canonical trust record | `SCHEMA.md` — `trusted_plugin` YAML blocks (name, kind, path, sha256, trusted_at, author) |
| Queryable projection | `trusted_plugins` table in `wiki.db`, rebuilt from `SCHEMA.md` |
| Trust CLI | `hermes wiki plugins trust\|untrust\|list` |
| Enforcement | path must resolve inside the wiki root; sha256 must match; mismatch silently disables until re-trusted |
| Invocation | `classify_source()` consults trusted classifiers after built-ins; `_trusted_processor_for_label()` swaps the processor per label |

Every property below is inherited from this foundation, not invented:
**code lives in the wiki** (portable, git-versioned with content),
**trust is content-addressed** (path + sha256 in authoritative Markdown), and
**execution is opt-in per machine state** (a cloned wiki's hooks are inert
until the projection is rebuilt from the SCHEMA.md trust records the owner
committed).

## Design

### Hook points

Generalize `kind` from `{classifier, processor}` to a hook-point registry.
Each hook point declares its contract (function name, signature, return type)
and its failure semantics:

| Hook point | Contract | Called | On error |
| --- | --- | --- | --- |
| `classifier` *(shipped)* | `classify(source_path) -> ClassLabel \| str \| None` | After built-in classifiers miss | Skip hook, continue chain |
| `processor` *(shipped)* | `process(request: ProcessRequest) -> list[GeneratedPage]` | Replaces `DefaultProcessor` for its label | Fail the ingest (rollback) |
| `taxonomy` | `validate_tags(page_meta, schema_taxonomy) -> list[TagViolation]` and/or `suggest_tags(page_meta, body) -> list[str]` | On page create/update, before propagation | Fail closed: reject the write with the violation |
| `lint` | `lint(wiki_root, projection) -> list[Finding]` | Appended to built-in checks in `lint_wiki` | Report as its own finding, never crash lint |
| `pre_ingest` | `pre_ingest(snapshot_meta) -> IngestDecision` (allow / skip / reroute label) | After snapshot, before classification | Fail open: log and continue (snapshot is already durable) |
| `post_ingest` | `post_ingest(result: IngestResult) -> None` | After commit, outside the rollback boundary | Log only |

Notes:

- `taxonomy` is the highest-value new hook: SCHEMA.md already declares the
  taxonomy in YAML; this hook lets a wiki *enforce or extend* it (e.g. derive
  tags from frontmatter, forbid tag combinations).
- `pre_ingest`/`post_ingest` deliberately bracket the existing transactional
  boundary (`_remember`/`_restore`): pre runs before any page mutation,
  post runs after the git commit, so neither can corrupt a rollback.
- No hook ever runs on read paths (search, open, dashboard GETs). Hooks fire
  only on writes a grant already authorizes.

### Layout

```
<wiki-root>/plugins/
  classifiers/   <name>.py     # shipped
  processors/    <name>.py     # shipped
  hooks/
    taxonomy/    <name>.py
    lint/        <name>.py
    pre_ingest/  <name>.py
    post_ingest/ <name>.py
```

Trust records keep the same shape with new `kind` values, so `SCHEMA.md`
blocks, the `trusted_plugins` projection, `hermes wiki plugins trust <kind>
<name>`, and the dashboard plugin listing all extend without schema changes.

### Execution model

- **In-process, synchronous, deterministic order.** Multiple trusted hooks of
  one kind run sorted by name; first decisive answer wins for
  classifier-style chains, all run for collector-style chains (lint,
  taxonomy violations).
- **Module loading** reuses `_load_processor_module`: content-hashed module
  names (`hermes_wiki_trusted_<kind>_<name>_<sha16>`) so a re-trusted edit
  loads fresh code, never a stale module cache.
- **No new capabilities granted.** Hooks run with the same OS permissions as
  the host process today. The trust gate is *consent*, not a sandbox. The
  threat model is "synced wiki must not auto-execute foreign code," which
  path+sha256 trust already solves. OS-level sandboxing (subprocess with
  seccomp/sandbox-exec, or WASM) is explicitly out of scope until a phase
  where untrusted-author wikis are a real use case; the interface is designed
  so the in-process invoker can be swapped for an IPC invoker without
  changing hook contracts.
- **Determinism rule:** hooks must not perform network I/O. Phase 2 enforces
  this socially (docs + lint warning); a later phase may enforce it
  technically via the IPC invoker.

### Attribution and rollback

Every hook-caused mutation flows through the existing write paths, so
attribution is inherited: pages created by a custom processor carry the
ingest's `author`/`author_kind`; a taxonomy rejection appends a `lint`-style
log row naming the hook. Hook registration/unregistration already commits to
the wiki git repo via the trust CLI.

### Surfaces

- **CLI:** `hermes wiki plugins trust taxonomy <name>` (kinds become an open
  enum sourced from the hook-point registry). `plugins list` grows a `hook`
  column.
- **API/Dashboard:** the existing plugin listing extends to new kinds; a
  later dashboard phase can offer per-hook enable/disable (a `disabled: true`
  field on the trust record, still canonical in SCHEMA.md).
- **Skills:** per-wiki skill assignments (`SCHEMA.md` `wiki-skills` block)
  tell *agents* how to behave; hooks tell *the pipeline* how to behave. They
  are deliberately separate records — prose guidance vs executable policy —
  but a wiki's skill can document its hooks.

## Phasing

1. **Phase 1 (shipped):** classifier + processor kinds, trust CLI,
   projection, content-hashed loading.
2. **Phase 2:** hook-point registry module (`hermes_wiki/hooks.py`) with the
   contract table above; migrate classifier/processor lookups onto it;
   implement `taxonomy` (validate + suggest) and `lint` hooks; extend trust
   CLI kinds; docs.
3. **Phase 3:** `pre_ingest`/`post_ingest` hooks; `disabled` flag on trust
   records; dashboard hook management.
4. **Phase 4 (speculative):** IPC/sandboxed invoker, resource limits,
   network-deny enforcement.

## Rejected alternatives

- **Home-level (`~/.hermes`) hook config** — breaks portability; a wiki's
  policy must travel with the wiki.
- **Entry-point/pip-installed hooks** — global to the machine, not per-wiki,
  and invisible to the wiki's git history.
- **YAML-only rule DSL** — taxonomy rules quickly exceed declarative
  expressiveness (derivations, conditional requirements); Python with a trust
  gate is simpler than a bespoke DSL and already proven by Phase 1.
- **Auto-trust on wiki create** — violates trust-before-execute; even
  self-authored hooks require an explicit trust action so the SCHEMA.md
  record exists for the next machine.
