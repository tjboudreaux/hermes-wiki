"""CLI black-box tests for projection rebuild and lint repair behavior."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from hermes_wiki import db, projection
from hermes_wiki_cli.cli import main


def _run_cli(home: Path, *argv: str, env: dict[str, str] | None = None) -> int:
    merged = {"HERMES_HOME": str(home), "USER": "lint-tester", **(env or {})}
    old = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(merged)
        return main(list(argv))
    finally:
        os.environ.clear()
        os.environ.update(old)


def _run_cli_subprocess(home: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HERMES_HOME": str(home), "USER": "lint-tester"}
    return subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from hermes_wiki_cli.cli import main; "
                f"raise SystemExit(main({list(argv)!r}))"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _write_page(
    wiki_root: Path,
    rel: str = "concepts/agent-memory.md",
    *,
    title: str = "Agent Memory",
    body: str = "Agent memory systems retain durable context.",
    include_type: bool = True,
) -> Path:
    path = wiki_root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    type_line = ["type: concept"] if include_type else []
    path.write_text(
        "\n".join(
            [
                "---",
                "id: concepts/agent-memory",
                f"title: {title}",
                *type_line,
                "created: 2026-06-05T00:00:00Z",
                "updated: 2026-06-05T00:00:00Z",
                "tags: [agents, memory]",
                "sources: [raw/articles/memory.md]",
                "author: lint-tester",
                "author_kind: human",
                "---",
                "",
                f"# {title}",
                body,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _read_json_stdout(capsys) -> dict[str, Any]:
    out = capsys.readouterr().out
    return cast(dict[str, Any], json.loads(out))


def _findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], report["findings"])


def _rebuild(report: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], report["rebuild"])


def test_lint_rebuilds_deleted_db_from_markdown_and_preserves_raw(
    tmp_path: Path,
    capsys,
) -> None:
    """Deleting wiki.db then running lint recreates pages from Markdown files."""
    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    wiki_root = tmp_path / "wikis" / "ai-tooling"
    _write_page(wiki_root)
    raw = wiki_root / "raw" / "articles" / "memory.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("immutable raw bytes", encoding="utf-8")
    raw_hash = projection.sha256_file(raw)
    assert _run_cli(tmp_path, "lint", "--wiki", "ai-tooling") == 0
    capsys.readouterr()

    (wiki_root / "wiki.db").unlink()
    before_manifest_lines = (wiki_root / "db_versions" / "manifest.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()

    assert _run_cli(tmp_path, "lint", "--wiki", "ai-tooling") == 0
    report = _read_json_stdout(capsys)

    assert any(f["code"] == "projection_missing" for f in _findings(report))
    assert (wiki_root / "wiki.db").exists()
    assert not (wiki_root / "wiki.db.tmp").exists()
    assert projection.sha256_file(raw) == raw_hash
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        page = db.get_page(conn, "concepts/agent-memory")
        assert page is not None
        assert page["title"] == "Agent Memory"
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        active_count = conn.execute(
            "SELECT COUNT(*) FROM projection_versions WHERE status='active'"
        ).fetchone()[0]
        assert active_count == 1
    after_manifest_lines = (wiki_root / "db_versions" / "manifest.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(after_manifest_lines) == len(before_manifest_lines) + 1
    assert _git(wiki_root, "status", "--porcelain").stdout.strip() == ""


def test_lint_rebuilds_corrupt_db_instead_of_crashing(tmp_path: Path, capsys) -> None:
    """A corrupt wiki.db is replaced by a valid projection during lint."""
    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    capsys.readouterr()
    wiki_root = tmp_path / "wikis" / "ai-tooling"
    _write_page(wiki_root)
    (wiki_root / "wiki.db").write_bytes(b"not sqlite")

    assert _run_cli(tmp_path, "lint", "--wiki", "ai-tooling") == 0
    report = _read_json_stdout(capsys)

    assert any(f["code"] == "projection_corrupt" for f in _findings(report))
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        assert db.get_page(conn, "concepts/agent-memory") is not None
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_lint_reports_file_db_conflict_and_files_win(tmp_path: Path, capsys) -> None:
    """If Markdown and DB disagree, lint reports the conflict and repairs from files."""
    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    wiki_root = tmp_path / "wikis" / "ai-tooling"
    page_path = _write_page(wiki_root, title="Agent Memory")
    assert _run_cli(tmp_path, "lint", "--wiki", "ai-tooling") == 0
    capsys.readouterr()
    page_path.write_text(
        page_path.read_text(encoding="utf-8").replace("title: Agent Memory", "title: File Wins"),
        encoding="utf-8",
    )

    assert _run_cli(tmp_path, "lint", "--wiki", "ai-tooling") == 0
    report = _read_json_stdout(capsys)

    mismatch = [f for f in _findings(report) if f["code"] == "projection_mismatch"]
    assert mismatch
    assert mismatch[0]["field"] == "title"
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        page = db.get_page(conn, "concepts/agent-memory")
        assert page is not None
        assert page["title"] == "File Wins"
        active = conn.execute(
            """
            SELECT source_tree_sha256, db_sha256
            FROM projection_versions
            WHERE status='active'
            """
        ).fetchone()
        assert active[0] == projection.source_tree_sha256(wiki_root)
        assert active[1] == projection.projection_db_sha256(wiki_root / "wiki.db")


def test_lint_failure_retains_prior_db_and_records_failed_version(
    tmp_path: Path,
    capsys,
) -> None:
    """Invalid Markdown does not swap in a broken DB and leaves one active version."""
    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    wiki_root = tmp_path / "wikis" / "ai-tooling"
    _write_page(wiki_root)
    assert _run_cli(tmp_path, "lint", "--wiki", "ai-tooling") == 0
    capsys.readouterr()
    _write_page(wiki_root, include_type=False)

    assert _run_cli(tmp_path, "lint", "--wiki", "ai-tooling") == 1
    report = _read_json_stdout(capsys)

    assert _rebuild(report)["status"] == "failed"
    assert any(f["code"] == "projection_rebuild_failed" for f in _findings(report))
    assert not (wiki_root / "wiki.db.tmp").exists()
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        page = db.get_page(conn, "concepts/agent-memory")
        assert page is not None
        assert page["title"] == "Agent Memory"
        active_count = conn.execute(
            "SELECT COUNT(*) FROM projection_versions WHERE status='active'"
        ).fetchone()[0]
        failed_count = conn.execute(
            "SELECT COUNT(*) FROM projection_versions WHERE status='failed'"
        ).fetchone()[0]
        assert active_count == 1
        assert failed_count == 1


def test_concurrent_lint_rebuilds_leave_single_active_projection(
    tmp_path: Path,
) -> None:
    """Advisory locking serializes concurrent rebuilds of the same wiki."""
    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    wiki_root = tmp_path / "wikis" / "ai-tooling"
    _write_page(wiki_root)
    (wiki_root / "wiki.db").unlink()

    first = subprocess.Popen(
        _subprocess_args("lint", "--wiki", "ai-tooling"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "HERMES_HOME": str(tmp_path), "USER": "lint-tester"},
    )
    second = subprocess.Popen(
        _subprocess_args("lint", "--wiki", "ai-tooling"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "HERMES_HOME": str(tmp_path), "USER": "lint-tester"},
    )
    first_out, first_err = first.communicate(timeout=30)
    second_out, second_err = second.communicate(timeout=30)

    assert first.returncode == 0, first_err or first_out
    assert second.returncode == 0, second_err or second_out
    assert not (wiki_root / "wiki.db.tmp").exists()
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        active_count = conn.execute(
            "SELECT COUNT(*) FROM projection_versions WHERE status='active'"
        ).fetchone()[0]
        assert active_count == 1


def test_archived_show_denied_without_disclosure(tmp_path: Path, capsys) -> None:
    """show on an archived wiki returns only the non-disclosing denial string."""
    assert _run_cli(tmp_path, "create", "ungodly-economy", "--domain", "Game economy") == 0
    assert _run_cli(tmp_path, "archive", "ungodly-economy") == 0
    capsys.readouterr()

    assert _run_cli(tmp_path, "show", "ungodly-economy") == 1

    captured = capsys.readouterr()
    assert captured.err.strip() == "not found or not visible"
    assert "Game economy" not in captured.out
    assert "archived" not in captured.err


def test_manifest_rows_reference_existing_snapshots_and_versions(
    tmp_path: Path,
    capsys,
) -> None:
    """Every manifest row points at a snapshot file and projection_versions row."""
    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    wiki_root = tmp_path / "wikis" / "ai-tooling"
    _write_page(wiki_root)
    assert _run_cli(tmp_path, "lint", "--wiki", "ai-tooling") == 0
    capsys.readouterr()

    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        version_ids = {
            row["version_id"]
            for row in conn.execute("SELECT version_id FROM projection_versions").fetchall()
        }
    rows = [
        json.loads(line)
        for line in (wiki_root / "db_versions" / "manifest.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert rows
    for row in rows:
        assert row["version_id"] in version_ids
        assert row["snapshot_path"]
        assert (wiki_root / row["snapshot_path"]).exists()


def _subprocess_args(*argv: str) -> list[str]:
    return [
        sys.executable,
        "-c",
        f"from hermes_wiki_cli.cli import main; raise SystemExit(main({list(argv)!r}))",
    ]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
