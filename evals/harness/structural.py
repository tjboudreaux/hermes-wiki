"""Compare a generated wiki against an ``expected_structure.yaml`` contract."""

from __future__ import annotations

import json
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from hermes_wiki import db


def evaluate_structure(
    wiki_root: Path,
    expected: dict[str, Any],
    *,
    health_score: float | None = None,
) -> list[str]:
    """Return a list of violations (empty means the wiki matches the contract).

    ``expected`` supports:
      pages: [{id: <glob>, type, must_cite: [globs], must_link: [globs]}]
      forbidden: {duplicate_titles: bool}
      min_health_score: float  (requires ``health_score`` from a lint run)
    """

    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        pages = [
            {
                "id": str(row["id"]),
                "title": str(row["title"]),
                "type": str(row["type"] or ""),
                "sources": json.loads(str(row["sources"] or "[]")),
            }
            for row in conn.execute(
                "SELECT id, title, type, sources FROM pages WHERE COALESCE(archived, 0) = 0"
            ).fetchall()
        ]
        outbound: dict[str, list[str]] = {}
        for row in conn.execute(
            "SELECT source_page_id, target_page_id FROM page_links"
        ).fetchall():
            outbound.setdefault(str(row["source_page_id"]), []).append(
                str(row["target_page_id"])
            )

    violations: list[str] = []
    for spec in expected.get("pages", []):
        violations.extend(_check_page_spec(spec, pages, outbound))

    forbidden = expected.get("forbidden", {})
    if forbidden.get("duplicate_titles"):
        violations.extend(_check_duplicate_titles(pages))

    minimum = expected.get("min_health_score")
    if minimum is not None:
        if health_score is None:
            violations.append("min_health_score set but no health_score provided to evaluator")
        elif health_score < float(minimum):
            violations.append(
                f"health score {health_score} below required minimum {minimum}"
            )
    return violations


def _check_page_spec(
    spec: dict[str, Any],
    pages: list[dict[str, Any]],
    outbound: dict[str, list[str]],
) -> list[str]:
    pattern = str(spec.get("id", ""))
    matches = [page for page in pages if fnmatch(page["id"], pattern)]
    if not matches:
        return [f"no page matches id pattern {pattern!r}"]
    if len(matches) > 1:
        ids = ", ".join(page["id"] for page in matches)
        return [f"id pattern {pattern!r} is ambiguous: {ids}"]

    page = matches[0]
    violations: list[str] = []
    expected_type = spec.get("type")
    if expected_type is not None and page["type"] != expected_type:
        violations.append(
            f"{page['id']}: expected type {expected_type!r}, got {page['type']!r}"
        )
    for cite_pattern in spec.get("must_cite", []):
        if not any(fnmatch(str(source), str(cite_pattern)) for source in page["sources"]):
            violations.append(
                f"{page['id']}: no sources entry matches {cite_pattern!r} "
                f"(sources: {page['sources']})"
            )
    targets = outbound.get(page["id"], [])
    for link_pattern in spec.get("must_link", []):
        if not any(fnmatch(target, str(link_pattern)) for target in targets):
            violations.append(
                f"{page['id']}: no outbound link matches {link_pattern!r} "
                f"(links: {targets})"
            )
    return violations


def _check_duplicate_titles(pages: list[dict[str, Any]]) -> list[str]:
    seen: dict[str, str] = {}
    violations: list[str] = []
    for page in pages:
        key = page["title"].strip().lower()
        if key in seen:
            violations.append(
                f"duplicate title {page['title']!r}: {seen[key]} and {page['id']}"
            )
        else:
            seen[key] = page["id"]
    return violations


__all__ = ["evaluate_structure"]
