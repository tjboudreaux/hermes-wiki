"""Build disposable wikis from corpus sources via the public CLI surface."""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def wiki_env(home: Path, *, slug: str | None = None, user: str = "eval-harness") -> Iterator[None]:
    """Point the wiki runtime at ``home`` (with a write grant for ``slug``).

    Existing ``HERMES_*`` variables are removed for the duration so evals never
    touch a live Hermes home; everything else (PATH, git config) is preserved.
    """

    saved = os.environ.copy()
    try:
        for key in [key for key in os.environ if key.startswith("HERMES_")]:
            del os.environ[key]
        os.environ["HERMES_HOME"] = str(home)
        os.environ["USER"] = user
        if slug is not None:
            os.environ["HERMES_WIKI"] = slug
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def build_corpus_wiki(
    home: Path,
    *,
    slug: str,
    domain: str,
    sources: Iterable[Path],
) -> Path:
    """Create a wiki under ``home`` and ingest ``sources`` through the real CLI."""

    from hermes_wiki_cli.cli import main

    with wiki_env(home, slug=slug):
        rc = main(["create", slug, "--domain", domain])
        if rc != 0:
            raise RuntimeError(f"wiki create failed for {slug} (exit {rc})")
        for source in sources:
            rc = main(["ingest", str(source), "--wiki", slug])
            if rc != 0:
                raise RuntimeError(f"ingest failed for {source} (exit {rc})")
    return home / "wikis" / slug


__all__ = ["build_corpus_wiki", "wiki_env"]
