"""Run relevance judgments against the live search surface and score them."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from hermes_wiki.metrics import aggregate_metrics, retrieval_metrics


def evaluate_qrels(
    qrels: Sequence[dict[str, Any]],
    *,
    wiki: str,
    k: int = 5,
) -> dict[str, Any]:
    """Score every qrels query via ``search_wiki`` (caller provides the env)."""

    from hermes_wiki.search import search_wiki

    per_query: list[dict[str, Any]] = []
    for entry in qrels:
        query = str(entry["q"])
        relevant = [str(item) for item in entry["relevant"]]
        ranked = [str(row["id"]) for row in search_wiki(query, wiki=wiki, limit=k)]
        metrics = retrieval_metrics(relevant, ranked, k)
        per_query.append({"q": query, "ranked": ranked, **metrics})

    return {
        "k": k,
        "wiki": wiki,
        "queries": per_query,
        "aggregate": aggregate_metrics(per_query),
    }


__all__ = ["evaluate_qrels"]
