---
layout: default
title: Quality Audit & Improvement Roadmap
description: Audit of generated-wiki quality across content, retrieval, structure, and test/CI infrastructure — with a prioritized roadmap of features, evals, and test suites
---

# Quality Audit & Improvement Roadmap

**TL;DR** — Hermes Wiki's deterministic core (pipeline, projection, lint) is the strongest part of the system: well-tested, rebuildable, and attributed. The quality bottleneck is **agent output** — the pages agents actually write — which today is entirely unmeasured. The single highest-leverage investment is an **eval harness that judges agent-produced wikis** (golden corpus + retrieval relevance sets + LLM-judge rubrics), paired with a skill upgrade that gives agents an explicit synthesis/dedup/contradiction protocol.

**Scope & method**: audited at commit `0f2d1d4` by static code review of the pipeline, lint, search, projection, skills, fixtures, and CI — not runtime profiling. Four dimensions: content quality, retrieval quality, structural integrity, test/CI infrastructure. Every finding carries a stable ID (`CQ-*`, `RQ-*`, `SI-*`, `TI-*`) referenced by the roadmap.

---

## Executive Summary

| Dimension | Maturity | Headline gap |
|---|---|---|
| Content quality | **Weak** | No measurement of agent-written pages; naive `DefaultProcessor` heuristics; skills silent on synthesis fidelity, dedup, and contradictions |
| Retrieval quality | **Adequate, unmeasured** | Solid FTS5/BM25 with identifier normalization, but zero relevance evals before the planned embedding ranker lands |
| Structural integrity | **Strong** | 18 lint checks + health score + drift detection; gap is no trend tracking and no link-graph metrics |
| Test/CI infrastructure | **Strong unit, absent elsewhere** | 236 tests, but no coverage gate, no golden/snapshot tests, no evals in CI, no perf benchmarks |

**North star**: the core pipeline (`hermes_wiki/pipeline.py`) is deterministic — no LLM calls. Generated-wiki quality is therefore driven almost entirely by agents following the `wiki-ingestion`/`wiki-writing` skills. Improving wiki quality means (1) measuring agent output and (2) raising the ceiling of what the skills ask agents to do. Core-code hardening is a distant third — it is already the best-covered part of the system.

---

## Audit Findings

### Dimension 1 — Content Quality

#### Strengths

- Deterministic, rebuildable core: every page write propagates atomically to `index.md`, `log.md`, the SQLite projection, and a git commit (`hermes_wiki/pipeline.py`).
- Triple-redundant attribution: frontmatter + SQLite + git (`hermes_wiki/attribution.py`).
- Explicit page-type taxonomy and frontmatter contract in `adapters/hermes/skills/wiki-writing/SKILL.md` — `source`/`entity`/`concept`/`comparison`/`query`/`summary` with required keys.
- The "update over duplicate: search first" curation rule exists (`wiki-writing/SKILL.md`, Curation rules).

#### Gaps

- **CQ-1 — Naive derived-page classification** (severity: medium). `_derived_page_title_and_type` (`hermes_wiki/pipeline.py:1503-1507`) classifies entity vs. concept with a single regex over org keywords (`inc|labs|systems|hermes|google|openai|anthropic`). It never inspects the source body, so most organizations, people, and products silently become `concept` pages. Impact: derived pages are mistyped from day one and taxonomy/type filters degrade.
- **CQ-2 — Regex first-sentence summary** (severity: medium). `_summary_sentence` (`hermes_wiki/pipeline.py:1569-1574`) flattens the source, takes the first sentence, and truncates at 280 chars. Source pages open with a low-value stub rather than a representative lead. Impact: agents and humans browsing source pages get little signal without opening the raw snapshot.
- **CQ-3 — Skills are silent on synthesis fidelity** (severity: **high** — this is the real quality driver). `wiki-writing/SKILL.md` covers mechanics (frontmatter, links, propagation, line limits) but never instructs the agent *how* to summarize faithfully, what counts as a claim requiring a citation, or how to verify its summary against the source. There is no self-check rubric. Since the agent is the content generator, this is the largest unguarded surface in the system.
- **CQ-4 — No proactive contradiction handling** (severity: medium). `unresolved_contested` exists as a *reactive* lint check, but neither skill tells the agent how to detect that a new source conflicts with an existing cited page, or when to create a `comparison` page versus flag a page `contested`. Conflicting sources get silently merged.
- **CQ-5 — Unmanaged `confidence` field** (severity: low). `confidence` is projected (`hermes_wiki/db.py`, pages table) and carried in frontmatter, but no skill guidance or lint check addresses calibration — every value is self-reported and unvalidated.

#### Target state

- Agent outputs are measurable against a golden corpus (structure asserts) and an LLM-judge rubric (faithfulness, citation accuracy, dedup, contradiction handling).
- The writing/ingestion skills carry an explicit synthesis protocol the evals can score against.
- `DefaultProcessor` stubs are good enough that an empty-agent ingest still produces useful pages.

### Dimension 2 — Retrieval Quality

#### Strengths

- Thoughtful identifier normalization: `normalize_search_text` (`hermes_wiki/search.py:20-40`) indexes both original spellings (`getCwd`, `HTTPRequestParser`) and split forms, deliberately avoiding stemming for technical wikis.
- Safe FTS query construction: `build_fts_query` (`hermes_wiki/search.py:43-56`) quotes every term, immune to FTS5 operator injection.
- BM25 ranking over title/tags/snippet/search_text (`hermes_wiki/db.py:617-638`), with `ensure_projection_current` repairing stale projections before every search.
- The pluggable ranker is a documented extension point (SPEC §search) — embedding retrieval was consciously deferred, not forgotten.

#### Gaps

- **RQ-1 — No relevance evals** (severity: **high**). There are no query→expected-page sets, no precision@k/recall/MRR measurement anywhere. This blocks safe adoption of the embedding ranker: without a baseline there is no way to tell whether a new ranker is better or worse.
- **RQ-2 — No ranking regression guard** (severity: medium). Any change to `search_text` projection, tokenization, or BM25 column weighting can silently reorder results; the test suite asserts *membership*, not *ranking quality*.
- **RQ-3 — Unmeasured default recall** (severity: low). `search_wiki` defaults to `limit=5` (`hermes_wiki/search.py:63`). Whether top-5 covers typical agent needs at the documented 100–500 page scale is unknown.

#### Target state

- A fixture-backed relevance suite reporting precision@k, recall@k, MRR, and nDCG — run in CI as a non-blocking report initially, then gated with a regression tolerance once the embedding ranker lands.
- A committed BM25 baseline captured *before* any ranker change.

### Dimension 3 — Structural Integrity

#### Strengths

- 18 lint checks spanning frontmatter, links, citations, index/log consistency, raw-snapshot immutability, plugin trust, and projection drift (`hermes_wiki/lint.py`).
- Projection drift detection with automatic rebuild and atomic swap-after-validation (`hermes_wiki/projection.py`); markdown stays authoritative.
- Health score already computed (`_health_score`, `hermes_wiki/lint.py:911-914`) **and persisted per-wiki** (`_record_lint_result`, `hermes_wiki/lint.py:917-931`).
- The link graph is already projected: `page_links` table + target index (`hermes_wiki/db.py:188`, `:214`) with inbound-link queries (`list_inbound_page_links`).

#### Gaps

- **SI-1 — Health score is point-in-time, not trended** (severity: medium). `_record_lint_result` overwrites a single `health_score` column; nothing keeps or surfaces history. This is an easy win — the measurement already exists, only the time series is missing.
- **SI-2 — No link-graph metrics** (severity: medium). `orphan_page` is checked per-page, but no aggregate metrics (orphan rate, connected components, mean out-degree, dangling-link count) exist despite `page_links` containing everything needed.
- **SI-3 — No index-coverage metric** (severity: low). There is no single number for "% of pages reachable from `index.md`."
- **SI-4 — Unvalidated health-score weights** (severity: low). The penalty constants (`high=0.2, medium=0.08, low=0.03`, `lint.py:912`) are arbitrary; one high finding costs the same as ~7 low findings with no sensitivity analysis behind that ratio.

#### Target state

- A `metrics`/`eval graph` surface emitting graph + coverage metrics and a health trendline from stored history, visible in the dashboard health card.

### Dimension 4 — Test/CI Infrastructure

#### Strengths

- 236 tests across 28 files (~7,800 lines) covering pipeline, lint, db, search, projection, tools, CLI, adapters, and the dashboard API.
- Deterministic fixtures: `fixtures/factory.py` builds populated/clean multi-wiki homes; `fixtures/seed_data.py` pins `FIXED_NOW` (`:14`) so tests never depend on wall-clock time.
- CI matrix on Python 3.11–3.13 with ruff, ty type checking, pytest, and a dashboard build (`.github/workflows/ci.yml`); release automation via release-please.

#### Gaps

- **TI-1 — No coverage reporting or threshold** (severity: medium). CI runs bare `pytest`; coverage regressions are invisible.
- **TI-2 — No golden/snapshot tests for generated pages** (severity: medium). `DefaultProcessor` output is asserted piecemeal, never pinned whole. Changes to stub generation (the CQ-1/CQ-2 fixes) cannot be reviewed as diffs.
- **TI-3 — No property-based tests** (severity: medium). Frontmatter write→read round-trip and projection-rebuild idempotency are real invariants currently only spot-checked.
- **TI-4 — No e2e CLI tests** (severity: low). Subcommands are tested at function level, not as `hermes-wiki ...` process invocations; argparse/wiring breaks can slip through.
- **TI-5 — No React component tests** (severity: low). The dashboard is build-checked only.
- **TI-6 — No performance benchmarks** (severity: low). Bulk ingest and search latency at the documented 100–500 page target are unmeasured.
- **TI-7 — No content-quality or retrieval evals in CI** (severity: **high**). The headline gap — cross-references all `CQ-*` and `RQ-*` findings.

#### Target state

- Coverage gate, golden snapshots for deterministic generation, two targeted property suites, and the eval harness wired into CI (deterministic evals gated; LLM-judge evals scheduled).

---

## Eval Harness Architecture

This is the centerpiece recommendation. Because the core has no LLM, evals must judge **agent output**, not core functions. That splits the harness into two families with different execution models:

| Family | Examples | Determinism | Where it runs |
|---|---|---|---|
| **Deterministic evals** | golden structure, retrieval qrels, graph metrics | Fully reproducible | CI, gated (`pytest -m eval`) |
| **LLM-judge content evals** | faithfulness, citation accuracy, dedup, contradiction | Judge-model variance | Scheduled + on-demand, never PR-blocking (`pytest -m eval_llm`) |

**Default execution mode: transcript replay.** Agent ingestion/writing runs are recorded once and committed as fixtures; evals score the recorded outputs. This makes content evals deterministic and cheap for regression purposes. A separate `--live` mode regenerates transcripts on a schedule to catch skill/model drift.

### Directory layout

```
evals/
  README.md                      # how to run, how to add cases
  conftest.py                    # registers markers: eval, eval_llm
  corpus/                        # golden corpus: input sources + expected outcomes
    agent-memory/
      sources/                   # raw source files (same style as fixtures/sources/)
      expected_structure.yaml    # expected pages: ids, types, citations, cross-links
      relevance.yaml             # qrels: query -> ranked expected page ids
    multi-source-contradiction/  # designed to exercise contradiction handling
      sources/
      expected_structure.yaml
      relevance.yaml
  transcripts/                   # committed recorded agent runs
    agent-memory.transcript.json # tool calls + final wiki manifest hash
  rubrics/
    faithfulness.md              # claim decomposition: supported-claim fraction vs cited sources
    citation_accuracy.md         # every claim cites a real source page; no fabricated cites
    dedup.md                     # no near-duplicates; "2+ sources or central" threshold honored
    contradiction.md             # conflicting sources surfaced with dates, not silently merged
  harness/
    runner.py                    # load case -> run/replay -> score -> store
    structural.py                # compare generated wiki to expected_structure.yaml
    retrieval.py                 # precision@k, recall@k, MRR, nDCG over relevance.yaml
    graph.py                     # link-graph + index-coverage metrics over a wiki
    judge.py                     # LLM-judge wrapper (rubric -> score + rationale)
    replay.py                    # rebuild wiki from a recorded transcript
    scoring.py                   # metric dataclasses, aggregation, thresholds
    store.py                     # append results to evals/results/ (JSONL, git-tracked)
  results/                       # {date, case, metric, value, commit} baselines
  test_structural_evals.py       # @pytest.mark.eval     — deterministic, CI-gated
  test_retrieval_evals.py        # @pytest.mark.eval     — deterministic, CI-gated
  test_graph_evals.py            # @pytest.mark.eval     — deterministic, CI-gated
  test_content_evals.py          # @pytest.mark.eval_llm — scheduled only
```

### Content-quality evals

**Golden-structure eval (deterministic, CI-safe).** For each corpus case, run the current generation path (DefaultProcessor today; agent transcript replay later) over `sources/`, then assert against `expected_structure.yaml`:

- expected page IDs exist with the correct `type`
- each page's `sources:` frontmatter references a real source page
- required cross-links are present (checked via the `page_links` projection)
- the wiki passes lint at a minimum health score

```yaml
# expected_structure.yaml
pages:
  - id: concepts/agent-memory
    type: concept
    must_cite: [sources/2026-06-06-agent-memory-article]
    must_link: [entities/hermes]
forbidden:
  duplicate_titles: true
min_health_score: 0.9
```

This is the cheapest, highest-signal content eval and needs no LLM. It directly pins CQ-1/CQ-2 behavior once `DefaultProcessor` is enriched.

**LLM-judge evals (scheduled).** `judge.py` sends (source text + generated page body + rubric) to a pinned judge model at temperature 0 and parses a structured verdict: `{score: 1-5, pass: bool, rationale: str, violations: [...]}`. The faithfulness rubric uses **claim decomposition** (FActScore/RAGAS style — see Prior Art): split the page into atomic claims, verify each against its cited sources, score the supported fraction; this outperforms holistic 1–5 scoring and yields per-claim violations to act on. Rubrics live as markdown in `rubrics/` so changes are PR-reviewable. Results (including model id and rationale) append to `results/` for diffing across runs. A `--dry-run` flag validates case/rubric wiring without API calls so the suite's plumbing is testable in plain CI. Eval-case files in `corpus/` adopt Anthropic's Agent Skills JSON case shape for interoperability.

### Retrieval evals

`retrieval.py` loads `relevance.yaml`, runs `search_wiki(query, wiki=<fixture>, limit=k)`, and computes precision@k, recall@k, MRR, and nDCG — per-query and aggregate. Cases run against the existing populated fixture (`fixtures/factory.build_populated_home`) plus corpus wikis.

```yaml
# relevance.yaml
queries:
  - q: "agent memory"
    relevant: [concepts/agent-memory, sources/2026-06-06-agent-memory-article]
  - q: "getCwd"          # identifier-normalization regression case
    relevant: [concepts/get-cwd]
```

Rollout: non-blocking CI report first; once the embedding ranker work begins, gate with a tolerance (fail if aggregate MRR drops more than X% versus the last stored baseline in `results/`). **Capture the BM25 baseline now** — it is the safety net for RQ-1/RQ-2.

### Structural metrics over time

`graph.py` builds the link graph from `page_links` (`hermes_wiki/db.py:188`) and computes: orphan rate, connected-component count, % pages reachable from `index.md`, mean out-degree, and dangling-link count. `store.py` appends health score + graph metrics keyed by `{commit, wiki, date}`; a small renderer turns the JSONL into a trendline table. This reuses the already-persisted health score (`_record_lint_result`) rather than inventing new storage.

### CLI, pytest, and CI integration

- **CLI**: add an `eval` subcommand to `hermes_wiki_cli/cli.py` (alongside `lint`) with verbs `structural | retrieval | graph | content [--live|--replay] [--dry-run] | report`, routing into `evals/harness/runner.py`.
- **pytest**: register `eval` and `eval_llm` markers in `pyproject.toml`; exclude both from the default run (`addopts = "-ra -m 'not eval and not eval_llm'"`) so the fast suite stays fast.
- **CI**: add a `pytest -m eval` job to `ci.yml` (deterministic — safe to gate). Add `.github/workflows/evals.yml` on `schedule` (weekly) + `workflow_dispatch` running `pytest -m eval_llm` with the judge API key as a secret, writing results to the job summary and `results/`. Judge evals never block PRs.

---

## Prior Art & Solution Engineering Notes (research-validated)

A deep-research pass (22 sources fetched, 107 claims extracted, 25 adversarially verified — 23 confirmed, 2 refuted) validated and sharpened the roadmap. Findings that change *how* the workstreams should be engineered:

### Upstream already wrote most of F1 — adapt, don't invent

The Hermes Agent bundles a [`research-llm-wiki` skill (v2.1.0)](https://hermes-agent.nousresearch.com/docs/user-guide/skills/bundled/research/research-llm-wiki) that encodes the exact protocols F1 calls for, verbatim:

- **Dedup / page-creation threshold**: *"Create a page when an entity/concept appears in 2+ sources OR is central to one source"*; *"DON'T create a page for passing mentions, minor details, or things outside the domain."*
- **Contradiction protocol**: check dates — newer sources generally supersede; if genuinely contradictory, note both positions with dates and sources; mark `contradictions: [page-name]` in frontmatter; flag for user review in the lint report.
- **Provenance markers**: on pages synthesizing 3+ sources, append `^[raw/articles/source-file.md]` at the end of paragraphs whose claims come from a specific source; single-source pages rely on the frontmatter `sources:` field.

The upstream `contradictions:` frontmatter convention maps directly onto the existing `contradictions` projection column and the `unresolved_contested` lint check — adopting it costs nothing schema-wise. **F1 should port and adapt this prose into `wiki-writing`/`wiki-ingestion` SKILL.md** rather than authoring new protocols, keeping local additions (e.g., the faithfulness self-check) clearly separated from upstream-derived rules. Notably, upstream v2.1.0 contains **zero eval, retrieval, or testing protocols** — the harness and retrieval workstreams remain genuinely new work.

### Skill engineering: follow the host's template and Anthropic's evals-first loop

- Hermes skills use SKILL.md with name+description frontmatter and **three-level progressive disclosure**; the recommended content structure is *When to Use / Procedure / Pitfalls / Verification* ([Hermes skills docs](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)). For F1: dedup + contradiction rules belong under **Procedure**; the faithfulness/citation self-check belongs under **Verification**.
- Anthropic's [Agent Skills best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) prescribe **building evaluations *before* writing skill docs** — 3+ concrete scenarios per behavior, a JSON eval-case schema (they ship the schema, not a runner), and a validate-fix-repeat authoring loop. Applied here: write the eval corpus cases for dedup/contradiction/faithfulness behaviors *first*, then write the F1 prose against them. This reorders "Now": eval scaffold cases for skill behaviors land before or with F1, not after.

### Eval methodology grounding

- **LLM-as-judge** ([Zheng et al., MT-Bench](https://arxiv.org/abs/2306.05685)): strong judges reach ~80%+ agreement with humans, but known biases (position, verbosity, self-enhancement) require structured verdicts and pinned judge models — confirming the harness design (temperature 0, pinned model id, recorded rationale).
- **Faithfulness via claim decomposition** ([FActScore](https://arxiv.org/abs/2305.14251), [RAGAS faithfulness](https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/faithfulness/)): decompose a generated page into atomic claims and verify each against the cited sources, scoring the supported fraction — rather than holistic 1–5 scoring. The `rubrics/faithfulness.md` design should adopt claim decomposition as its core mechanic.
- **Retrieval baselines** ([BEIR](https://arxiv.org/abs/2104.08663)): BM25 is a strong, hard-to-beat baseline across heterogeneous retrieval tasks — embedding rankers frequently *underperform* it out-of-domain. This strengthens the closing rule: capture the BM25 baseline now and require the embedding ranker to beat it on our own qrels before shipping.
- **Build-on-pytest confirmed**: no third-party eval framework comparison survived verification at primary-source quality; Anthropic ships an eval-case schema with no runner. Owning a small pytest-based runner (as designed above) remains the right call; adopt Anthropic's JSON case shape for `corpus/` cases to stay interoperable.

### Integration cautions (refuted claims)

Two plausible-sounding claims about Hermes Agent internals were **refuted** during verification and must not be assumed:

1. ~~Plugin discovery via `~/.hermes/plugins/` + `.hermes/plugins/` + pip entry points with import-time tool self-registration~~ — not how it works.
2. ~~Memory providers implement a `MemoryProvider` ABC with `get_tool_schemas()`/`handle_tool_call()`/etc.~~ — not the actual interface.

Any work touching the adapter surface (`adapters/hermes/`) should be verified against the live `hermes-agent` source, not docs-derived assumptions.

**Skill precedence — verified against hermes-agent 0.16.0 source (2026-06-07).** There is no *name* collision risk: plugin-registered skills live in a separate registry with qualified names (`wiki:<name>`, `hermes_cli/plugins.py:957-1000`), while bundled skills are seeded to `~/.hermes/skills/` and tracked via `.bundled_manifest`. The real risk is an **attention asymmetry**: bundled/local skills appear in the system prompt's `<available_skills>` block and as slash commands (implicit activation), whereas plugin skills are **explicit-load only** (`skill_view("wiki:wiki-writing")`) and never appear in the system prompt (`tools/skills_tool.py:851-897`, `agent/prompt_builder.py:1254-1330`). Consequences:

1. If the bundled `research-llm-wiki` skill is present in a user's `~/.hermes/skills/`, its guidance (including the `^[...]` provenance-marker syntax this wiki rejects) activates *by default*, while this plugin's per-wiki skills require an explicit load. Upstream guidance wins unless mitigated.
2. Mitigations: users can disable the bundled skill via `skills.disabled: [research-llm-wiki]` in Hermes `config.yaml` (`tools/skills_tool.py:546-566`); and the wiki prompt injection should instruct agents to load the wiki's *assigned* skills (`wiki:wiki-writing`/`wiki:wiki-ingestion` per SCHEMA.md) before writing — a small `prompt.py` enhancement, added to the roadmap as **F9**.

---

## Feature Recommendations

| ID | Feature | Dimension | Leverage | Effort | Notes |
|---|---|---|---|---|---|
| **F1** | **Skill upgrade: synthesis/dedup/contradiction protocol** — port the upstream [`research-llm-wiki` v2.1.0](https://hermes-agent.nousresearch.com/docs/user-guide/skills/bundled/research/research-llm-wiki) protocols into `wiki-writing/SKILL.md` and `wiki-ingestion/SKILL.md` (dedup threshold "2+ sources or central", date-aware contradiction handling with `contradictions:` frontmatter, per-paragraph provenance markers on 3+-source pages), plus a local faithfulness self-check (every claim traceable to a cited source page). Structure per the Hermes template: rules under *Procedure*, self-check under *Verification*; record `upstream_skill: research-llm-wiki` + `upstream_skill_version: 2.1.0` in SKILL.md metadata so upstream drift is reviewable on dependency bumps | Content | High | S | Adapt upstream prose, don't invent (see Prior Art); addresses CQ-3/CQ-4; what the LLM-judge evals score against |
| **F2** | **Enrich `DefaultProcessor`** — replace the single-regex entity/concept heuristic (`pipeline.py:1503`) with a scored signal set (title + body keyword density + source type); upgrade `_summary_sentence` (`pipeline.py:1569`) to extract a lead paragraph | Content | Medium | M | Addresses CQ-1/CQ-2; land golden snapshots (T2) first so the change reviews as a diff |
| **F3** | **Dedup-on-create suggestion** — on `wiki_create_page`/`create-page`, BM25-search the title and warn when a high-similarity page exists ("did you mean to update X?") | Content/Structural | High | M | Operationalizes the rule F1 can only state; reuses existing search |
| **F4** | **Citation-verification lint check** — every `sources:` entry resolves to a real `source` page; stretch: claims adjacent to citations are non-empty | Content/Structural | High | S | Complements existing `missing_citation` (`lint.py:367`) |
| **F5** | **Taxonomy enforcement via Phase 2 hooks** — implement the already-designed `validate_tags`/`suggest_tags` hooks ([hooks architecture](hooks-architecture.md)) so invalid tags are caught at write time, not only by lint | Structural | Medium | M | Builds on planned work — not a new design |
| **F6** | **Health trendline + graph metrics surface** — persist health-score history, surface trendline + `graph.py` metrics in the dashboard health card and a CLI report | Structural | Medium | S/M | Addresses SI-1/SI-2/SI-3; storage already exists |
| **F7** | **Capture BM25 retrieval baseline** — land relevance fixtures + `eval retrieval` and snapshot current numbers before any ranker change | Retrieval | High | S | Addresses RQ-1; cheap insurance for the SPEC's embedding extension point |
| **F8** | **Contradiction detection assist** — flag when a new page's claims contradict an existing cited page (heuristics first, LLM-judge later) | Content | Medium | L | Sequence after F1 + judge evals prove the gap with data |
| **F9** | **Prompt injection loads assigned wiki skills** — extend `prompt.py` so the Available Wikis block instructs agents to `skill_view` the wiki's SCHEMA.md-assigned `wiki:*` skills before writing | Content | High | S | Counters the bundled-skill attention asymmetry (see Integration cautions): plugin skills are explicit-load only and otherwise lose to implicit upstream guidance |

**Ordering rationale**: per Anthropic's evals-before-docs loop (see Prior Art), write the eval corpus cases for the F1 behaviors (dedup, contradiction, faithfulness — 3+ scenarios each) first or together with the F1 prose, so the skill is authored against measurable targets. Then F7 (baselines before behavior changes), then F2–F6 in leverage order. F1 remains the highest-ROI item — and is now mostly a porting job from upstream v2.1.0 rather than original authoring.

---

## Test Suite Recommendations

| ID | Item | Covers | Effort | Strength |
|---|---|---|---|---|
| **T1** | **Coverage reporting + threshold** — add `pytest-cov` to CI, report on PRs, set the floor at the observed level and ratchet | TI-1 | S | Strong |
| **T2** | **Golden snapshots of `DefaultProcessor` output** — snapshot full generated pages (frontmatter + body) for each `fixtures/sources/*` sample, via `syrupy` or committed expected files | TI-2 | S/M | Strong — prerequisite for F2 |
| **T3** | **Property-based tests (targeted)** — `hypothesis` for exactly two invariants: (a) frontmatter write→read round-trip preserves data; (b) projection rebuild idempotency (rebuilding twice == once; rebuild-from-files == original) | TI-3 | M | Strong but deliberately narrow |
| **T4** | **e2e CLI tests** — a handful of subprocess-level runs (`create → ingest → search → lint`) against a temp home | TI-4 | M | Moderate; keep small |
| **T5** | **React component tests** — Vitest + Testing Library for the health card and inbox manager only | TI-5 | M | Optional |
| **T6** | **Performance benchmarks** — bulk ingest of N sources and search latency at 100/500 pages (the Phase-1 target); scheduled, tracked in `evals/results/`, not gated | TI-6 | M | Moderate; most valuable right before the embedding ranker |

**Deliberately de-prioritized**: broad property testing beyond the two invariants, full-dashboard Playwright e2e, and mutation testing — the codebase's size and risk profile don't justify them yet.

---

## Prioritized Roadmap

### Now

| Item | Dimension | Effort | Depends on |
|---|---|---|---|
| F1 — Skill synthesis/dedup/contradiction protocol | Content | S | — |
| ~~Verify skill precedence/collision vs upstream bundled `llm-wiki` skill~~ ✅ verified 2026-06-07 — see Integration cautions; spawned F9 | Content | S | — |
| F9 — Prompt injection loads assigned wiki skills (`prompt.py`: instruct agents to `skill_view` the SCHEMA.md-assigned `wiki:*` skills before writing) | Content | S | — |
| Eval scaffold (`evals/` layout, markers, `hermes-wiki eval`, structural eval) | Test/Content | M | — |
| F7 — BM25 retrieval baseline + `eval retrieval` | Retrieval | S | Eval scaffold |
| T1 — Coverage reporting + floor | Test | S | — |
| T2 — Golden snapshots of `DefaultProcessor` output | Test/Content | S | — |
| F4 — Citation-verification lint check | Content/Structural | S | — |

### Next

| Item | Dimension | Effort | Depends on |
|---|---|---|---|
| F2 — Enrich `DefaultProcessor` classify/summary | Content | M | T2 |
| F3 — Dedup-on-create suggestion | Content/Structural | M | — |
| LLM-judge content evals + scheduled workflow | Content/Test | M | Eval scaffold, F1 |
| F6 — Health trendline + graph metrics | Structural | S/M | Eval scaffold |
| T3 — Property tests (frontmatter round-trip, projection idempotency) | Test | M | — |
| Retrieval regression gate with tolerance | Retrieval/Test | S | F7 |

### Later

| Item | Dimension | Effort | Depends on |
|---|---|---|---|
| F5 — Taxonomy hooks (validate/suggest tags) | Structural | M | Phase 2 hooks |
| F8 — Contradiction detection assist | Content | L | LLM-judge evals |
| T4 — e2e CLI tests | Test | M | — |
| T6 — Performance benchmarks | Test/Retrieval | M | — |
| Embedding ranker behind the eval gate | Retrieval | L | Retrieval gate, T6 |
| T5 — React component tests | Test | M | — |

**Closing rule**: the embedding ranker (a documented SPEC extension point) must not ship until the retrieval eval gate exists — without it, the ranker's impact is unmeasurable.

---

## Appendix

### Finding index

| ID | Finding | Severity |
|---|---|---|
| CQ-1 | Naive derived-page classification (`pipeline.py:1503`) | Medium |
| CQ-2 | Regex first-sentence summary (`pipeline.py:1569`) | Medium |
| CQ-3 | Skills silent on synthesis fidelity | **High** |
| CQ-4 | No proactive contradiction handling | Medium |
| CQ-5 | Unmanaged `confidence` field | Low |
| RQ-1 | No relevance evals | **High** |
| RQ-2 | No ranking regression guard | Medium |
| RQ-3 | Unmeasured default recall (`search.py:63`) | Low |
| SI-1 | Health score not trended (`lint.py:917`) | Medium |
| SI-2 | No link-graph metrics (`db.py:188`) | Medium |
| SI-3 | No index-coverage metric | Low |
| SI-4 | Unvalidated health-score weights (`lint.py:912`) | Low |
| TI-1 | No coverage gate | Medium |
| TI-2 | No golden snapshots of generated pages | Medium |
| TI-3 | No property-based tests | Medium |
| TI-4 | No e2e CLI tests | Low |
| TI-5 | No React component tests | Low |
| TI-6 | No performance benchmarks | Low |
| TI-7 | No content/retrieval evals in CI | **High** |

### Glossary

- **Golden corpus** — committed input sources paired with expected output structure, used to detect generation regressions.
- **qrels** — query→relevant-document judgments used to score search rankings.
- **Precision@k / Recall@k / MRR / nDCG** — standard retrieval metrics: fraction of top-k results that are relevant; fraction of relevant results in top-k; mean reciprocal rank of the first relevant result; rank-discounted relevance gain.
- **LLM-judge** — a pinned model scoring generated content against a written rubric, returning a structured verdict with rationale.
- **Transcript replay** — re-running a recorded sequence of agent tool calls to reproduce a generated wiki deterministically.

### Relationship to planned work

This audit **builds on** rather than re-proposes existing designs:

- **Upstream `research-llm-wiki` skill v2.1.0** ([Hermes Agent bundled skills](https://hermes-agent.nousresearch.com/docs/user-guide/skills/bundled/research/research-llm-wiki)) — F1 ports its dedup/contradiction/provenance protocols rather than authoring new ones; the eval harness and retrieval suites cover what upstream lacks entirely.
- **Phase 2 hooks** ([hooks-architecture.md](hooks-architecture.md)) — F5 implements the already-designed taxonomy hooks; future lint hooks can host F4-style checks per-wiki.
- **Pluggable ranker** (SPEC) — the retrieval eval suite (F7 + regression gate) is the precondition this audit adds in front of that extension point; BEIR's finding that BM25 is hard to beat out-of-domain makes the gate non-negotiable.
- **Media processing / chunking, cross-wiki routing, purge** (SPEC future phases) — out of scope here; nothing in this roadmap conflicts with them.
