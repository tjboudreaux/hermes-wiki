"""CLI surface for Hermes Wiki management commands."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Any

from hermes_wiki import __version__
from hermes_wiki.attribution import list_log_entries, resolve_actor
from hermes_wiki.management import (
    WikiManagementError,
    archive_wiki,
    create_wiki,
    current_profile,
    ensure_wiki_mutable,
    list_visible_wikis,
    show_wiki,
    switch_wiki,
)
from hermes_wiki.navigation import WikiNavigationError, list_wiki_pages, open_wiki_page
from hermes_wiki.pipeline import IngestError, ingest_inbox, ingest_source, list_inbox
from hermes_wiki.search import search_wiki
from hermes_wiki.tools import _create_or_update_page


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
        if verb == "lint":
            from hermes_wiki.lint import lint_wiki

            report = lint_wiki(slug=args.wiki, profile=args.profile, author=args.author)
            print(report.to_json())
            return 1 if report.status == "failed" else 0
        if verb == "ingest":
            if args.inbox and args.source:
                print("ingest accepts either <path|url> or --inbox, not both", file=sys.stderr)
                return 1
            if args.inbox:
                results = ingest_inbox(wiki=args.wiki, author=args.author)
                if not results:
                    print("Inbox empty.")
                    return 0
                for result in results:
                    name = result.message or result.source_id.rsplit("/", 1)[-1]
                    if result.skipped and result.classified_as == "oversized":
                        print(f"Skipped {name} status=oversized")
                        continue
                    if result.skipped and result.classified_as == "unknown":
                        print(f"Retained {name} class=unknown")
                        continue
                    print(
                        f"Ingested {name} class={result.classified_as} "
                        f"source={result.source_id}"
                    )
                return 0
            if not args.source:
                print("ingest requires <path|url> or explicit --inbox", file=sys.stderr)
                return 1
            result = ingest_source(args.source, wiki=args.wiki, author=args.author)
            if result.skipped:
                print(f"no change: {result.source_id}")
                return 0
            print(
                f"Ingested {args.source} class={result.classified_as} "
                f"source={result.source_id}"
            )
            print("pages_created: " + ", ".join(result.pages_created))
            if result.pages_updated:
                print("pages_updated: " + ", ".join(result.pages_updated))
            return 0
        if verb == "search":
            rows = search_wiki(args.query, wiki=args.wiki, limit=args.limit)
            if not rows:
                print("No results.")
                return 0
            for row in rows:
                context = row.get("context") or row.get("snippet") or ""
                print(f"{row['id']}: {row['title']} — {context}")
            return 0
        if verb == "open":
            print(open_wiki_page(args.page_id, wiki=args.wiki), end="")
            return 0
        if verb == "list-pages":
            rows = list_wiki_pages(wiki=args.wiki, page_type=args.page_type, tag=args.tag)
            if not rows:
                print("No pages.")
                return 0
            for row in rows:
                tags = row.get("tags") or []
                tag_text = ",".join(str(tag) for tag in tags)
                print(f"{row['id']}: {row['title']} type={row['type']} tags={tag_text}")
            return 0
        if verb == "create-page":
            actor, actor_kind = resolve_actor(author=args.author, author_kind=args.author_kind)
            resolved = ensure_wiki_mutable(slug=args.wiki, profile=args.profile)
            result = _create_or_update_page(
                resolved.path,
                wiki=resolved.slug,
                title=args.title,
                body=args.body,
                page_type=args.page_type,
                tags=args.tags or (),
                sources=args.sources or (),
                author=actor,
                author_kind=actor_kind,
            )
            print(
                f"{result['id']} author={result['author']} "
                f"author_kind={result['author_kind']}"
            )
            return 0
        if verb == "inbox":
            rows = list_inbox(wiki=args.wiki)
            if not rows:
                print("Inbox empty.")
                return 0
            for row in rows:
                print(f"{row['name']}: {row['status']} ({row['path']})")
            return 0
        if verb == "log":
            _print_activity_log(args)
            return 0
        if verb == "plugins":
            from hermes_wiki.trust import TrustError, list_plugins, trust_plugin, untrust_plugin

            try:
                if args.plugins_command == "list":
                    rows = list_plugins(wiki=args.wiki)
                    if not rows:
                        print("No custom plugins.")
                        return 0
                    for row in rows:
                        print(
                            f"{row['kind']} {row['name']}: {row['status']} "
                            f"sha256={row.get('sha256') or ''}"
                        )
                    return 0
                if args.plugins_command == "trust":
                    result = trust_plugin(
                        kind=args.kind,
                        name=args.name,
                        wiki=args.wiki,
                        author=args.author,
                    )
                    print(
                        f"Trusted {result['kind']} {result['name']} "
                        f"sha256={result['sha256']}"
                    )
                    return 0
                if args.plugins_command == "untrust":
                    result = untrust_plugin(
                        name=args.name,
                        kind=args.kind,
                        wiki=args.wiki,
                        author=args.author,
                    )
                    print(f"Untrusted {result['message']}")
                    return 0
            except TrustError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            print("plugins requires a subcommand", file=sys.stderr)
            return 1
        if verb == "purge":
            print(
                "wiki purge is not available in this phase; archive is reversible "
                "and non-destructive",
                file=sys.stderr,
            )
            return 1
    except (WikiManagementError, IngestError, WikiNavigationError, ValueError) as exc:
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

    lint = subparsers.add_parser("lint", help="Lint and repair a Wiki projection")
    lint.add_argument("--wiki", dest="wiki", help="Explicit wiki slug (overrides current)")
    lint.add_argument("--profile", help="Profile for current-wiki resolution")
    lint.add_argument("--author", help="Override the acting author for attribution")

    ingest = subparsers.add_parser("ingest", help="Ingest one source into a Wiki")
    ingest.add_argument("source", nargs="?", help="Local path or http(s) URL")
    ingest.add_argument("--wiki", dest="wiki", help="Explicit wiki slug")
    ingest.add_argument("--author", help="Override the acting author for attribution")
    ingest.add_argument("--inbox", action="store_true", help="Explicitly batch the inbox")

    search = subparsers.add_parser("search", help="Search Wiki Pages")
    search.add_argument("query", help="FTS query")
    search.add_argument("--wiki", dest="wiki", help="Explicit wiki slug")
    search.add_argument("--limit", type=int, default=5)

    open_page = subparsers.add_parser("open", help="Print a Wiki Page's Markdown content")
    open_page.add_argument("page_id", help="Wiki Page id, e.g. concepts/attention-mechanism")
    open_page.add_argument("--wiki", dest="wiki", help="Explicit wiki slug")

    list_pages = subparsers.add_parser("list-pages", help="List Wiki Pages")
    list_pages.add_argument("--wiki", dest="wiki", help="Explicit wiki slug")
    list_pages.add_argument("--type", dest="page_type", help="Filter by page type")
    list_pages.add_argument("--tag", dest="tag", help="Filter by tag")

    create_page = subparsers.add_parser("create-page", help="Create or update a Wiki Page")
    create_page.add_argument("title", help="Page title")
    create_page.add_argument("--body", required=True, help="Markdown body for the page")
    create_page.add_argument("--type", dest="page_type", default="concept", help="Wiki Page type")
    create_page.add_argument("--tag", dest="tags", action="append", help="Tag to add")
    create_page.add_argument("--source", dest="sources", action="append", help="Source id/path")
    create_page.add_argument("--wiki", dest="wiki", help="Explicit wiki slug")
    create_page.add_argument("--profile", help="Profile for current-wiki resolution")
    create_page.add_argument("--author", help="Override the acting author for attribution")
    create_page.add_argument(
        "--author-kind",
        choices=("agent", "profile", "human", "cron"),
        help="Override inferred author kind",
    )

    inbox = subparsers.add_parser("inbox", help="List unprocessed inbox files")
    inbox.add_argument("--wiki", dest="wiki", help="Explicit wiki slug")

    log = subparsers.add_parser("log", help="List attributed Wiki actions")
    log.add_argument("--wiki", dest="wiki", help="Explicit wiki slug")
    log.add_argument("--profile", help="Profile for current-wiki resolution")
    log.add_argument("--author", help="Filter to one exact author")
    log.add_argument(
        "--kind",
        choices=("agent", "profile", "human", "cron"),
        help="Filter author kind",
    )
    log.add_argument("--page", dest="page_id", help="Filter to one page id")
    log.add_argument("--limit", type=int, default=50, help="Maximum rows to print")
    log.add_argument("--offset", type=int, default=0, help="Rows to skip before printing")

    plugins = subparsers.add_parser("plugins", help="List and trust custom plugins")
    plugin_subparsers = plugins.add_subparsers(dest="plugins_command")
    plugin_list = plugin_subparsers.add_parser("list", help="List custom plugins")
    plugin_list.add_argument("--wiki", dest="wiki", help="Explicit wiki slug")
    plugin_trust = plugin_subparsers.add_parser("trust", help="Trust a custom plugin file")
    plugin_trust.add_argument("kind", choices=("classifier", "processor"))
    plugin_trust.add_argument("name")
    plugin_trust.add_argument("--wiki", dest="wiki", help="Explicit wiki slug")
    plugin_trust.add_argument("--author", help="Override the acting author for attribution")
    plugin_untrust = plugin_subparsers.add_parser("untrust", help="Revoke custom plugin trust")
    plugin_untrust.add_argument("name")
    plugin_untrust.add_argument("--kind", choices=("classifier", "processor"))
    plugin_untrust.add_argument("--wiki", dest="wiki", help="Explicit wiki slug")
    plugin_untrust.add_argument("--author", help="Override the acting author for attribution")

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


def _print_activity_log(args: argparse.Namespace) -> None:
    row = show_wiki(slug=args.wiki, profile=args.profile)
    entries = list_log_entries(
        row["path"],
        author=args.author,
        author_kind=args.kind,
        page_id=args.page_id,
        limit=args.limit,
        offset=args.offset,
    )
    if not entries:
        print("No log entries.")
        return
    for entry in entries:
        print(
            f"{entry.timestamp} {entry.author_kind} {entry.author} "
            f"{entry.action} {entry.target} {entry.details}".rstrip()
        )


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
