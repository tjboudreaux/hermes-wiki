"""Trusted custom classifier/processor metadata helpers."""

from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path
from typing import Any

import yaml

from hermes_wiki import db, git_ops, projection
from hermes_wiki.attribution import append_log_entry
from hermes_wiki.classifiers import BUILTIN_CLASSIFIERS
from hermes_wiki.management import (
    NOT_FOUND_OR_NOT_VISIBLE,
    WikiManagementError,
    ensure_wiki_mutable,
    resolved_author,
)
from hermes_wiki.visibility import WikiVisibilityError, require_visible_wiki


class TrustError(RuntimeError):
    """Raised for clean user-facing trust/list failures."""


_TRUST_BLOCK_RE = re.compile(
    r"\n?<!-- trusted-plugin (?P<kind>classifier|processor):(?P<name>[A-Za-z0-9_-]+) -->"
    r"\n```yaml\n(?P<body>.*?)\n```\n?",
    re.DOTALL,
)


def list_plugins(*, wiki: str | None = None) -> list[dict[str, Any]]:
    """List built-in plugins and custom plugin files with trust state."""

    try:
        _slug, wiki_root = require_visible_wiki(wiki)
    except WikiVisibilityError as exc:
        raise TrustError(NOT_FOUND_OR_NOT_VISIBLE) from exc
    trusted = {
        (record["kind"], record["name"]): record
        for record in read_schema_trust_records(wiki_root)
    }
    rows: list[dict[str, Any]] = [
        {
            "kind": "classifier",
            "name": classifier.name,
            "path": "<built-in>",
            "sha256": "",
            "status": "built-in",
        }
        for classifier in BUILTIN_CLASSIFIERS
    ]
    rows.append(
        {
            "kind": "processor",
            "name": "default",
            "path": "<built-in>",
            "sha256": "",
            "status": "built-in",
        }
    )
    for kind, dirname in (("classifier", "classifiers"), ("processor", "processors")):
        plugin_dir = wiki_root / "plugins" / dirname
        seen_names: set[str] = set()
        for path in sorted(plugin_dir.glob("*.py")):
            name = path.stem
            seen_names.add(name)
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
                    "path": path.relative_to(wiki_root).as_posix(),
                    "sha256": shown_sha,
                    "status": status,
                }
            )
        for key_kind, key_name in sorted(trusted):
            if key_kind != kind or key_name in seen_names:
                continue
            trust_row = trusted[(key_kind, key_name)]
            rows.append(
                {
                    "kind": kind,
                    "name": key_name,
                    "path": trust_row["path"],
                    "sha256": trust_row["sha256"],
                    "status": "disabled missing-file",
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
    _replace_schema_trust_record(
        resolved.path,
        kind=clean_kind,
        name=clean_name,
        path=plugin_rel.as_posix(),
        sha256=sha,
        trusted_at=trusted_at,
        author=acting_author,
    )
    _append_trust_log(
        resolved.path,
        action="trust",
        kind=clean_kind,
        name=clean_name,
        author=acting_author,
        trusted_at=trusted_at,
    )
    rebuild = projection.rebuild_projection(
        resolved.path,
        rebuild_reason="manual",
        author=acting_author,
        author_kind="human",
    )
    if rebuild.status != "active":
        raise TrustError(f"projection rebuild failed: {rebuild.notes}")
    with db.connect_wiki(resolved.path / "wiki.db") as conn:
        row = conn.execute(
            """
            SELECT * FROM trusted_plugins
            WHERE name = ? AND kind = ?
            """,
            (clean_name, clean_kind),
        ).fetchone()
        result = dict(row) if row is not None else {}
    if not result:
        raise TrustError("trusted plugin did not project into wiki.db")
    git_ops.commit_change(
        resolved.path,
        action="trust",
        what=f"{clean_kind} {clean_name}",
        author=acting_author,
    )
    return result


def untrust_plugin(
    *,
    name: str,
    wiki: str | None = None,
    kind: str | None = None,
    author: str | None = None,
) -> dict[str, Any]:
    """Revoke trust by removing canonical SCHEMA.md records and rebuilding projection."""

    clean_name = _validate_name(name)
    clean_kind = None if kind is None else _validate_kind(kind)
    acting_author = resolved_author(author)
    try:
        resolved = ensure_wiki_mutable(slug=wiki)
    except WikiManagementError as exc:
        raise TrustError(NOT_FOUND_OR_NOT_VISIBLE) from exc

    removed = _remove_schema_trust_records(resolved.path, name=clean_name, kind=clean_kind)
    if not removed:
        raise TrustError(f"plugin is not trusted: {clean_name}")
    now = _utc_now()
    removed_names = ", ".join(f"{record['kind']} {record['name']}" for record in removed)
    _append_trust_log(
        resolved.path,
        action="untrust",
        kind=clean_kind or "plugin",
        name=clean_name,
        author=acting_author,
        trusted_at=now,
    )
    rebuild = projection.rebuild_projection(
        resolved.path,
        rebuild_reason="manual",
        author=acting_author,
        author_kind="human",
    )
    if rebuild.status != "active":
        raise TrustError(f"projection rebuild failed: {rebuild.notes}")
    git_ops.commit_change(
        resolved.path,
        action="untrust",
        what=clean_name,
        author=acting_author,
    )
    return {"name": clean_name, "removed": removed, "message": removed_names}


def read_schema_trust_records(wiki_root: Path | str) -> list[dict[str, Any]]:
    """Parse canonical trusted-plugin records from ``SCHEMA.md`` marker blocks."""

    schema = Path(wiki_root) / "SCHEMA.md"
    if not schema.exists():
        return []
    text = schema.read_text(encoding="utf-8")
    records: list[dict[str, Any]] = []
    for match in _TRUST_BLOCK_RE.finditer(text):
        marker_kind = match.group("kind")
        marker_name = match.group("name")
        try:
            loaded = yaml.safe_load(match.group("body")) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(loaded, dict):
            continue
        record = loaded.get("trusted_plugin")
        if not isinstance(record, dict):
            continue
        normalized = {
            "name": str(record.get("name") or marker_name),
            "kind": str(record.get("kind") or marker_kind),
            "path": str(record.get("path") or ""),
            "sha256": str(record.get("sha256") or ""),
            "trusted_at": str(record.get("trusted_at") or ""),
            "author": str(record.get("author") or ""),
            "author_kind": str(record.get("author_kind") or "human"),
        }
        if normalized["kind"] != marker_kind or normalized["name"] != marker_name:
            continue
        if not normalized["path"] or not normalized["sha256"] or not normalized["trusted_at"]:
            continue
        records.append(normalized)
    records.sort(key=lambda row: (str(row["trusted_at"]), str(row["kind"]), str(row["name"])))
    return records


def project_schema_trust_records(wiki_root: Path | str, conn: Any) -> None:
    """Replace ``trusted_plugins`` projection rows with canonical SCHEMA.md records."""

    conn.execute("DELETE FROM trusted_plugins")
    for record in read_schema_trust_records(wiki_root):
        db.upsert_trusted_plugin(
            conn,
            name=str(record["name"]),
            kind=str(record["kind"]),
            path=str(record["path"]),
            sha256=str(record["sha256"]),
            trusted_at=str(record["trusted_at"]),
            author=str(record["author"] or "") or None,
            author_kind=str(record["author_kind"] or "") or None,
        )


def _trusted_map(wiki_root: Path) -> dict[tuple[str, str], dict[str, Any]]:
    wiki_db = wiki_root / "wiki.db"
    if not wiki_db.exists():
        return {}
    with db.connect_wiki(wiki_db) as conn:
        return {
            (str(row["kind"]), str(row["name"])): row
            for row in db.list_trusted_plugins(conn)
        }


def _replace_schema_trust_record(
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
    text = schema.read_text(encoding="utf-8")
    text, _removed = _remove_trust_blocks_from_text(text, name=name, kind=kind)
    # The author is free text (CLI --author / $USER); quote it as a JSON string
    # (valid YAML double-quoted scalar) so values containing ": " or other YAML
    # indicators survive the yaml.safe_load round-trip.
    block = textwrap.dedent(
        f"""

        <!-- trusted-plugin {kind}:{name} -->
        ```yaml
        trusted_plugin:
          name: {name}
          kind: {kind}
          path: {path}
          sha256: {sha256}
          trusted_at: {trusted_at}
          author: {json.dumps(author)}
          author_kind: human
        ```
        """
    )
    schema.write_text(text.rstrip() + block + "\n", encoding="utf-8")


def _remove_schema_trust_records(
    wiki_root: Path,
    *,
    name: str,
    kind: str | None,
) -> list[dict[str, Any]]:
    schema = wiki_root / "SCHEMA.md"
    text = schema.read_text(encoding="utf-8")
    updated, removed = _remove_trust_blocks_from_text(text, name=name, kind=kind)
    if removed:
        schema.write_text(updated.rstrip() + "\n", encoding="utf-8")
    return removed


def _remove_trust_blocks_from_text(
    text: str,
    *,
    name: str,
    kind: str | None,
) -> tuple[str, list[dict[str, Any]]]:
    removed: list[dict[str, Any]] = []

    def replace(match: re.Match[str]) -> str:
        block_kind = match.group("kind")
        block_name = match.group("name")
        if block_name != name or (kind is not None and block_kind != kind):
            return match.group(0)
        removed.append({"kind": block_kind, "name": block_name})
        return "\n"

    return _TRUST_BLOCK_RE.sub(replace, text), removed


def _append_trust_log(
    wiki_root: Path,
    *,
    action: str,
    kind: str,
    name: str,
    author: str,
    trusted_at: str,
) -> None:
    append_log_entry(
        wiki_root,
        timestamp=trusted_at,
        action=action,
        target=f"{kind} {name}",
        author=author,
        author_kind="human",
        details={"kind": kind, "name": name},
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


__all__ = [
    "TrustError",
    "list_plugins",
    "project_schema_trust_records",
    "read_schema_trust_records",
    "trust_plugin",
    "untrust_plugin",
]
