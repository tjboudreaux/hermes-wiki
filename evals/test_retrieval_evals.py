"""BM25 retrieval relevance evals against committed baselines (``pytest -m eval``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.harness import wiki_builder
from evals.harness.cases import CorpusCase, load_corpus_cases, load_qrels
from evals.harness.retrieval import evaluate_qrels
from evals.harness.store import baseline_floors, read_results

pytestmark = pytest.mark.eval

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPO_ROOT / "evals" / "results" / "bm25-baseline.jsonl"
RELEVANCE_CASES = [
    case
    for case in load_corpus_cases(REPO_ROOT / "evals" / "corpus")
    if case.relevance is not None
]


def _assert_meets_baseline(aggregate: dict[str, float], *, scope: str) -> None:
    floors = baseline_floors(read_results(BASELINE_PATH), suite="retrieval", scope=scope)
    assert floors, (
        f"no committed BM25 baseline for scope {scope!r} in {BASELINE_PATH}; "
        "regenerate with: uv run python -m evals.harness.runner capture-baseline"
    )
    drops = [
        f"{metric}: {aggregate.get(metric)} < baseline {floor}"
        for metric, floor in floors.items()
        if aggregate.get(metric, 0.0) < floor - 1e-9
    ]
    assert not drops, "retrieval regression vs committed baseline:\n" + "\n".join(drops)


def test_fixture_home_meets_bm25_baseline(tmp_path: Path) -> None:
    """Seeded fixture wiki retrieval quality must not regress below baseline."""

    from fixtures.factory import build_clean_home

    fixture = build_clean_home(tmp_path / "hermes-home")
    qrels = load_qrels(REPO_ROOT / "evals" / "retrieval" / "fixture-qrels.yaml")
    assert qrels
    with wiki_builder.wiki_env(fixture.home, slug=fixture.primary_slug):
        result = evaluate_qrels(qrels, wiki=fixture.primary_slug)
    _assert_meets_baseline(result["aggregate"], scope="fixture-home")


@pytest.mark.parametrize("case", RELEVANCE_CASES, ids=lambda case: case.name)
def test_corpus_case_meets_bm25_baseline(case: CorpusCase, tmp_path: Path) -> None:
    """Corpus-wiki retrieval quality must not regress below baseline."""

    home = tmp_path / "hermes-home"
    slug = f"eval-{case.name}"
    wiki_builder.build_corpus_wiki(
        home,
        slug=slug,
        domain=f"eval corpus: {case.name}",
        sources=case.sources,
    )
    assert case.relevance is not None
    with wiki_builder.wiki_env(home, slug=slug):
        result = evaluate_qrels(case.relevance, wiki=slug)
    _assert_meets_baseline(result["aggregate"], scope=case.name)
