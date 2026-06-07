"""F9: Available Wikis block instructs agents to load assigned wiki skills.

Plugin-registered skills are explicit-load only in Hermes (they never appear
in the host's ``<available_skills>`` system-prompt section), so the wiki
discovery block must carry the loading instruction itself — plus per-wiki
``skills:`` annotations when a wiki overrides the defaults in SCHEMA.md.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from fixtures.factory import build_test_wiki
from hermes_wiki.skills import DEFAULT_WIKI_SKILLS, render_skills_block


def _block(profile: str | None = None) -> str:
    from hermes_wiki.prompt import available_wikis_block

    return available_wikis_block(profile=profile)


def _strip_skills_blocks(text: str) -> str:
    from hermes_wiki.skills import _SKILLS_BLOCK_RE

    return _SKILLS_BLOCK_RE.sub("\n", text)


def _append_skills_block(wiki_root: Path, skills: dict[str, str]) -> None:
    """Replace the wiki's canonical skills block (starter SCHEMA.md ships one)."""

    schema = wiki_root / "SCHEMA.md"
    text = _strip_skills_blocks(schema.read_text(encoding="utf-8"))
    schema.write_text(text.rstrip() + render_skills_block(skills) + "\n", encoding="utf-8")


def _append_raw_marker_block(wiki_root: Path, body: str) -> None:
    schema = wiki_root / "SCHEMA.md"
    text = _strip_skills_blocks(schema.read_text(encoding="utf-8"))
    schema.write_text(
        text.rstrip() + f"\n\n<!-- wiki-skills -->\n```yaml\n{body}\n```\n",
        encoding="utf-8",
    )


@pytest.fixture
def fixture_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    fixture = build_test_wiki(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture.home))
    return fixture


# --- Guidance lines -----------------------------------------------------------


def test_write_guidance_line_present_with_visible_wikis(fixture_home: Any) -> None:
    """Agents are told to load the default wiki skills before any write."""

    from hermes_wiki.prompt import WRITE_GUIDANCE_LINE

    block = _block(fixture_home.profile)
    assert WRITE_GUIDANCE_LINE in block
    assert 'skill_view("wiki:wiki-ingestion")' in block
    assert 'skill_view("wiki:wiki-writing")' in block
    # Read guidance is unchanged and precedes the write guidance.
    assert block.index("Use wiki_search") < block.index("Before writing")


def test_write_guidance_absent_when_no_wikis_visible(
    fixture_home: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With nothing to write to, the block must not instruct skill loading."""

    (fixture_home.home / "config.yaml").write_text(
        "wiki:\n  whitelist: [does-not-exist]\n", encoding="utf-8"
    )
    from hermes_wiki.prompt import EMPTY_GUIDANCE_LINE, WRITE_GUIDANCE_LINE

    block = _block()
    assert EMPTY_GUIDANCE_LINE in block
    assert WRITE_GUIDANCE_LINE not in block
    assert "skill_view" not in block


# --- Per-wiki skills annotations ----------------------------------------------


def test_default_assignments_render_no_suffix(fixture_home: Any) -> None:
    """Default skills are covered by the guidance line, not per-wiki noise."""

    block = _block(fixture_home.profile)
    assert "(skills:" not in block
    assert (
        f"- {fixture_home.primary_slug}: AI agents, coding tools, and research workflows "
        f"({len(fixture_home.page_ids)} pages, health 0.72)\n"
    ) in block + "\n"


def test_override_via_public_api_is_annotated(
    fixture_home: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An assignment set through set_wiki_skill shows up in the block."""

    monkeypatch.setenv("HERMES_WIKI", fixture_home.primary_slug)
    monkeypatch.setenv("USER", "prompt-tester")
    from hermes_wiki.skills import set_wiki_skill

    set_wiki_skill("ingestion", "research:custom-ingest", wiki=fixture_home.primary_slug)

    block = _block(fixture_home.profile)
    assert "(skills: ingestion=research:custom-ingest)" in block
    assert "writing=" not in block  # unchanged kind stays unlisted


def test_both_overrides_render_sorted_by_kind(fixture_home: Any) -> None:
    _append_skills_block(
        fixture_home.primary_wiki_root,
        {"ingestion": "lab:ingest.v2-x", "writing": "lab:write.v2-x"},
    )

    block = _block(fixture_home.profile)
    assert "(skills: ingestion=lab:ingest.v2-x, writing=lab:write.v2-x)" in block


def test_block_restating_defaults_renders_no_suffix(fixture_home: Any) -> None:
    """Explicitly writing the default values is not an override."""

    _append_skills_block(fixture_home.primary_wiki_root, dict(DEFAULT_WIKI_SKILLS))

    assert "(skills:" not in _block(fixture_home.profile)


def test_special_character_skill_names_round_trip(fixture_home: Any) -> None:
    _append_skills_block(fixture_home.primary_wiki_root, {"writing": "team:notes_writer.v1-beta"})

    assert "(skills: writing=team:notes_writer.v1-beta)" in _block(fixture_home.profile)


# --- Fail-safe behavior --------------------------------------------------------


def test_malformed_yaml_block_falls_back_silently(fixture_home: Any) -> None:
    _append_raw_marker_block(
        fixture_home.primary_wiki_root, "wiki_skills:\n  ingestion: [unclosed"
    )

    block = _block(fixture_home.profile)
    assert fixture_home.primary_slug in block
    assert "(skills:" not in block


def test_non_mapping_skills_record_falls_back_silently(fixture_home: Any) -> None:
    _append_raw_marker_block(fixture_home.primary_wiki_root, "wiki_skills:\n- not\n- a\n- map")

    block = _block(fixture_home.profile)
    assert fixture_home.primary_slug in block
    assert "(skills:" not in block


def test_blank_and_non_string_values_are_ignored(fixture_home: Any) -> None:
    _append_raw_marker_block(
        fixture_home.primary_wiki_root,
        "wiki_skills:\n  ingestion: '   '\n  writing: 7",
    )

    block = _block(fixture_home.profile)
    assert fixture_home.primary_slug in block
    assert "(skills:" not in block


def test_missing_schema_md_renders_without_suffix(fixture_home: Any) -> None:
    (fixture_home.primary_wiki_root / "SCHEMA.md").unlink()

    block = _block(fixture_home.profile)
    assert fixture_home.primary_slug in block
    assert "(skills:" not in block


def test_registry_row_without_path_does_not_break_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Corrupt registry rows degrade to a plain line, never an exception."""

    from hermes_wiki import prompt

    rows = [
        {"slug": "pathless", "domain": "broken row", "page_count": 3, "health_score": 1.0},
        {"slug": "nullpath", "domain": "broken row", "page_count": 1, "path": None},
    ]
    monkeypatch.setattr(prompt, "resolve_visible_wikis", lambda **_kwargs: rows)

    block = prompt.available_wikis_block()
    assert "- pathless: broken row (3 pages, health 1.00)" in block
    assert "- nullpath: broken row (1 pages, health unknown)" in block
    assert "(skills:" not in block


def test_registry_row_with_nonexistent_path_renders_plain_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hermes_wiki import prompt

    rows = [
        {
            "slug": "ghost",
            "domain": "missing on disk",
            "page_count": 0,
            "health_score": 1.0,
            "path": str(tmp_path / "does-not-exist"),
        }
    ]
    monkeypatch.setattr(prompt, "resolve_visible_wikis", lambda **_kwargs: rows)

    block = prompt.available_wikis_block()
    assert "- ghost: missing on disk (0 pages, health 1.00)" in block
    assert "(skills:" not in block


# --- Visibility boundaries ------------------------------------------------------


def test_private_wiki_overrides_never_leak(fixture_home: Any) -> None:
    """A hidden wiki's skill names must not appear anywhere in the block."""

    _append_skills_block(
        fixture_home.private_wiki_root, {"writing": "secret:private-writer"}
    )

    block = _block(fixture_home.profile)
    assert fixture_home.private_slug not in block
    assert "secret:private-writer" not in block


def test_archived_wiki_overrides_never_leak(fixture_home: Any) -> None:
    _append_skills_block(
        fixture_home.archived_wiki_root, {"ingestion": "secret:archived-ingest"}
    )

    block = _block(fixture_home.profile)
    assert fixture_home.archived_slug not in block
    assert "secret:archived-ingest" not in block


# --- Determinism and multi-wiki rendering ---------------------------------------


def test_block_is_deterministic_across_calls(fixture_home: Any) -> None:
    _append_skills_block(fixture_home.primary_wiki_root, {"ingestion": "lab:ingest"})

    assert _block(fixture_home.profile) == _block(fixture_home.profile)


def test_multi_wiki_block_sorts_slugs_and_mixes_suffixes(
    fixture_home: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wikis stay slug-sorted; only overridden ones carry annotations."""

    from hermes_wiki_cli.cli import main

    merged = {"HERMES_HOME": str(fixture_home.home), "USER": "prompt-tester"}
    old = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(merged)
        assert main(["create", "zz-extra", "--domain", "Extra domain"]) == 0
    finally:
        os.environ.clear()
        os.environ.update(old)
    _append_skills_block(
        fixture_home.home / "wikis" / "zz-extra", {"writing": "extra:writer"}
    )

    block = _block(fixture_home.profile)
    lines = [line for line in block.splitlines() if line.startswith("- ")]
    assert [line.split(":", 1)[0] for line in lines] == [
        f"- {fixture_home.primary_slug}",
        "- zz-extra",
    ]
    assert "(skills:" not in lines[0]
    assert lines[1].endswith("(skills: writing=extra:writer)")
