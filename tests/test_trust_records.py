"""SCHEMA.md trusted-plugin block round-trip behavior."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hermes_wiki.trust import _replace_schema_trust_record, read_schema_trust_records
from hermes_wiki_cli.cli import main


def _create_wiki(tmp_path: Path, slug: str) -> Path:
    merged = {"HERMES_HOME": str(tmp_path), "USER": "trust-tester"}
    old = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(merged)
        assert main(["create", slug]) == 0
    finally:
        os.environ.clear()
        os.environ.update(old)
    return tmp_path / "wikis" / slug


@pytest.mark.parametrize(
    "author",
    [
        "trust-tester",
        "alice@example.com",
        "cron:nightly-sweep",
        "Release Manager: Alice",  # ": " is a YAML mapping indicator
        '"already quoted"',
        "[bracketed] author #with-comment",
    ],
)
def test_trust_record_author_round_trips_through_yaml(tmp_path: Path, author: str) -> None:
    """Free-text authors must survive the SCHEMA.md yaml.safe_load round-trip."""

    wiki_root = _create_wiki(tmp_path, "ai-tooling")

    _replace_schema_trust_record(
        wiki_root,
        kind="classifier",
        name="widget",
        path="plugins/classifiers/widget.py",
        sha256="ab" * 32,
        trusted_at="2026-06-07T00:00:00Z",
        author=author,
    )

    records = read_schema_trust_records(wiki_root)
    matching = [record for record in records if record.get("name") == "widget"]
    assert len(matching) == 1, f"trust block failed to parse for author {author!r}"
    assert matching[0]["author"] == author
    assert matching[0]["kind"] == "classifier"
    assert matching[0]["sha256"] == "ab" * 32
