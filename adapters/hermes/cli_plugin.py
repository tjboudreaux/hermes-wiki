"""Hermes entry-point plugin for the Wiki CLI and slash command.

Discovered via the ``hermes_agent.plugins`` entry-point group defined in
``pyproject.toml``. When activated, registers:

1. ``hermes wiki <verb> …`` — a top-level CLI subcommand (mirrors kanban)
2. ``/wiki <verb> …`` — an in-session slash command
"""

from __future__ import annotations

from typing import Any


def register(ctx: Any) -> None:
    """Plugin entry point called by Hermes' PluginManager."""

    _register_cli(ctx)
    _register_slash(ctx)


def _register_cli(ctx: Any) -> None:
    """Register ``hermes wiki`` as a CLI subcommand."""

    from hermes_wiki_cli.cli import wiki_command

    def setup_wiki_parser(subparser: Any) -> None:
        from hermes_wiki_cli.cli import _add_management_subcommands

        _add_management_subcommands(subparser.add_subparsers(dest="wiki_command"))

    ctx.register_cli_command(
        name="wiki",
        help="Manage Hermes LLM Wikis — create, ingest, search, lint, and curate",
        setup_fn=setup_wiki_parser,
        handler_fn=wiki_command,
        description=(
            "Create, list, show, switch, ingest, search, lint, and archive "
            "Hermes LLM Wikis. Implements Karpathy's LLM Wiki pattern as a "
            "first-class Hermes surface."
        ),
    )


def _register_slash(ctx: Any) -> None:
    """Register ``/wiki`` as an in-session slash command."""

    from hermes_wiki.slash import run_slash

    ctx.register_command(
        "wiki",
        run_slash,
        description="Run Hermes Wiki CLI commands inside the current session.",
        args_hint="<verb> ...",
    )


__all__ = ["register"]
