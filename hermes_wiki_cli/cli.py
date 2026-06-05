"""Minimal standalone CLI for the initial Hermes Wiki scaffold."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from hermes_wiki import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the standalone scaffold parser."""
    parser = argparse.ArgumentParser(
        prog="hermes-wiki",
        description="Hermes Wiki Plugin scaffold",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"hermes-wiki {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the standalone scaffold CLI."""
    parser = build_parser()
    try:
        parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)

    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
