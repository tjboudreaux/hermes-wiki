from __future__ import annotations

from pathlib import Path
from typing import Any

from fixtures.factory import build_test_wiki


def _write_config(home: Path, text: str) -> None:
    (home / "config.yaml").write_text(text, encoding="utf-8")


def _block_slugs(block: str) -> set[str]:
    slugs: set[str] = set()
    for line in block.splitlines():
        if line.startswith("- "):
            slugs.add(line[2:].split(":", 1)[0])
    return slugs


def test_available_wikis_block_lists_exact_visible_set_with_metadata(
    monkeypatch: Any, tmp_path: Path
) -> None:
    fixture = build_test_wiki(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture.home))

    from hermes_wiki.prompt import available_wikis_block

    block = available_wikis_block(profile=fixture.profile)

    assert "# Available Wikis" in block
    assert _block_slugs(block) == {fixture.primary_slug}
    assert fixture.private_slug not in block
    assert fixture.archived_slug not in block
    assert (
        f"- {fixture.primary_slug}: AI agents, coding tools, and research workflows "
        f"({len(fixture.page_ids)} pages, health 0.72)"
    ) in block
    assert "Use wiki_search" in block


def test_visibility_rules_cover_private_blacklist_whitelist_and_archived(
    monkeypatch: Any, tmp_path: Path
) -> None:
    fixture = build_test_wiki(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture.home))

    from hermes_wiki.visibility import resolve_visible_wikis

    assert {row["slug"] for row in resolve_visible_wikis()} == {fixture.primary_slug}

    _write_config(
        fixture.home,
        f"wiki:\n  blacklist: [{fixture.primary_slug}]\n",
    )
    assert resolve_visible_wikis() == []

    _write_config(
        fixture.home,
        f"wiki:\n  default_access: discoverable\n  whitelist: [{fixture.private_slug}]\n",
    )
    assert {row["slug"] for row in resolve_visible_wikis()} == {fixture.private_slug}

    _write_config(
        fixture.home,
        (
            "wiki:\n"
            f"  whitelist: [{fixture.primary_slug}, {fixture.archived_slug}]\n"
            f"  blacklist: [{fixture.primary_slug}]\n"
        ),
    )
    assert {row["slug"] for row in resolve_visible_wikis()} == {fixture.primary_slug}


def test_empty_visible_set_prompt_is_safe(monkeypatch: Any, tmp_path: Path) -> None:
    fixture = build_test_wiki(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture.home))
    _write_config(fixture.home, "wiki:\n  whitelist: [does-not-exist]\n")

    from hermes_wiki.prompt import available_wikis_block

    block = available_wikis_block()

    assert block.startswith("# Available Wikis")
    assert _block_slugs(block) == set()
    assert "No visible wikis." in block
    assert fixture.primary_slug not in block
    assert fixture.private_slug not in block
    assert fixture.archived_slug not in block


def test_denied_lookup_is_exact_and_does_not_disclose_slug(
    monkeypatch: Any, tmp_path: Path
) -> None:
    fixture = build_test_wiki(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture.home))

    from hermes_wiki.tools import wiki_health_check, wiki_list, wiki_search
    from hermes_wiki.visibility import NOT_FOUND_OR_NOT_VISIBLE, require_visible_wiki

    try:
        require_visible_wiki(fixture.private_slug)
    except Exception as exc:
        assert str(exc) == NOT_FOUND_OR_NOT_VISIBLE
        assert fixture.private_slug not in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("private wiki unexpectedly visible")

    for result in (
        wiki_search("secret", wiki=fixture.private_slug),
        wiki_health_check(wiki=fixture.private_slug),
        wiki_list(wiki=fixture.private_slug),
    ):
        assert result == NOT_FOUND_OR_NOT_VISIBLE
        assert fixture.private_slug not in str(result)


def test_write_grant_gating_is_separate_from_visibility(
    monkeypatch: Any, tmp_path: Path
) -> None:
    fixture = build_test_wiki(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture.home))
    monkeypatch.delenv("HERMES_WIKI", raising=False)

    from hermes_wiki.visibility import has_write_grant

    assert not has_write_grant(fixture.primary_slug)
    assert not has_write_grant(fixture.private_slug)

    _write_config(fixture.home, f"wiki:\n  write_grants: [{fixture.primary_slug}]\n")
    assert has_write_grant(fixture.primary_slug)
    assert not has_write_grant(fixture.private_slug)

    _write_config(fixture.home, 'wiki:\n  write_grants: ["*"]\n')
    assert has_write_grant(fixture.primary_slug)
    assert has_write_grant(fixture.private_slug)

    monkeypatch.setenv("HERMES_WIKI", fixture.primary_slug)
    _write_config(fixture.home, "wiki:\n  write_grants: []\n")
    assert has_write_grant(fixture.primary_slug)
    assert not has_write_grant(fixture.private_slug)
