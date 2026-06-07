"""Link-graph health evals over fixture and corpus wikis (``pytest -m eval``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.harness import wiki_builder
from evals.harness.cases import CorpusCase, load_corpus_cases
from hermes_wiki import db
from hermes_wiki.metrics import graph_metrics

pytestmark = pytest.mark.eval

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES = load_corpus_cases(REPO_ROOT / "evals" / "corpus")


def test_clean_fixture_link_graph_is_fully_connected(tmp_path: Path) -> None:
    """The seeded clean wiki has a connected, orphan-free, fully indexed graph."""

    from fixtures.factory import build_clean_home

    fixture = build_clean_home(tmp_path / "hermes-home")
    with db.connect_wiki(fixture.primary_wiki_db) as conn:
        metrics = graph_metrics(conn, wiki_root=fixture.primary_wiki_root)

    assert metrics["page_count"] == 8
    assert metrics["dangling_link_count"] == 0
    assert metrics["orphan_count"] == 0
    assert metrics["component_count"] == 1
    assert metrics["index_coverage"] == 1.0


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_corpus_wiki_graph_has_no_dangling_links(case: CorpusCase, tmp_path: Path) -> None:
    """Generated corpus wikis never produce dangling links or unindexed pages.

    Orphan derived pages ARE currently expected from DefaultProcessor (each
    derived page links to its source page but nothing links back) — pinned at
    exactly one orphan per ingested source until F2/F3 improve cross-linking.
    """

    home = tmp_path / "hermes-home"
    slug = f"eval-{case.name}"
    wiki_root = wiki_builder.build_corpus_wiki(
        home,
        slug=slug,
        domain=f"eval corpus: {case.name}",
        sources=case.sources,
    )
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        metrics = graph_metrics(conn, wiki_root=wiki_root)

    assert metrics["dangling_link_count"] == 0
    assert metrics["index_coverage"] == 1.0
    assert metrics["orphan_count"] == len(case.sources)
