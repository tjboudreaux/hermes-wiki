from __future__ import annotations

import json
import os
import sys
from io import StringIO
from pathlib import Path
from typing import Any

from hermes_wiki import db, projection
from hermes_wiki.frontmatter import read_markdown
from hermes_wiki_cli.cli import main


def _run_cli(home: Path, *argv: str) -> tuple[int, str, str]:
    merged = {"HERMES_HOME": str(home), "USER": "kanban-tester"}
    old = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(merged)
        out = StringIO()
        err = StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        try:
            sys.stdout, sys.stderr = out, err
            code = main(list(argv))
        finally:
            sys.stdout, sys.stderr = old_out, old_err
        return code, out.getvalue(), err.getvalue()
    finally:
        os.environ.clear()
        os.environ.update(old)


def _write_tasks(home: Path, tasks: dict[str, dict[str, Any]]) -> None:
    (home / "kanban_tasks.json").write_text(json.dumps(tasks, sort_keys=True), encoding="utf-8")


def _create_wiki_with_page(home: Path) -> Path:
    code, _out, err = _run_cli(home, "create", "ai-tooling", "--domain", "AI tooling")
    assert code == 0, err
    code, _out, err = _run_cli(
        home,
        "create-page",
        "Agent Memory",
        "--body",
        "# Agent Memory\n\nDurable notes.",
        "--type",
        "concept",
        "--wiki",
        "ai-tooling",
    )
    assert code == 0, err
    return home / "wikis" / "ai-tooling"


def _write_article(path: Path, task_id: str, *, marker: str = "source text") -> None:
    path.write_text(
        "\n".join(
            [
                "# Task Linked Article",
                "",
                f"This article references {task_id} in {marker}.",
                "Hermes Wiki should only auto-link when enabled.",
            ]
        ),
        encoding="utf-8",
    )


def test_cli_link_refs_unlink_validate_readonly_and_idempotent(tmp_path: Path) -> None:
    wiki_root = _create_wiki_with_page(tmp_path)
    _write_tasks(tmp_path, {"KB-123": {"id": "KB-123", "title": "Ship kanban linkage"}})
    kanban_db = tmp_path / "kanban.db"
    kanban_db.write_bytes(b"kanban-db-sentinel")
    before = kanban_db.read_bytes()

    code, out, err = _run_cli(
        tmp_path, "link", "concepts/agent-memory", "KB-DOES-NOT-EXIST", "--wiki", "ai-tooling"
    )
    assert code == 1
    assert "not found" in err
    assert kanban_db.read_bytes() == before

    code, out, err = _run_cli(
        tmp_path, "link", "concepts/agent-memory", "KB-123", "--wiki", "ai-tooling"
    )
    assert code == 0, err
    assert "KB-123" in out
    assert "Ship kanban linkage" in out
    assert kanban_db.read_bytes() == before

    frontmatter, _body = read_markdown(wiki_root / "concepts/agent-memory.md")
    matching_refs = [
        ref
        for ref in frontmatter["kanban_refs"]
        if ref["task_id"] == "KB-123" and ref["direction"] == "page->task"
    ]
    assert len(matching_refs) == 1
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM kanban_refs "
                "WHERE page_id='concepts/agent-memory' AND task_id='KB-123'"
            ).fetchone()[0]
            == 1
        )

    code, _out, err = _run_cli(
        tmp_path, "link", "concepts/agent-memory", "KB-123", "--wiki", "ai-tooling"
    )
    assert code == 0, err
    frontmatter, _body = read_markdown(wiki_root / "concepts/agent-memory.md")
    assert [
        ref
        for ref in frontmatter["kanban_refs"]
        if ref["task_id"] == "KB-123" and ref["direction"] == "page->task"
    ] == matching_refs

    code, out, err = _run_cli(tmp_path, "refs", "concepts/agent-memory", "--wiki", "ai-tooling")
    assert code == 0, err
    assert "KB-123" in out
    assert "Ship kanban linkage" in out

    code, out, err = _run_cli(tmp_path, "refs", "--task", "KB-123", "--wiki", "ai-tooling")
    assert code == 0, err
    assert "concepts/agent-memory" in out

    code, out, err = _run_cli(
        tmp_path, "unlink", "concepts/agent-memory", "KB-123", "--wiki", "ai-tooling"
    )
    assert code == 0, err
    assert "unlinked" in out
    assert kanban_db.read_bytes() == before
    frontmatter, _body = read_markdown(wiki_root / "concepts/agent-memory.md")
    assert not [
        ref for ref in frontmatter.get("kanban_refs", []) if ref.get("task_id") == "KB-123"
    ]
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM kanban_refs WHERE task_id='KB-123'").fetchone()[0]
            == 0
        )

    code, out, err = _run_cli(
        tmp_path, "unlink", "concepts/agent-memory", "KB-123", "--wiki", "ai-tooling"
    )
    assert code == 0, err
    assert "not linked" in out
    assert kanban_db.read_bytes() == before


def test_kanban_refs_survive_projection_rebuild_and_source_pages_link(tmp_path: Path) -> None:
    wiki_root = _create_wiki_with_page(tmp_path)
    _write_tasks(tmp_path, {"KB-123": {"id": "KB-123", "title": "Rebuild-safe task"}})
    code, _out, err = _run_cli(
        tmp_path,
        "create-page",
        "Vaswani Source",
        "--body",
        "# Vaswani Source\n\nSource page body.",
        "--type",
        "source",
        "--wiki",
        "ai-tooling",
    )
    assert code == 0, err
    code, _out, err = _run_cli(
        tmp_path, "link", "sources/vaswani-source", "KB-123", "--wiki", "ai-tooling"
    )
    assert code == 0, err
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        before = db.list_kanban_refs(conn)

    (wiki_root / "wiki.db").unlink()
    result = projection.rebuild_projection(
        wiki_root,
        rebuild_reason="manual",
        author="kanban-tester",
        author_kind="human",
    )
    assert result.status == "active"
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        after = db.list_kanban_refs(conn)
    assert after == before
    assert any(ref["page_id"] == "sources/vaswani-source" for ref in after)


def test_ingest_auto_link_requires_schema_opt_in(tmp_path: Path) -> None:
    wiki_root = _create_wiki_with_page(tmp_path)
    _write_tasks(tmp_path, {"KB-123": {"id": "KB-123", "title": "Auto link task"}})
    source = tmp_path / "article.md"
    _write_article(source, "KB-123")

    code, _out, err = _run_cli(tmp_path, "ingest", str(source), "--wiki", "ai-tooling")
    assert code == 0, err
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        assert db.list_kanban_refs(conn) == []

    schema = wiki_root / "SCHEMA.md"
    schema.write_text(
        schema.read_text(encoding="utf-8").replace(
            "auto_link_kanban: false",
            "auto_link_kanban: true",
        ),
        encoding="utf-8",
    )
    source2 = tmp_path / "article2.md"
    _write_article(source2, "KB-123", marker="enabled source text")
    code, _out, err = _run_cli(tmp_path, "ingest", str(source2), "--wiki", "ai-tooling")
    assert code == 0, err
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        refs = db.list_kanban_refs(conn, task_id="KB-123")
    assert refs
    assert all(ref["direction"] == "page->task" for ref in refs)


def test_lint_reports_kanban_projection_drift_and_dangling_refs(tmp_path: Path, capsys) -> None:
    wiki_root = _create_wiki_with_page(tmp_path)
    _write_tasks(tmp_path, {"KB-123": {"id": "KB-123", "title": "Dangling candidate"}})
    code, _out, err = _run_cli(
        tmp_path, "link", "concepts/agent-memory", "KB-123", "--wiki", "ai-tooling"
    )
    assert code == 0, err
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        conn.execute("DELETE FROM kanban_refs WHERE task_id='KB-123'")
        conn.commit()

    code, out, err = _run_cli(tmp_path, "lint", "--wiki", "ai-tooling")
    assert code == 0
    assert err == ""
    report = json.loads(out)
    assert any(finding["check"] == "kanban_projection_drift" for finding in report["findings"])

    projection.rebuild_projection(
        wiki_root,
        rebuild_reason="manual",
        author="kanban-tester",
        author_kind="human",
    )
    _write_tasks(tmp_path, {})
    code, out, err = _run_cli(tmp_path, "lint", "--wiki", "ai-tooling")
    assert code == 0
    assert err == ""
    report = json.loads(out)
    assert any(finding["check"] == "dangling_kanban_ref" for finding in report["findings"])
