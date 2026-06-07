"""Retrieval and link-graph quality metrics for evals and health reporting."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence
from pathlib import Path
from sqlite3 import Connection
from typing import Any

_INDEX_LINK_RE = re.compile(r"\]\(([^)#?]+)\.md\)")


def precision_at_k(relevant: Sequence[str], ranked: Sequence[str], k: int) -> float:
    """Fraction of the top-k ranked ids that are relevant."""

    if k <= 0:
        return 0.0
    hits = sum(1 for item in ranked[:k] if item in set(relevant))
    return hits / k


def recall_at_k(relevant: Sequence[str], ranked: Sequence[str], k: int) -> float:
    """Fraction of relevant ids that appear in the top-k ranked ids."""

    if not relevant or k <= 0:
        return 0.0
    hits = sum(1 for item in set(relevant) if item in ranked[:k])
    return hits / len(set(relevant))


def reciprocal_rank(relevant: Sequence[str], ranked: Sequence[str]) -> float:
    """1/rank of the first relevant id in the ranking (0.0 when absent)."""

    targets = set(relevant)
    for index, item in enumerate(ranked):
        if item in targets:
            return 1.0 / (index + 1)
    return 0.0


def ndcg_at_k(relevant: Sequence[str], ranked: Sequence[str], k: int) -> float:
    """Binary-relevance normalized discounted cumulative gain at k."""

    if not relevant or k <= 0:
        return 0.0
    targets = set(relevant)
    dcg = sum(
        1.0 / math.log2(index + 2)
        for index, item in enumerate(ranked[:k])
        if item in targets
    )
    ideal_hits = min(len(targets), k)
    idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
    return dcg / idcg if idcg else 0.0


def retrieval_metrics(
    relevant: Sequence[str],
    ranked: Sequence[str],
    k: int,
) -> dict[str, float]:
    """All retrieval metrics for one query as a flat mapping."""

    return {
        f"precision_at_{k}": round(precision_at_k(relevant, ranked, k), 4),
        f"recall_at_{k}": round(recall_at_k(relevant, ranked, k), 4),
        "mrr": round(reciprocal_rank(relevant, ranked), 4),
        f"ndcg_at_{k}": round(ndcg_at_k(relevant, ranked, k), 4),
    }


def graph_metrics(conn: Connection, *, wiki_root: Path | None = None) -> dict[str, Any]:
    """Link-graph health metrics computed from the ``page_links`` projection.

    Pass ``wiki_root`` to also compute ``index_coverage`` (the fraction of
    non-archived pages linked from ``index.md``).
    """

    page_ids = {
        str(row["id"])
        for row in conn.execute(
            "SELECT id FROM pages WHERE COALESCE(archived, 0) = 0"
        ).fetchall()
    }
    links = [
        (str(row["source_page_id"]), str(row["target_page_id"]))
        for row in conn.execute(
            "SELECT source_page_id, target_page_id FROM page_links"
        ).fetchall()
    ]
    internal = [(s, t) for s, t in links if s in page_ids and t in page_ids]
    dangling = sum(1 for s, t in links if s in page_ids and t not in page_ids)
    inbound_targets = {t for _s, t in internal}
    orphan_count = len(page_ids - inbound_targets)

    metrics: dict[str, Any] = {
        "page_count": len(page_ids),
        "link_count": len(internal),
        "dangling_link_count": dangling,
        "orphan_count": orphan_count,
        "orphan_rate": round(orphan_count / len(page_ids), 4) if page_ids else 0.0,
        "mean_out_degree": (
            round(len(internal) / len(page_ids), 4) if page_ids else 0.0
        ),
        "component_count": _component_count(page_ids, internal),
    }
    if wiki_root is not None:
        metrics["index_coverage"] = round(_index_coverage(wiki_root, page_ids), 4)
    return metrics


def _component_count(page_ids: set[str], edges: list[tuple[str, str]]) -> int:
    """Weakly-connected component count over the internal link graph."""

    parent = {page_id: page_id for page_id in page_ids}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for source, target in edges:
        root_a, root_b = find(source), find(target)
        if root_a != root_b:
            parent[root_a] = root_b
    return len({find(page_id) for page_id in page_ids})


def _index_coverage(wiki_root: Path, page_ids: set[str]) -> float:
    """Fraction of pages reachable from ``index.md`` link targets."""

    if not page_ids:
        return 0.0
    index_path = wiki_root / "index.md"
    if not index_path.is_file():
        return 0.0
    indexed: set[str] = set()
    for match in _INDEX_LINK_RE.finditer(index_path.read_text(encoding="utf-8")):
        target = match.group(1).strip().lstrip("./")
        if target in page_ids:
            indexed.add(target)
    return len(indexed) / len(page_ids)


def aggregate_metrics(per_query: Sequence[dict[str, Any]]) -> dict[str, float]:
    """Mean of every numeric metric across per-query result rows."""

    if not per_query:
        return {}
    keys = [
        key
        for key, value in per_query[0].items()
        if isinstance(value, int | float) and not isinstance(value, bool)
    ]
    return {
        key: round(sum(float(row[key]) for row in per_query) / len(per_query), 4)
        for key in keys
    }


def dumps_metrics(metrics: dict[str, Any]) -> str:
    """Stable JSON rendering for reports and baselines."""

    return json.dumps(metrics, sort_keys=True)


__all__ = [
    "aggregate_metrics",
    "dumps_metrics",
    "graph_metrics",
    "ndcg_at_k",
    "precision_at_k",
    "recall_at_k",
    "reciprocal_rank",
    "retrieval_metrics",
]
