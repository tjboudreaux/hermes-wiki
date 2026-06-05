"""Tests for shared slug/profile validators."""

from __future__ import annotations

import pytest

from hermes_wiki import templates
from hermes_wiki._validators import ValidationError, validate_profile, validate_slug
from hermes_wiki.home import WikiResolutionError, resolve_wiki


def test_validate_slug_is_shared_by_templates_and_home(tmp_path, monkeypatch) -> None:
    """Templates and resolution use the same lowercase slug rule."""
    assert validate_slug("ai-tooling") == "ai-tooling"
    with pytest.raises(ValidationError, match="invalid wiki slug"):
        validate_slug("Has Spaces/Bad")
    with pytest.raises(ValueError, match="invalid wiki slug"):
        templates.generate_schema_markdown(slug="Has Spaces", created="2026-06-05T00:00:00Z")

    (tmp_path / "wikis").mkdir()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    with pytest.raises(WikiResolutionError, match="invalid wiki slug"):
        resolve_wiki(wiki="Has Spaces", env={})


def test_validate_profile_uses_shared_profile_rule() -> None:
    """Profile current marker names are validated centrally."""
    assert validate_profile("test-profile") == "test-profile"
    with pytest.raises(ValidationError, match="invalid profile name"):
        validate_profile("../outside")
