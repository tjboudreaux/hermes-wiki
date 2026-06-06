"""Tests for the Hermes entry-point plugin (adapters.hermes.cli_plugin).

Verifies that the plugin registers both the ``hermes wiki`` CLI subcommand
and the ``/wiki`` in-session slash command via the standard PluginContext API.
"""

from __future__ import annotations

import argparse
import importlib.metadata
from collections.abc import Callable
from typing import Any

import pytest

from fixtures.factory import build_test_wiki


class FakePluginContext:
    """Minimal shim replicating Hermes PluginContext registration methods."""

    def __init__(self) -> None:
        self.cli_commands: dict[str, dict[str, Any]] = {}
        self.slash_commands: dict[str, dict[str, Any]] = {}

    def register_cli_command(
        self,
        name: str,
        help: str,
        setup_fn: Callable,
        handler_fn: Callable | None = None,
        description: str = "",
    ) -> None:
        self.cli_commands[name] = {
            "name": name,
            "help": help,
            "description": description,
            "setup_fn": setup_fn,
            "handler_fn": handler_fn,
        }

    def register_command(
        self,
        name: str,
        handler: Callable,
        description: str = "",
        args_hint: str = "",
    ) -> None:
        self.slash_commands[name] = {
            "name": name,
            "handler": handler,
            "description": description,
            "args_hint": args_hint,
        }


def test_register_exposes_wiki_cli_and_slash_command() -> None:
    """register(ctx) creates both a CLI subcommand and a slash command."""
    from adapters.hermes.cli_plugin import register

    ctx = FakePluginContext()
    register(ctx)

    assert "wiki" in ctx.cli_commands
    assert "wiki" in ctx.slash_commands


def test_cli_command_metadata_is_correct() -> None:
    """CLI command has proper name, help, and callable handler."""
    from adapters.hermes.cli_plugin import register

    ctx = FakePluginContext()
    register(ctx)

    cmd = ctx.cli_commands["wiki"]
    assert cmd["name"] == "wiki"
    assert "LLM Wiki" in cmd["help"]
    assert callable(cmd["setup_fn"])
    assert callable(cmd["handler_fn"])


def test_slash_command_metadata_is_correct() -> None:
    """Slash command has handler and args_hint."""
    from adapters.hermes.cli_plugin import register

    ctx = FakePluginContext()
    register(ctx)

    cmd = ctx.slash_commands["wiki"]
    assert cmd["name"] == "wiki"
    assert callable(cmd["handler"])
    assert cmd["args_hint"] == "<verb> ..."


def test_setup_fn_builds_argparse_subcommands() -> None:
    """The setup_fn populates a subparser with wiki management commands."""
    from adapters.hermes.cli_plugin import register

    ctx = FakePluginContext()
    register(ctx)

    parser = argparse.ArgumentParser(prog="hermes")
    subparsers = parser.add_subparsers(dest="command")
    wiki_parser = subparsers.add_parser("wiki", help="test")

    setup_fn = ctx.cli_commands["wiki"]["setup_fn"]
    setup_fn(wiki_parser)

    args = parser.parse_args(["wiki", "list"])
    assert args.wiki_command == "list"


def test_handler_fn_dispatches_list(
    monkeypatch: Any, tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """The handler_fn (wiki_command) dispatches subcommands correctly."""
    fixture = build_test_wiki(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture.home))

    from adapters.hermes.cli_plugin import register

    ctx = FakePluginContext()
    register(ctx)

    parser = argparse.ArgumentParser(prog="hermes")
    subparsers = parser.add_subparsers(dest="command")
    wiki_parser = subparsers.add_parser("wiki")
    ctx.cli_commands["wiki"]["setup_fn"](wiki_parser)
    wiki_parser.set_defaults(func=ctx.cli_commands["wiki"]["handler_fn"])

    args = parser.parse_args(["wiki", "list"])
    exit_code = args.func(args)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert fixture.primary_slug in output


def test_handler_fn_dispatches_search(
    monkeypatch: Any, tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """Search verb works through the plugin handler."""
    fixture = build_test_wiki(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture.home))

    from adapters.hermes.cli_plugin import register

    ctx = FakePluginContext()
    register(ctx)

    parser = argparse.ArgumentParser(prog="hermes")
    subparsers = parser.add_subparsers(dest="command")
    wiki_parser = subparsers.add_parser("wiki")
    ctx.cli_commands["wiki"]["setup_fn"](wiki_parser)
    wiki_parser.set_defaults(func=ctx.cli_commands["wiki"]["handler_fn"])

    args = parser.parse_args(["wiki", "search", "memory", "--wiki", fixture.primary_slug])
    exit_code = args.func(args)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "concepts/agent-memory" in output


def test_slash_handler_equivalence(monkeypatch: Any, tmp_path: Any) -> None:
    """The slash handler delegates to the same run_slash implementation."""
    fixture = build_test_wiki(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture.home))

    from adapters.hermes.cli_plugin import register
    from hermes_wiki.slash import run_slash

    ctx = FakePluginContext()
    register(ctx)

    direct = run_slash("list")
    handler = ctx.slash_commands["wiki"]["handler"]
    via_plugin = handler("list")

    assert direct == via_plugin


def test_entry_point_is_declared_in_pyproject() -> None:
    """The hermes_agent.plugins entry point is defined for the installed package."""
    eps = importlib.metadata.entry_points()
    if hasattr(eps, "select"):
        group_eps = eps.select(group="hermes_agent.plugins")
    elif isinstance(eps, dict):
        group_eps = eps.get("hermes_agent.plugins", [])
    else:
        group_eps = [ep for ep in eps if ep.group == "hermes_agent.plugins"]

    names = {ep.name for ep in group_eps}
    assert "wiki" in names, (
        "Entry point 'wiki' not found in 'hermes_agent.plugins' group. "
        "Run 'uv sync' to install."
    )


def test_entry_point_resolves_to_register() -> None:
    """The entry point reference loads correctly and has a register function."""
    eps = importlib.metadata.entry_points()
    if hasattr(eps, "select"):
        group_eps = list(eps.select(group="hermes_agent.plugins"))
    elif isinstance(eps, dict):
        group_eps = eps.get("hermes_agent.plugins", [])
    else:
        group_eps = [ep for ep in eps if ep.group == "hermes_agent.plugins"]

    wiki_eps = [ep for ep in group_eps if ep.name == "wiki"]
    assert len(wiki_eps) == 1

    module = wiki_eps[0].load()
    assert hasattr(module, "register")
    assert callable(module.register)
