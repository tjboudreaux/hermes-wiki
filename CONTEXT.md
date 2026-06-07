# Hermes Wiki Plugin

Hermes Wiki adds Karpathy-style LLM Wikis to Hermes: persistent, compounding knowledge bases that agents curate over time instead of rediscovering context from scratch.

## Language

**LLM Wiki**:
A domain-scoped knowledge base where agents compile, cross-reference, and maintain durable knowledge from human-curated sources. It is the canonical domain object; CLIs, dashboards, databases, and tools are surfaces or support systems around it.
_Avoid_: vault, CMS, RAG corpus, dashboard tab

**Karpathy Pattern**:
The conceptual curation loop behind an LLM Wiki: immutable Raw Sources become agent-curated, interlinked Wiki Pages governed by a Schema, Index, Log, and provenance. The pattern does not require a particular editor, link syntax, or storage implementation.
_Avoid_: Obsidian implementation, literal skill template

**Wiki**:
Short form of **LLM Wiki** when the Hermes context is clear. A Wiki contains **Raw Sources**, **Wiki Pages**, a **Schema**, an **Index**, and a **Log**.
_Avoid_: plugin, app, server, search index

**Raw Source**:
Immutable source material captured before synthesis. A Raw Source may support many Wiki Pages, but agents do not rewrite it to make the wiki read better.
_Avoid_: page, note, draft

**Source Snapshot**:
A specific captured version of a Raw Source at one point in time. When an external URL changes, the Wiki creates a new Source Snapshot instead of overwriting the old one.
_Avoid_: overwritten source, patch

**Source Page**:
A curated Wiki Page that summarizes and contextualizes one or more Source Snapshots. It is readable synthesis about a source, not the immutable source itself.
_Avoid_: raw file, source snapshot

**Wiki Page**:
Agent-curated knowledge derived from one or more Raw Sources. A Wiki Page should synthesize, link, and stay current rather than merely mirror source text.
_Avoid_: source, clipping, document

**Schema**:
The domain contract for a Wiki: its scope, taxonomy, page thresholds, and update policy. The Schema guides curation decisions but is not the knowledge itself.
_Avoid_: config file, database schema

**Index**:
The reader and agent-facing catalog of Wiki Pages. The Index is navigation, not the source of truth for page content.
_Avoid_: search database, registry

**Projection**:
A rebuildable support view derived from Wiki content for search, health checks, metadata, and operational joins. A Projection may be versioned for triage, but it never overrides Raw Sources or Wiki Pages.
_Avoid_: source of truth, content store

**Projection Version**:
A historical state of a Projection used to diagnose rebuilds, migrations, and inconsistencies. It is a version of the support view, not a version of the Wiki's knowledge.
_Avoid_: page history, wiki snapshot

**Search Projection**:
A Projection optimized for finding Wiki Pages, including normalized technical terms and identifiers. It supports discovery but does not define page content.
_Avoid_: knowledge store, vector memory

**Log**:
The append-only record of wiki actions. The Log explains what changed and when, but does not replace page-level provenance.
_Avoid_: audit database, changelog

**Page History**:
The chronological record of changes to a Wiki Page, rendered from attribution records outside the page body. Page History is metadata about curation, not knowledge content.
_Avoid_: author-history section, page content

**Ingest**:
The act of turning a Raw Source into one or more Wiki Page updates. Ingest includes synthesis, cross-linking, indexing, and logging.
_Avoid_: upload, import, scrape

**Inbox Ingest**:
An explicit batch Ingest of pending Raw Sources from a Wiki's inbox. It is distinct from ingesting a single provided source.
_Avoid_: omitted path ingest, implicit batch

**Oversized Inbox Item**:
A file in a Wiki inbox that exceeds the current ingest size limit. It stays unprocessed until a later media/chunking workflow can handle it safely.
_Avoid_: failed source, partial source

**Monitor**:
A recurring job definition that keeps a Wiki current or healthy. The Wiki owns the desired Monitor definition; Hermes cron owns execution state.
_Avoid_: cron-only job, hidden automation

**Profile**:
A Hermes agent identity with its own permissions and working context. Profiles may discover or use Wikis, but they do not own the definition of a Wiki.
_Avoid_: user account, role

**Visible Wiki**:
An LLM Wiki that a Profile is allowed to discover and query. Invisible Wikis are not named in prompts or ordinary tool errors.
_Avoid_: accessible database, public wiki

**Archived Wiki**:
An LLM Wiki preserved on disk but hidden from normal discovery and mutation. Archiving is reversible; purging is a separate destructive operation.
_Avoid_: deleted wiki, removed files

**Current Wiki**:
The default Wiki a Profile or session uses when a command omits `--wiki`. Current Wiki is profile-scoped to prevent one Profile from changing another Profile's default.
_Avoid_: global active wiki

**Wiki Repository**:
The per-Wiki git repository that records durable Markdown, raw snapshots, schema, index, log, and manifests for one LLM Wiki. It does not make database projections authoritative.
_Avoid_: global wiki repo, database backup

**Write Grant**:
Permission for a Profile or agent session to change a Wiki. Read access makes a Wiki visible; a Write Grant is required for ingesting, editing pages, linking kanban tasks, or configuring monitors.
_Avoid_: visibility, tool availability

**Trusted Plugin**:
A custom classifier or processor that has been explicitly approved for a Wiki. A plugin file's presence is not enough to make it executable.
_Avoid_: dropped Python file, implicit extension

**Kanban Reference**:
A durable relationship between a Wiki Page and a Hermes kanban task. The wiki-side canonical copy lives with the Wiki Page, while databases may mirror it for lookup.
_Avoid_: database-only link, task comment

**Surface**:
A Hermes-facing way to use a Wiki, such as a CLI command, agent tool, slash command, or dashboard view. A Surface exposes Wiki behavior but is not itself part of the Wiki's knowledge.
_Avoid_: wiki, knowledge base

## Flagged ambiguities

**Wiki vs plugin**:
Resolved: "Wiki" means the curated knowledge base. "Hermes Wiki Plugin" means the Hermes integration that lets agents and humans create, search, ingest into, and manage Wikis.

**Karpathy Pattern vs literal implementation**:
Resolved: Hermes adopts the Karpathy Pattern conceptually. Hermes keeps standard markdown links, SQLite search, and plugin Surfaces rather than copying Obsidian compatibility or wikilink syntax. The bundled `llm-wiki` skill is split by layer: its mechanics (wikilinks, Obsidian conventions, `^[...]` provenance-marker syntax) are rejected with the above, while its architecture-neutral quality protocols (page-creation threshold, contradiction handling, provenance expectations) are adopted and ported into the wiki skills — see `docs/quality-audit.md` (F1, Prior Art).

**Wiki content vs database state**:
Resolved: Raw Sources and Wiki Pages are authoritative. Database-backed views are Projections; if a Projection disagrees with Wiki content, the Projection is repaired or rebuilt, with Projection Version history preserved for triage.

**Deterministic core vs media extraction**:
Resolved (2026-06-07, media design): the core pipeline is deterministic *or version-stamped extraction*. Mechanical extraction (PDF parsing, ASR, scene detection) may run model-based tools inside trusted processors when tool + version + model identity are stamped into a derived-artifact manifest; interpretation (captions, synthesis) is always attributed to a model identity and stays agent-side or routes through the host's auxiliary vision router. See `docs/media-ingestion-design.md` (D1).

**Raw evidence vs large media**:
Resolved (2026-06-07, media design): for media above `MAX_INGEST_BYTES`, provenance consciously degrades from bytes-in-git to fingerprint-in-git — the original is kept on disk (gitignored) with its sha256 pinned in the derived manifest, and the git-tracked derived artifacts are the durable evidence. See `docs/media-ingestion-design.md` (D4).

**Search Projection strategy**:
Resolved: Phase 1 search preserves technical terms and normalized identifiers rather than applying Porter stemming by default.

**Monitor ownership**:
Resolved: a Wiki stores desired Monitor definitions for portability, while global Hermes cron owns actual scheduling and run state.

**Kanban Reference authority**:
Resolved: the Wiki Page is authoritative for the wiki-side Kanban Reference. SQLite may project it and kanban may mirror it, but the relationship must survive wiki database regeneration.

**Visible vs invisible Wikis**:
Resolved: prompts and ordinary tools name only Visible Wikis. Hidden, private, or blacklisted Wikis are not disclosed by name outside admin/debug surfaces.

**Archive vs purge**:
Resolved: normal wiki removal means archive/disable, not file deletion. Permanent purging is a separate explicit destructive operation.

**Current Wiki scope**:
Resolved: Current Wiki is resolved per session/profile before any global fallback.

**Git boundary**:
Resolved: each LLM Wiki owns its own Wiki Repository. Cross-wiki registries and database projections are not the git authority for wiki knowledge.

**Read vs write access**:
Resolved: Visible Wikis are readable/searchable by authorized Profiles. Mutating a Wiki requires a Write Grant.

**Custom plugin execution**:
Resolved: custom classifiers and processors must be Trusted Plugins. Hermes never executes per-wiki code merely because a file exists.

**Single-source Ingest vs Inbox Ingest**:
Resolved: processing the inbox requires explicit inbox intent. A missing source path must not silently batch-process a Wiki's inbox.

**Large media handling**:
Resolved: Phase 1 leaves files over 50MB in the inbox as Oversized Inbox Items. Later media skills handle PDFs, video, images, and audio by producing transcripts or decomposed source material.

**Raw Source immutability**:
Resolved: Raw Sources are append-only. External source changes create new Source Snapshots, and Wiki Pages cite the snapshots they used.

**Raw Source vs Source Page**:
Resolved: Raw Sources are immutable evidence; Source Pages are curated summaries inside the Wiki.

**Page History placement**:
Resolved: Page History stays outside Wiki Page bodies so search and reading focus on knowledge content.

**Raw Source vs Wiki Page**:
Resolved: Raw Sources are immutable evidence; Wiki Pages are mutable synthesis.

## Example dialogue

Developer: "Should `wiki_search` query the Wiki or the Index?"

Domain expert: "It queries the Index as a support system, but the result represents Wiki Pages in the LLM Wiki."

Developer: "If a PDF changes, do we edit the Raw Source?"

Domain expert: "No. Capture the changed material as source drift, then Ingest it into updated Wiki Pages with provenance."
