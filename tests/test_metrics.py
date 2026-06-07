"""Retrieval and link-graph metric math (hermes_wiki.metrics)."""

from __future__ import annotations

from pathlib import Path

from hermes_wiki import db
from hermes_wiki.metrics import (
    aggregate_metrics,
    graph_metrics,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    retrieval_metrics,
)

RELEVANT = ["a", "b"]
RANKED = ["x", "a", "y", "b", "z"]


def test_precision_at_k_counts_relevant_hits_over_k() -> None:
    assert precision_at_k(RELEVANT, RANKED, 5) == 0.4
    assert precision_at_k(RELEVANT, RANKED, 2) == 0.5
    assert precision_at_k(RELEVANT, [], 5) == 0.0
    assert precision_at_k(RELEVANT, RANKED, 0) == 0.0


def test_recall_at_k_counts_found_relevant_over_total_relevant() -> None:
    assert recall_at_k(RELEVANT, RANKED, 5) == 1.0
    assert recall_at_k(RELEVANT, RANKED, 2) == 0.5
    assert recall_at_k([], RANKED, 5) == 0.0


def test_reciprocal_rank_uses_first_relevant_position() -> None:
    assert reciprocal_rank(RELEVANT, RANKED) == 0.5
    assert reciprocal_rank(["z"], RANKED) == 0.2
    assert reciprocal_rank(["missing"], RANKED) == 0.0


def test_ndcg_is_one_for_perfect_ranking_and_zero_for_miss() -> None:
    assert ndcg_at_k(["a", "b"], ["a", "b", "x"], 3) == 1.0
    assert ndcg_at_k(["a"], ["x", "y"], 2) == 0.0
    perfect = ndcg_at_k(RELEVANT, ["a", "b"], 5)
    imperfect = ndcg_at_k(RELEVANT, RANKED, 5)
    assert 0.0 < imperfect < perfect == 1.0


def test_retrieval_metrics_and_aggregate_round_trip() -> None:
    row = retrieval_metrics(RELEVANT, RANKED, 5)
    assert row == {
        "precision_at_5": 0.4,
        "recall_at_5": 1.0,
        "mrr": 0.5,
        "ndcg_at_5": round(ndcg_at_k(RELEVANT, RANKED, 5), 4),
    }
    aggregate = aggregate_metrics([row, {**row, "mrr": 1.0}])
    assert aggregate["mrr"] == 0.75
    assert aggregate["recall_at_5"] == 1.0


def test_graph_metrics_reports_orphans_dangling_and_components(tmp_path: Path) -> None:
    wiki_root = tmp_path / "wiki"
    wiki_root.mkdir()
    (wiki_root / "index.md").write_text(
        "\n".join(
            [
                "# Index",
                "- [A](concepts/a.md) — `concepts/a`",
                "- [B](concepts/b.md) — `concepts/b`",
            ]
        ),
        encoding="utf-8",
    )
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        db.initialize_wiki(conn)
        for page_id in ("concepts/a", "concepts/b", "concepts/island"):
            db.upsert_page(
                conn,
                id=page_id,
                title=page_id.rsplit("/", 1)[-1].title(),
                type="concept",
                created="2026-06-05T00:00:00Z",
                updated="2026-06-05T00:00:00Z",
                tags=(),
                sources=(),
                confidence="low",
                contested=0,
                contradictions=None,
                author="tests",
                author_kind="human",
                sha256="0" * 64,
                inbound_links=0,
                snippet=None,
                body_text="",
            )
        db.replace_page_links(
            conn,
            source_page_id="concepts/a",
            target_page_ids=["concepts/b", "concepts/missing"],
        )
        conn.commit()
        metrics = graph_metrics(conn, wiki_root=wiki_root)

    assert metrics["page_count"] == 3
    assert metrics["link_count"] == 1  # a -> b (a -> missing is dangling)
    assert metrics["dangling_link_count"] == 1
    assert metrics["orphan_count"] == 2  # a and island have no inbound links
    assert metrics["component_count"] == 2  # {a, b} and {island}
    assert metrics["index_coverage"] == round(2 / 3, 4)
