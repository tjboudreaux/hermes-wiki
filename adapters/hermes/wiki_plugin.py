"""Hermes plugin registration for the Wiki slash command."""

from __future__ import annotations

from typing import Any

from hermes_wiki.slash import run_slash


def register(ctx: Any) -> None:
    """Register ``/wiki`` as a Hermes in-session slash command."""

    ctx.register_command(
        "wiki",
        run_slash,
        description="Run Hermes Wiki CLI commands inside the current session.",
        args_hint="<verb> ...",
    )


__all__ = ["register"]
