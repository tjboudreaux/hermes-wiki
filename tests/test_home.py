"""Tests for Hermes Wiki home and current-wiki resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from adapters.standalone import StandaloneHomeResolver
from hermes_wiki.home import WikiResolutionError, resolve_home, resolve_wiki


def _wiki(home: Path, slug: str) -> Path:
    path = home / "wikis" / slug
    path.mkdir(parents=True)
    return path


def test_resolve_home_uses_home_seam(tmp_path: Path) -> None:
    """Home resolution delegates to the injected Home seam."""
    resolver = StandaloneHomeResolver(home_path=tmp_path)

    assert resolve_home(resolver) == tmp_path


def test_explicit_wiki_param_wins_over_env_current_and_default(tmp_path: Path) -> None:
    """The explicit wiki parameter is the highest-precedence cascade tier."""
    _wiki(tmp_path, "param")
    _wiki(tmp_path, "env")
    _wiki(tmp_path, "current")
    _wiki(tmp_path, "fallback")
    (tmp_path / "wikis" / "research.current").write_text("current\n", encoding="utf-8")
    (tmp_path / "wikis" / "default").write_text("fallback\n", encoding="utf-8")

    resolved = resolve_wiki(
        wiki="param",
        profile="research",
        home_resolver=StandaloneHomeResolver(home_path=tmp_path),
        env={"HERMES_WIKI": "env"},
    )

    assert resolved.slug == "param"
    assert resolved.path == tmp_path / "wikis" / "param"
    assert resolved.source == "param"


def test_hermes_wiki_env_wins_over_current_and_default(tmp_path: Path) -> None:
    """HERMES_WIKI is used when no explicit wiki parameter is provided."""
    _wiki(tmp_path, "env")
    _wiki(tmp_path, "current")
    _wiki(tmp_path, "fallback")
    (tmp_path / "wikis" / "research.current").write_text("current\n", encoding="utf-8")
    (tmp_path / "wikis" / "default").write_text("fallback\n", encoding="utf-8")

    resolved = resolve_wiki(
        profile="research",
        home_resolver=StandaloneHomeResolver(home_path=tmp_path),
        env={"HERMES_WIKI": " env "},
    )

    assert resolved.slug == "env"
    assert resolved.source == "env"


def test_profile_current_wins_over_default_and_is_profile_local(tmp_path: Path) -> None:
    """A profile current file is scoped to the requested profile only."""
    _wiki(tmp_path, "research-wiki")
    _wiki(tmp_path, "coding-wiki")
    _wiki(tmp_path, "fallback")
    (tmp_path / "wikis" / "research.current").write_text("research-wiki\n", encoding="utf-8")
    (tmp_path / "wikis" / "coding.current").write_text("coding-wiki\n", encoding="utf-8")
    (tmp_path / "wikis" / "default").write_text("fallback\n", encoding="utf-8")
    resolver = StandaloneHomeResolver(home_path=tmp_path)

    research = resolve_wiki(profile="research", home_resolver=resolver, env={})
    coding = resolve_wiki(profile="coding", home_resolver=resolver, env={})
    anonymous = resolve_wiki(home_resolver=resolver, env={})

    assert research.slug == "research-wiki"
    assert research.source == "profile-current"
    assert coding.slug == "coding-wiki"
    assert coding.source == "profile-current"
    assert anonymous.slug == "fallback"
    assert anonymous.source == "default"


def test_default_file_used_when_higher_tiers_absent(tmp_path: Path) -> None:
    """The default pointer is the final successful cascade tier."""
    _wiki(tmp_path, "fallback")
    (tmp_path / "wikis" / "default").write_text("fallback\n", encoding="utf-8")

    resolved = resolve_wiki(
        profile="missing-profile",
        home_resolver=StandaloneHomeResolver(home_path=tmp_path),
        env={},
    )

    assert resolved.slug == "fallback"
    assert resolved.path == tmp_path / "wikis" / "fallback"
    assert resolved.source == "default"


def test_bogus_hermes_wiki_env_errors_without_falling_through(tmp_path: Path) -> None:
    """A bad HERMES_WIKI value must not silently fall through to the default wiki."""
    _wiki(tmp_path, "fallback")
    (tmp_path / "wikis" / "default").write_text("fallback\n", encoding="utf-8")

    with pytest.raises(WikiResolutionError, match=r"HERMES_WIKI.*missing"):
        resolve_wiki(
            home_resolver=StandaloneHomeResolver(home_path=tmp_path),
            env={"HERMES_WIKI": "missing"},
        )


def test_exhausted_cascade_raises_clean_error(tmp_path: Path) -> None:
    """No flag/env/current/default produces a typed, non-crashing error."""
    (tmp_path / "wikis").mkdir()

    with pytest.raises(WikiResolutionError, match="No wiki could be resolved"):
        resolve_wiki(
            profile="research",
            home_resolver=StandaloneHomeResolver(home_path=tmp_path),
            env={},
        )


@pytest.mark.parametrize("bad_slug", ["../outside", "/absolute", "nested/wiki", ".", ".."])
def test_invalid_slug_values_raise_clean_error(tmp_path: Path, bad_slug: str) -> None:
    """Resolution rejects path-like slug values before touching the filesystem."""
    _wiki(tmp_path, "fallback")
    (tmp_path / "wikis" / "default").write_text("fallback\n", encoding="utf-8")

    with pytest.raises(WikiResolutionError, match="invalid wiki slug"):
        resolve_wiki(
            wiki=bad_slug,
            home_resolver=StandaloneHomeResolver(home_path=tmp_path),
            env={},
        )
