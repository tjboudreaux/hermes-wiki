"""Slash-command forwarding for the Hermes Wiki surface."""

from __future__ import annotations

import argparse
import contextlib
import io
import shlex

from hermes_wiki.management import NOT_FOUND_OR_NOT_VISIBLE
from hermes_wiki.tools import WRITE_PERMISSION_DENIED, _check_wiki_write_mode
from hermes_wiki.visibility import WikiVisibilityError, require_visible_wiki
from hermes_wiki_cli.cli import build_parser
from hermes_wiki_cli.cli import main as wiki_cli_main


def run_slash(raw_args: str) -> str:
    """Execute ``/wiki <verb> ...`` by forwarding to the wiki CLI.

    Hermes plugin slash command handlers receive only the text after the command
    name. Tests and TUI helpers may pass the full ``/wiki ...`` string, so this
    helper accepts both forms. Read commands are delegated directly to the CLI;
    mutating existing-wiki commands perform the same visibility-then-write-grant
    gate used by the agent write tools before delegation.
    """

    argv = _split_args(raw_args)
    gate_output = _write_gate_output(argv)
    if gate_output is not None:
        return gate_output
    return _run_cli(argv)


def _split_args(raw_args: str) -> list[str]:
    stripped = (raw_args or "").strip()
    if not stripped:
        return []
    try:
        argv = shlex.split(stripped)
    except ValueError as exc:
        return ["--__parse_error__", str(exc)]
    if argv and argv[0].lstrip("/").lower() == "wiki":
        argv = argv[1:]
    return argv


def _write_gate_output(argv: list[str]) -> str | None:
    if argv and argv[0] == "--__parse_error__":
        return f"wiki command parse error: {argv[1] if len(argv) > 1 else 'invalid arguments'}"

    parsed, parse_output = _parse(argv)
    if parsed is None:
        # Let argparse/CLI usage errors surface exactly as the CLI renders them.
        return parse_output

    if not _requires_write_grant(parsed):
        return None

    target = _target_wiki_for_write(parsed)
    try:
        slug, _wiki_root = require_visible_wiki(target)
    except WikiVisibilityError:
        return NOT_FOUND_OR_NOT_VISIBLE

    if not _check_wiki_write_mode(slug):
        return WRITE_PERMISSION_DENIED
    return None


def _parse(argv: list[str]) -> tuple[argparse.Namespace | None, str]:
    parser = build_parser()
    parser.set_defaults(_parser=parser)
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            return parser.parse_args(argv), ""
        except SystemExit:
            return None, _combined_output(stdout.getvalue(), stderr.getvalue())


def _requires_write_grant(args: argparse.Namespace) -> bool:
    verb = getattr(args, "wiki_command", None)
    if verb in {"archive", "unarchive", "ingest", "create-page", "link", "unlink", "monitor"}:
        return True
    if verb == "plugins" and getattr(args, "plugins_command", None) in {"trust", "untrust"}:
        return True
    return False


def _target_wiki_for_write(args: argparse.Namespace) -> str | None:
    return getattr(args, "wiki", None) or getattr(args, "slug", None)


def _run_cli(argv: list[str]) -> str:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        wiki_cli_main(argv)
    return _combined_output(stdout.getvalue(), stderr.getvalue())


def _combined_output(stdout: str, stderr: str) -> str:
    parts = [part.strip() for part in (stdout, stderr) if part.strip()]
    return "\n".join(parts)


__all__ = ["run_slash"]
