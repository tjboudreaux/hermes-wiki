"""Smoke tests for the initial Hermes Wiki package scaffold."""

from __future__ import annotations

import importlib.metadata

import pytest

from hermes_wiki_cli.cli import main


def test_package_is_importable() -> None:
    """The core package can be imported from an installed checkout."""
    module = __import__("hermes_wiki")

    assert module.__name__ == "hermes_wiki"
    assert isinstance(module.__version__, str)


def test_project_metadata_exposes_console_script() -> None:
    """The installed distribution exposes the standalone CLI entry point."""
    entry_points = importlib.metadata.entry_points(group="console_scripts")
    script_names = {entry_point.name for entry_point in entry_points}

    assert "hermes-wiki" in script_names


def test_project_metadata_summary_is_plugin_list_ready() -> None:
    """The package summary is suitable for ``hermes plugins list`` output."""
    metadata = importlib.metadata.metadata("hermes-wiki")

    assert metadata["Summary"].startswith("Karpathy-style LLM Wikis")


def test_cli_version_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    """The standalone CLI can execute a minimal version command."""
    exit_code = main(["--version"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "hermes-wiki" in output
