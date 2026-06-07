"""Read and write JSONL eval results and baselines under ``evals/results/``."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def write_results(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """Write rows as stable, sorted-key JSONL."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(row, sort_keys=True) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_results(path: Path) -> list[dict[str, Any]]:
    """Read JSONL rows; missing file yields an empty list."""

    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            rows.append(json.loads(stripped))
    return rows


def baseline_floors(
    rows: Iterable[dict[str, Any]],
    *,
    suite: str,
    scope: str,
) -> dict[str, float]:
    """Index committed baseline rows into ``{metric: floor_value}``."""

    floors: dict[str, float] = {}
    for row in rows:
        if row.get("suite") == suite and row.get("scope") == scope:
            floors[str(row["metric"])] = float(row["value"])
    return floors


__all__ = ["baseline_floors", "read_results", "write_results"]
