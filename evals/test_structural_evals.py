"""Deterministic golden-corpus structural evals (run with ``pytest -m eval``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.harness import structural, wiki_builder
from evals.harness.cases import CorpusCase, load_corpus_cases

pytestmark = pytest.mark.eval

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES = [
    case
    for case in load_corpus_cases(REPO_ROOT / "evals" / "corpus")
    if case.expected_structure is not None
]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_corpus_case_matches_expected_structure(case: CorpusCase, tmp_path: Path) -> None:
    """The current generation path must satisfy the case's structure contract."""

    home = tmp_path / "hermes-home"
    slug = f"eval-{case.name}"
    wiki_root = wiki_builder.build_corpus_wiki(
        home,
        slug=slug,
        domain=f"eval corpus: {case.name}",
        sources=case.sources,
    )
    with wiki_builder.wiki_env(home, slug=slug):
        from hermes_wiki.lint import lint_wiki

        health_score = lint_wiki(slug=slug).health_score

    assert case.expected_structure is not None
    violations = structural.evaluate_structure(
        wiki_root,
        case.expected_structure,
        health_score=health_score,
    )
    assert not violations, "structure violations:\n" + "\n".join(violations)
