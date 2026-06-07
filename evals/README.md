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
  skills/                  # skill-behavior scenario cases
    dedup.cases.json           # page-creation threshold / no near-duplicates
    contradiction.cases.json   # date-aware supersession, contested flagging
    faithfulness.cases.json    # claims traceable to cited sources
  corpus/                  # golden-corpus cases
    <case>/sources/            # input sources (deterministic, no network)
    <case>/expected_structure.yaml   # structure contract for the current path
    <case>/relevance.yaml            # qrels for the corpus wiki
  retrieval/
    fixture-qrels.yaml     # qrels for the seeded clean fixture home
  harness/                 # case loading, wiki building, scoring, storage
    runner.py              # dev entry point (capture-baseline / retrieval / suite)
  results/
    bm25-baseline.jsonl    # committed retrieval baseline (floors for CI)
  test_structural_evals.py # @pytest.mark.eval — golden structure contracts
  test_retrieval_evals.py  # @pytest.mark.eval — qrels vs committed baseline
  test_graph_evals.py      # @pytest.mark.eval — link-graph health
```

## Running

```bash
uv run pytest -m eval                                  # deterministic suite (CI-gated)
uv run python -m evals.harness.runner retrieval        # full per-query report
uv run python -m evals.harness.runner capture-baseline # refresh committed floors
```

The default `pytest` run deselects `eval`/`eval_llm` markers so the fast suite
stays fast. Refresh the baseline only when a ranking change is intentional —
the diff to `results/bm25-baseline.jsonl` is the review surface. LLM-judge
content evals (`rubrics/`, `@pytest.mark.eval_llm`) are a later roadmap item.

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
