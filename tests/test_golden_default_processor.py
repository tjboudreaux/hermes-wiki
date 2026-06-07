"""Golden snapshots pinning DefaultProcessor output for every sample source.

Regenerate after an intentional generation change with:

    UPDATE_GOLDEN=1 uv run pytest tests/test_golden_default_processor.py

and review the diff to ``tests/golden/default_processor/`` — that diff IS the
review surface for processor changes (audit item T2).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from evals.harness.wiki_builder import wiki_env
from fixtures import seed_data

GOLDEN_DIR = Path(__file__).resolve().parent / "golden" / "default_processor"
SOURCE_KINDS = ("article", "paper", "transcript", "unknown")

_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:?\d{2})?")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _normalize(text: str) -> str:
    return _DATE_RE.sub("<DATE>", _TIMESTAMP_RE.sub("<TS>", text))


def _snapshot(kind: str, tmp_path: Path) -> str:
    home = tmp_path / "hermes-home"
    slug = f"golden-{kind}"
    with wiki_env(home, slug=slug, user="golden-tester"):
        from hermes_wiki.management import create_wiki
        from hermes_wiki.pipeline import ingest_source

        create_wiki(slug, domain=f"golden snapshot: {kind}", author="golden-tester")
        result = ingest_source(
            str(seed_data.sample_source_path(kind)),
            wiki=slug,
            author="golden-tester",
            author_kind="human",
        )

    wiki_root = home / "wikis" / slug
    parts = [
        f"classified_as: {result.classified_as}",
        f"raw_snapshot: {_normalize(result.raw_snapshot)}",
        "",
    ]
    for page_id in result.pages_created:
        content = (wiki_root / f"{page_id}.md").read_text(encoding="utf-8")
        parts.append(f"--- page: {_normalize(page_id)} ---")
        parts.append(_normalize(content).rstrip())
        parts.append("")
    return "\n".join(parts) + "\n"


@pytest.mark.parametrize("kind", SOURCE_KINDS)
def test_default_processor_output_matches_golden(kind: str, tmp_path: Path) -> None:
    """Generated pages for each sample source byte-match the committed golden."""

    actual = _snapshot(kind, tmp_path)
    golden_path = GOLDEN_DIR / f"{kind}.txt"

    if os.environ.get("UPDATE_GOLDEN") == "1":
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(actual, encoding="utf-8")

    assert golden_path.is_file(), (
        f"missing golden snapshot {golden_path}; generate with UPDATE_GOLDEN=1"
    )
    expected = golden_path.read_text(encoding="utf-8")
    assert actual == expected, (
        f"DefaultProcessor output for {kind!r} diverged from the golden snapshot. "
        "If the change is intentional, regenerate with UPDATE_GOLDEN=1 and review the diff."
    )
