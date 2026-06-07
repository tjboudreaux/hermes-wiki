"""Load corpus cases and relevance judgments (qrels) for the eval suites."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class CorpusCase:
    """One golden-corpus case: input sources plus expected outcomes."""

    name: str
    path: Path
    sources: tuple[Path, ...]
    expected_structure: dict[str, Any] | None
    relevance: list[dict[str, Any]] | None


def load_corpus_cases(corpus_dir: Path) -> tuple[CorpusCase, ...]:
    """Load every case directory under ``corpus_dir`` (sorted by name)."""

    cases: list[CorpusCase] = []
    for case_dir in sorted(path for path in corpus_dir.iterdir() if path.is_dir()):
        sources_dir = case_dir / "sources"
        sources = tuple(
            sorted(
                path
                for path in sources_dir.iterdir()
                if path.is_file() and not path.name.startswith(".")
            )
            if sources_dir.is_dir()
            else ()
        )
        cases.append(
            CorpusCase(
                name=case_dir.name,
                path=case_dir,
                sources=sources,
                expected_structure=_load_yaml(case_dir / "expected_structure.yaml"),
                relevance=load_qrels(case_dir / "relevance.yaml"),
            )
        )
    return tuple(cases)


def load_qrels(path: Path) -> list[dict[str, Any]] | None:
    """Load ``{queries: [{q, relevant: [...]}]}`` relevance judgments."""

    data = _load_yaml(path)
    if data is None:
        return None
    queries = data.get("queries")
    if not isinstance(queries, list):
        raise ValueError(f"qrels file missing 'queries' list: {path}")
    for entry in queries:
        if not isinstance(entry.get("q"), str) or not isinstance(entry.get("relevant"), list):
            raise ValueError(f"qrels entry needs 'q' and 'relevant': {entry!r} in {path}")
    return queries


def _load_yaml(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return None
    if not isinstance(loaded, dict):
        raise ValueError(f"expected a mapping at the top level of {path}")
    return loaded


__all__ = ["CorpusCase", "load_corpus_cases", "load_qrels"]
