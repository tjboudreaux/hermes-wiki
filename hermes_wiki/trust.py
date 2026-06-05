"""Trusted custom classifier/processor metadata helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hermes_wiki import db, git_ops, projection
from hermes_wiki.management import (
    NOT_FOUND_OR_NOT_VISIBLE,
    WikiManagementError,
    ensure_wiki_mutable,
    resolved_author,
)


class TrustError(RuntimeError):
    """Raised for clean user-facing trust/list failures."""


def list_plugins(*, wiki: str | None = None) -> list[dict[str, Any]]:
    """List custom plugin files and whether their trust hash is active."""

    try:
        resolved = ensure_wiki_mutable(slug=wiki)
    except WikiManagementError as exc:
        raise TrustError(NOT_FOUND_OR_NOT_VISIBLE) from exc
    trusted = _trusted_map(resolved.path)
    rows: list[dict[str, Any]] = []
    for kind, dirname in (("classifier", "classifiers"), ("processor", "processors")):
        plugin_dir = resolved.path / "plugins" / dirname
        for path in sorted(plugin_dir.glob("*.py")):
            name = path.stem
            key = (kind, name)
            current_sha = projection.sha256_file(path)
            trust_row = trusted.get(key)
            if trust_row is None:
                status = "untrusted"
                shown_sha = current_sha
            elif str(trust_row.get("sha256")) == current_sha:
                status = "trusted"
                shown_sha = current_sha
            else:
                status = "disabled hash-mismatch"
                shown_sha = current_sha
            rows.append(
                {
                    "kind": kind,
                    "name": name,
                    "path": path.relative_to(resolved.path).as_posix(),
                    "sha256": shown_sha,
                    "status": status,
                }
            )
    return rows


def trust_plugin(
    *,
    kind: str,
    name: str,
    wiki: str | None = None,
    author: str | None = None,
) -> dict[str, Any]:
    """Trust one custom plugin by recording path+sha in SCHEMA.md and wiki.db."""

    clean_kind = _validate_kind(kind)
    clean_name = _validate_name(name)
    acting_author = resolved_author(author)
    try:
        resolved = ensure_wiki_mutable(slug=wiki)
    except WikiManagementError as exc:
        raise TrustError(NOT_FOUND_OR_NOT_VISIBLE) from exc
    dirname = "classifiers" if clean_kind == "classifier" else "processors"
    plugin_rel = Path("plugins") / dirname / f"{clean_name}.py"
    plugin_path = resolved.path / plugin_rel
    if not plugin_path.is_file():
        raise TrustError(f"plugin file does not exist: {plugin_rel.as_posix()}")
    sha = projection.sha256_file(plugin_path)
    trusted_at = _utc_now()
    _append_schema_trust_record(
        resolved.path,
        kind=clean_kind,
        name=clean_name,
        path=plugin_rel.as_posix(),
        sha256=sha,
        trusted_at=trusted_at,
        author=acting_author,
    )
    with db.connect_wiki(resolved.path / "wiki.db") as conn:
        row = db.upsert_trusted_plugin(
            conn,
            name=clean_name,
            kind=clean_kind,
            path=plugin_rel.as_posix(),
            sha256=sha,
            trusted_at=trusted_at,
            author=acting_author,
            author_kind="human",
        )
        conn.commit()
        db_hash = projection.projection_db_sha256(resolved.path / "wiki.db")
        conn.execute(
            "UPDATE projection_versions SET db_sha256 = ? WHERE status = 'active'",
            (db_hash,),
        )
        conn.commit()
    git_ops.commit_change(
        resolved.path,
        action="trust",
        what=f"{clean_kind} {clean_name}",
        author=acting_author,
    )
    return row


def _trusted_map(wiki_root: Path) -> dict[tuple[str, str], dict[str, Any]]:
    wiki_db = wiki_root / "wiki.db"
    if not wiki_db.exists():
        return {}
    with db.connect_wiki(wiki_db) as conn:
        return {
            (str(row["kind"]), str(row["name"])): row
            for row in db.list_trusted_plugins(conn)
        }


def _append_schema_trust_record(
    wiki_root: Path,
    *,
    kind: str,
    name: str,
    path: str,
    sha256: str,
    trusted_at: str,
    author: str,
) -> None:
    schema = wiki_root / "SCHEMA.md"
    with schema.open("a", encoding="utf-8") as handle:
        handle.write(
            "\n".join(
                [
                    "",
                    f"<!-- trusted-plugin {kind}:{name} -->",
                    "```yaml",
                    "trusted_plugin:",
                    f"  name: {name}",
                    f"  kind: {kind}",
                    f"  path: {path}",
                    f"  sha256: {sha256}",
                    f"  trusted_at: {trusted_at}",
                    f"  author: {author}",
                    "  author_kind: human",
                    "```",
                    "",
                ]
            )
        )


def _validate_kind(kind: str) -> str:
    if kind not in {"classifier", "processor"}:
        raise TrustError("plugin kind must be classifier or processor")
    return kind


def _validate_name(name: str) -> str:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise TrustError("invalid plugin name")
    if not name.replace("_", "-").replace("-", "").isalnum():
        raise TrustError("invalid plugin name")
    return name


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = ["TrustError", "list_plugins", "trust_plugin"]
