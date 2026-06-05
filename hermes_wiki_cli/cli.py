"""CLI surface for Hermes Wiki management commands."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Any

from hermes_wiki import __version__
from hermes_wiki.management import (
    WikiManagementError,
    archive_wiki,
    create_wiki,
    current_profile,
    list_visible_wikis,
    show_wiki,
    switch_wiki,
)


def build_parser(
    parent_subparsers: argparse._SubParsersAction[argparse.ArgumentParser] | None = None,
) -> argparse.ArgumentParser:
    """Build the wiki parser.

    When ``parent_subparsers`` is provided this mirrors Hermes' built-in
    ``hermes_cli.kanban.build_parser`` shape and attaches a ``wiki`` command
    under the existing top-level CLI. With no parent, it builds the standalone
    ``hermes-wiki`` executable used by tests and isolated development.
    """

    if parent_subparsers is None:
        parser = argparse.ArgumentParser(
            prog="hermes-wiki",
            description="Hermes Wiki management CLI",
        )
        _add_version(parser)
        _add_management_subcommands(parser.add_subparsers(dest="wiki_command"))
        parser.set_defaults(func=wiki_command)
        return parser

    parser = parent_subparsers.add_parser(
        "wiki",
        help="Manage Hermes LLM Wikis",
        description="Create, list, show, switch, and archive Hermes LLM Wikis.",
    )
    _add_management_subcommands(parser.add_subparsers(dest="wiki_command"))
    parser.set_defaults(func=wiki_command)
    return parser


def wiki_command(args: argparse.Namespace) -> int:
    """Dispatch ``hermes wiki …`` arguments and return a shell-style exit code."""

    verb = getattr(args, "wiki_command", None)
    if not verb:
        parser = getattr(args, "_parser", None)
        if isinstance(parser, argparse.ArgumentParser):
            parser.print_help()
        return 0
    try:
        if verb == "create":
            result = create_wiki(
                args.slug,
                domain=args.domain,
                author=args.author,
            )
            print(f"Created wiki {result.slug} at {result.path}")
            return 0
        if verb == "list":
            _print_wiki_list(args)
            return 0
        if verb == "show":
            _print_wiki_summary(args)
            return 0
        if verb == "switch":
            marker = switch_wiki(args.slug, profile=args.profile)
            print(f"Current wiki for profile {current_profile(args.profile)} set to {args.slug}")
            print(f"Marker: {marker}")
            return 0
        if verb == "archive":
            result = archive_wiki(args.slug, undo=args.undo, author=args.author)
            state = "unarchived" if args.undo else "archived"
            print(f"{state.capitalize()} wiki {result.slug}")
            return 0
        if verb == "unarchive":
            result = archive_wiki(args.slug, undo=True, author=args.author)
            print(f"Unarchived wiki {result.slug}")
            return 0
        if verb == "purge":
            print(
                "wiki purge is not available in this phase; archive is reversible "
                "and non-destructive",
                file=sys.stderr,
            )
            return 1
    except WikiManagementError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    raise AssertionError(f"unhandled wiki command: {verb}")


def command(args: argparse.Namespace) -> int:
    """Alias expected by Hermes-style command wiring."""

    return wiki_command(args)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the standalone wiki CLI."""

    parser = build_parser()
    parser.set_defaults(_parser=parser)
    parse_argv = list(argv) if argv is not None else sys.argv[1:]
    if parse_argv and parse_argv[0] == "wiki":
        parse_argv = parse_argv[1:]
    try:
        args = parser.parse_args(parse_argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    func = getattr(args, "func", None)
    if callable(func):
        return int(func(args) or 0)
    parser.print_help()
    return 0


def _add_version(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--version",
        action="version",
        version=f"hermes-wiki {__version__}",
    )


def _add_management_subcommands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    create = subparsers.add_parser("create", help="Create a new LLM Wiki")
    create.add_argument("slug", help="Lowercase wiki slug")
    create.add_argument("--domain", help="Human-readable domain/scope")
    create.add_argument("--author", help="Override the acting author for attribution")

    list_parser = subparsers.add_parser("list", help="List visible Wikis")
    list_parser.add_argument(
        "--archived",
        "--all",
        action="store_true",
        help="Include archived Wikis and mark their status",
    )
    list_parser.add_argument("--profile", help="Profile to evaluate visibility for")

    show = subparsers.add_parser("show", help="Show Wiki summary and stats")
    show.add_argument("slug", nargs="?", help="Wiki slug to show")
    show.add_argument("--wiki", dest="wiki", help="Explicit wiki slug (overrides current)")
    show.add_argument("--profile", help="Profile for current-wiki resolution")

    switch = subparsers.add_parser("switch", help="Set the profile-local current Wiki")
    switch.add_argument("slug", help="Wiki slug to make current")
    switch.add_argument("--profile", help="Profile current marker to update")

    archive = subparsers.add_parser("archive", help="Archive a Wiki without deleting files")
    archive.add_argument("slug", help="Wiki slug to archive")
    archive.add_argument("--undo", action="store_true", help="Reverse archive state")
    archive.add_argument("--author", help="Override the acting author for attribution")

    unarchive = subparsers.add_parser("unarchive", help="Unarchive a Wiki")
    unarchive.add_argument("slug", help="Wiki slug to restore")
    unarchive.add_argument("--author", help="Override the acting author for attribution")

    purge = subparsers.add_parser("purge", help="Future destructive removal command")
    purge.add_argument("slug", help="Wiki slug that would be purged in a future phase")


def _print_wiki_list(args: argparse.Namespace) -> None:
    rows = list_visible_wikis(include_archived=args.archived, profile=args.profile)
    if not rows:
        print("No wikis.")
        return
    for row in rows:
        print(_format_summary_line(row, include_status=True))


def _print_wiki_summary(args: argparse.Namespace) -> None:
    target = args.wiki or args.slug
    row = show_wiki(slug=target, profile=args.profile)
    print(f"slug: {row['slug']}")
    print(f"domain: {row.get('domain') or ''}")
    print(f"pages: {row.get('page_count') or 0}")
    print(f"sources: {row.get('source_count') or 0}")
    print(f"health: {float(row.get('health_score') or 0):.2f}")
    print(f"archived: {'yes' if int(row.get('archived') or 0) else 'no'}")
    print(f"path: {row.get('path')}")


def _format_summary_line(row: dict[str, Any], *, include_status: bool) -> str:
    status = " archived" if int(row.get("archived") or 0) else " active"
    return (
        f"{row['slug']}: domain={row.get('domain') or ''} "
        f"pages={row.get('page_count') or 0} "
        f"sources={row.get('source_count') or 0} "
        f"health={float(row.get('health_score') or 0):.2f}"
        f"{status if include_status else ''}"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
