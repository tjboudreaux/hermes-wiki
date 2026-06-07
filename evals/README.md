# Evals

Evaluation assets for generated-wiki quality, per the
[Quality Audit & Improvement Roadmap](../docs/quality-audit.md).

Authored **evals-first**: these scenario cases were written before the skill
prose they test (Anthropic's evaluation-driven skill development loop), so the
`wiki-writing`/`wiki-ingestion` synthesis protocols are measured against
concrete targets rather than imagined ones.

## Layout

```
evals/
  skills/                  # skill-behavior scenario cases (this drop)
    dedup.cases.json           # page-creation threshold / no near-duplicates
    contradiction.cases.json   # date-aware supersession, contested flagging
    faithfulness.cases.json    # claims traceable to cited sources
  corpus/                  # input sources the cases reference
    dedup-threshold/sources/
    multi-source-contradiction/sources/
```

The harness (`harness/`, `rubrics/`, `results/`, the `hermes-wiki eval` CLI,
and pytest `eval`/`eval_llm` markers) lands with the "eval scaffold" roadmap
item — see the audit's Eval Harness Architecture section for the full design.

## Case format

Cases use the Anthropic Agent Skills evaluation shape — one JSON array per
behavior, each case:

```json
{
  "skills": ["wiki-writing"],
  "query": "<the task an agent is given>",
  "files": ["<input sources, relative to repo root>"],
  "expected_behavior": ["<observable, checkable behaviors>"]
}
```

`expected_behavior` entries double as the checklist for LLM-judge rubrics
(`rubrics/*.md`, future) and as assertions for transcript-replay scoring.

## Adding cases

- 3+ scenarios per behavior; each `expected_behavior` entry must be
  observable from the resulting wiki or transcript (not vibes).
- Reference real input files — reuse `fixtures/sources/` or add minimal
  sources under `corpus/<case>/sources/`.
- Keep sources small and deterministic (no timestamps that drift, no
  network dependencies).
