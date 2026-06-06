"""FTS5 search helpers for Hermes Wiki projections."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from typing import Any

Row = dict[str, Any]
NOT_FOUND_OR_NOT_VISIBLE = "not found or not visible"

_IDENTIFIER_SEPARATOR_RE = re.compile(r"[_\-/]+")
_ACRONYM_WORD_RE = re.compile(r"([A-Z]{2,})([A-Z][a-z])")
_LOWER_TO_UPPER_WORD_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z][a-z])")
_WHITESPACE_RE = re.compile(r"\s+")
_QUERY_TOKEN_RE = re.compile(r"[\w]+(?:[-_][\w]+)*", flags=re.UNICODE)


def normalize_search_text(*parts: str | Sequence[str] | None) -> str:
    """Return FTS text with original terms plus identifier-normalized variants.

    The search projection intentionally keeps original technical spellings
    (``getCwd``, ``get_cwd``, ``get-cwd``, ``HTTPRequestParser``) and appends
    split forms (``get Cwd``, ``get cwd``, ``HTTP Request Parser``). This makes
    both exact identifier queries and natural-language split queries match while
    avoiding stemming.
    """

    originals: list[str] = []
    normalized: list[str] = []
    for part in parts:
        values = _values(part)
        for value in values:
            stripped = value.strip()
            if not stripped:
                continue
            originals.append(stripped)
            normalized.append(_split_identifier_text(stripped))
    return _WHITESPACE_RE.sub(" ", " ".join([*originals, *normalized])).strip()


def build_fts_query(query: str) -> str | None:
    """Convert raw user input into a safe literal FTS5 MATCH expression.

    FTS5 has its own operator grammar (``NEAR``, column filters, prefix
    operators, parentheses, unary ``-``). Search input is therefore tokenized
    into literal terms and every term is quoted. Empty or punctuation-only input
    returns ``None`` so callers can return an empty result set without invoking
    ``MATCH``.
    """

    terms = _QUERY_TOKEN_RE.findall(query)
    if not terms:
        return None
    return " OR ".join(_quote_fts_term(term) for term in terms)


def search_wiki(
    query: str,
    *,
    wiki: str | None = None,
    limit: int = 5,
) -> list[Row]:
    """Search one resolved visible Wiki with FTS5 BM25 ranking."""

    from hermes_wiki.management import WikiManagementError
    from hermes_wiki.visibility import WikiVisibilityError, require_visible_wiki

    if limit <= 0:
        return []
    fts_query = build_fts_query(query)
    if fts_query is None:
        return []
    try:
        _slug, wiki_root = require_visible_wiki(wiki)
    except WikiVisibilityError as exc:
        raise WikiManagementError(NOT_FOUND_OR_NOT_VISIBLE) from exc

    from hermes_wiki import db
    from hermes_wiki.lint import ensure_projection_current

    ensure_projection_current(wiki_root)
    try:
        with db.connect_wiki(wiki_root / "wiki.db") as conn:
            return db.search_pages(conn, fts_query, limit=limit)
    except sqlite3.DatabaseError as exc:
        raise WikiManagementError(f"search failed: {exc}") from exc


def _values(part: str | Sequence[str] | None) -> list[str]:
    if part is None:
        return []
    if isinstance(part, str):
        return [part]
    return [str(item) for item in part]


def _quote_fts_term(term: str) -> str:
    escaped = term.replace('"', '""')
    return f'"{escaped}"'


def _split_identifier_text(value: str) -> str:
    separated = _IDENTIFIER_SEPARATOR_RE.sub(" ", value)
    separated = _ACRONYM_WORD_RE.sub(r"\1 \2", separated)
    separated = _LOWER_TO_UPPER_WORD_RE.sub(" ", separated)
    return separated


__all__ = ["build_fts_query", "normalize_search_text", "search_wiki"]
