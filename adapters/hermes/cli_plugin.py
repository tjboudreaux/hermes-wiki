"""Hermes entry-point plugin for the Wiki CLI and slash command.

Discovered via the ``hermes_agent.plugins`` entry-point group defined in
``pyproject.toml``. When activated, registers:

1. ``hermes wiki <verb> …`` — a top-level CLI subcommand (mirrors kanban)
2. ``/wiki <verb> …`` — an in-session slash command
3. Packaged wiki skills — resolvable as ``wiki:<skill-name>``
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

SKILLS_ROOT = Path(__file__).resolve().parent / "skills"


def register(ctx: Any) -> None:
    """Plugin entry point called by Hermes' PluginManager."""

    _register_cli(ctx)
    _register_slash(ctx)
    _register_skills(ctx)


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


def _register_skills(ctx: Any) -> None:
    """Register packaged SKILL.md files as ``wiki:<name>`` plugin skills.

    Older Hermes versions without ``register_skill`` are tolerated silently so
    the CLI and slash surfaces keep working.
    """

    register_skill = getattr(ctx, "register_skill", None)
    if not callable(register_skill) or not SKILLS_ROOT.is_dir():
        return
    for skill_dir in sorted(SKILLS_ROOT.iterdir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        register_skill(
            name=skill_dir.name,
            path=skill_md,
            description=_skill_description(skill_md),
        )


def _skill_description(skill_md: Path) -> str:
    """Pull the frontmatter ``description`` without requiring a YAML parser."""

    for line in skill_md.read_text(encoding="utf-8").splitlines():
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip().strip('"')
    return ""


__all__ = ["SKILLS_ROOT", "register"]
