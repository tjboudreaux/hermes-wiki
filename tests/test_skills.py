"""Per-wiki skill assignment coverage."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hermes_wiki.management import create_wiki
from hermes_wiki.skills import (
    DEFAULT_WIKI_SKILLS,
    SkillsError,
    read_schema_skill_record,
    read_wiki_skills,
    set_wiki_skill,
)


@pytest.fixture
def wiki_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("USER", "skills-tester")
    result = create_wiki("ai-tooling", domain="AI tooling")
    return result.path


def _git_subject(root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "log", "-1", "--pretty=%s"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_new_wiki_schema_scaffolds_default_skills_block(wiki_root: Path) -> None:
    schema = (wiki_root / "SCHEMA.md").read_text(encoding="utf-8")

    assert schema.count("<!-- wiki-skills -->") == 1
    assert "ingestion: wiki:wiki-ingestion" in schema
    assert "writing: wiki:wiki-writing" in schema
    assert read_schema_skill_record(wiki_root) == DEFAULT_WIKI_SKILLS


def test_read_wiki_skills_returns_defaults_without_block(wiki_root: Path) -> None:
    schema_path = wiki_root / "SCHEMA.md"
    text = schema_path.read_text(encoding="utf-8")
    start = text.index("<!-- wiki-skills -->")
    end = text.index("```", text.index("```yaml", start) + 7) + 3
    schema_path.write_text(text[:start] + text[end:], encoding="utf-8")

    result = read_wiki_skills(wiki="ai-tooling")

    assert result["wiki"] == "ai-tooling"
    assert result["skills"] == DEFAULT_WIKI_SKILLS
    assert result["defaults"] == DEFAULT_WIKI_SKILLS


def test_set_wiki_skill_round_trips_in_place(wiki_root: Path) -> None:
    updated = set_wiki_skill("ingestion", "research-ingest", wiki="ai-tooling")

    assert updated["skills"]["ingestion"] == "research-ingest"
    assert updated["skills"]["writing"] == DEFAULT_WIKI_SKILLS["writing"]

    schema = (wiki_root / "SCHEMA.md").read_text(encoding="utf-8")
    assert schema.count("<!-- wiki-skills -->") == 1
    assert "ingestion: research-ingest" in schema
    assert "ingestion: wiki:wiki-ingestion" not in schema

    record = read_wiki_skills(wiki="ai-tooling")
    assert record["skills"]["ingestion"] == "research-ingest"
    assert record["skills"]["writing"] == DEFAULT_WIKI_SKILLS["writing"]


def test_set_wiki_skill_logs_and_commits(wiki_root: Path) -> None:
    set_wiki_skill("writing", "wiki:custom-writer", wiki="ai-tooling", author="curator")

    assert "wiki: skills set writing -> wiki:custom-writer [curator]" in _git_subject(wiki_root)
    log = (wiki_root / "log.md").read_text(encoding="utf-8")
    assert "skills" in log
    assert "wiki:custom-writer" in log
    assert (
        subprocess.run(
            ["git", "-C", str(wiki_root), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == ""
    )


def test_set_wiki_skill_rejects_unknown_kind(wiki_root: Path) -> None:
    with pytest.raises(SkillsError, match="unsupported skill kind"):
        set_wiki_skill("classification", "anything", wiki="ai-tooling")


@pytest.mark.parametrize("bad_name", ["", "   ", "two words", "bad\nline", ":leading-colon"])
def test_set_wiki_skill_rejects_invalid_names(wiki_root: Path, bad_name: str) -> None:
    with pytest.raises(SkillsError):
        set_wiki_skill("ingestion", bad_name, wiki="ai-tooling")


def test_skills_surface_hides_unknown_wiki(wiki_root: Path) -> None:
    with pytest.raises(SkillsError, match="not found or not visible"):
        read_wiki_skills(wiki="no-such-wiki")
    with pytest.raises(SkillsError, match="not found or not visible"):
        set_wiki_skill("ingestion", "anything", wiki="no-such-wiki")
