"""Attribution, page-history, and activity-log coverage for M3."""

from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import yaml

from hermes_wiki import db, projection
from hermes_wiki.frontmatter import read_markdown
from hermes_wiki_cli.cli import main


def _run_cli(home: Path, *argv: str, env: dict[str, str] | None = None) -> int:
    merged = {"HERMES_HOME": str(home), "USER": "cli-user", **(env or {})}
    old = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(merged)
        return main(list(argv))
    finally:
        os.environ.clear()
        os.environ.update(old)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _write_page(
    wiki_root: Path,
    page_id: str = "concepts/agent-memory",
    *,
    author: str = "original-author",
    author_kind: str = "human",
    created: str = "2026-06-05T00:00:00Z",
    updated: str = "2026-06-05T00:00:00Z",
    body: str = "# Agent Memory\n\nInitial cited body.",
) -> Path:
    metadata: dict[str, Any] = {
        "id": page_id,
        "title": "Agent Memory",
        "type": "concept",
        "created": created,
        "updated": updated,
        "tags": ["agents"],
        "sources": ["raw/articles/evidence.md"],
        "author": author,
        "author_kind": author_kind,
    }
    path = wiki_root / f"{page_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        + yaml.safe_dump(metadata, sort_keys=False).strip()
        + "\n---\n\n"
        + body.rstrip()
        + "\n",
        encoding="utf-8",
    )
    return path


def test_resolve_actor_maps_sources_and_prefers_config_email(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Author mapping covers human/email, agent, cron, and profile actors."""

    from hermes_wiki.attribution import resolve_actor

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("USER", "fallback-user")
    (tmp_path / "config.yaml").write_text(
        "author:\n  email: configured@example.com\n",
        encoding="utf-8",
    )

    assert resolve_actor(author_kind="human") == ("configured@example.com", "human")
    assert resolve_actor(author="explicit@example.com", author_kind="human") == (
        "explicit@example.com",
        "human",
    )
    assert resolve_actor(author="daily-health-check", author_kind="cron") == (
        "cron:daily-health-check",
        "cron",
    )
    assert resolve_actor(author="ai-tooling", author_kind="profile") == (
        "profile:ai-tooling",
        "profile",
    )

    monkeypatch.setenv("HERMES_MODEL", "claude-opus-4.8")
    assert resolve_actor(author_kind="agent") == ("claude-opus-4.8", "agent")

    (tmp_path / "config.yaml").unlink()
    monkeypatch.delenv("HERMES_MODEL", raising=False)
    assert resolve_actor(author_kind="human") == ("fallback-user", "human")


def test_record_change_updates_frontmatter_projection_and_log(
    tmp_path: Path,
    capsys,
) -> None:
    """record_change keeps current page attribution single-valued and queryable."""

    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    wiki_root = tmp_path / "wikis" / "ai-tooling"
    page_path = _write_page(wiki_root)
    projection.rebuild_projection(
        wiki_root,
        rebuild_reason="manual",
        author="original-author",
        author_kind="human",
    )
    capsys.readouterr()

    from hermes_wiki.attribution import record_change

    record_change(
        wiki_root,
        page_id="concepts/agent-memory",
        action="edit",
        author="claude-opus-4.8",
        author_kind="agent",
        timestamp="2026-06-05T01:00:00Z",
        details={"reason": "unit-test"},
    )

    frontmatter, body = read_markdown(page_path)
    assert frontmatter["author"] == "claude-opus-4.8"
    assert frontmatter["author_kind"] == "agent"
    assert frontmatter["created"] == "2026-06-05T00:00:00Z"
    assert frontmatter["updated"] == "2026-06-05T01:00:00Z"
    assert isinstance(frontmatter["author"], str)
    assert "Page History" not in body

    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        page = db.get_page(conn, "concepts/agent-memory")
    assert page is not None
    assert page["author"] == "claude-opus-4.8"
    assert page["author_kind"] == "agent"

    log_text = (wiki_root / "log.md").read_text(encoding="utf-8")
    expected = (
        "| 2026-06-05T01:00:00Z | edit | concepts/agent-memory | "
        "claude-opus-4.8 | agent |"
    )
    assert expected in log_text


def test_cli_create_page_uses_configured_human_email(
    tmp_path: Path,
    capsys,
) -> None:
    """Human CLI writes prefer configured email over USER and commit with it."""

    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    (tmp_path / "config.yaml").write_text("author: cli@example.com\n", encoding="utf-8")
    capsys.readouterr()

    assert (
        _run_cli(
            tmp_path,
            "create-page",
            "Human Notes",
            "--body",
            "# Human Notes\n\nHuman-authored cited body.",
            "--type",
            "concept",
            "--wiki",
            "ai-tooling",
        )
        == 0
    )

    wiki_root = tmp_path / "wikis" / "ai-tooling"
    frontmatter, _body = read_markdown(wiki_root / "concepts" / "human-notes.md")
    assert frontmatter["author"] == "cli@example.com"
    assert frontmatter["author_kind"] == "human"
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        page = db.get_page(conn, "concepts/human-notes")
    assert page is not None
    assert page["author"] == "cli@example.com"
    assert page["author_kind"] == "human"
    assert "wiki: create-page concepts/human-notes [cli@example.com]" in _git(
        wiki_root,
        "log",
        "-1",
        "--pretty=%s",
    ).stdout


def test_cli_log_filters_combines_and_paginates(
    tmp_path: Path,
    capsys,
) -> None:
    """`hermes-wiki log` is deterministic, chronological, filterable, and paginated."""

    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    wiki_root = tmp_path / "wikis" / "ai-tooling"
    capsys.readouterr()

    from hermes_wiki.attribution import append_log_entry

    append_log_entry(
        wiki_root,
        timestamp="2026-06-05T00:00:01Z",
        action="create-page",
        target="concepts/agent",
        author="claude-opus-4.8",
        author_kind="agent",
        details={"page_id": "concepts/agent"},
    )
    append_log_entry(
        wiki_root,
        timestamp="2026-06-05T00:00:02Z",
        action="monitor",
        target="sources/daily",
        author="cron:daily-health-check",
        author_kind="cron",
        details={"page_id": "sources/daily"},
    )
    append_log_entry(
        wiki_root,
        timestamp="2026-06-05T00:00:03Z",
        action="edit",
        target="concepts/profile",
        author="profile:ai-tooling",
        author_kind="profile",
        details={"page_id": "concepts/profile"},
    )

    assert _run_cli(tmp_path, "log", "--wiki", "ai-tooling") == 0
    first = capsys.readouterr().out
    assert _run_cli(tmp_path, "log", "--wiki", "ai-tooling") == 0
    assert capsys.readouterr().out == first
    assert first.index("claude-opus-4.8") < first.index("cron:daily-health-check")
    assert first.index("cron:daily-health-check") < first.index("profile:ai-tooling")

    assert _run_cli(tmp_path, "log", "--wiki", "ai-tooling", "--author", "claude-opus-4.8") == 0
    by_author = capsys.readouterr().out
    assert "claude-opus-4.8" in by_author
    assert "cron:daily-health-check" not in by_author

    assert _run_cli(tmp_path, "log", "--wiki", "ai-tooling", "--kind", "cron") == 0
    by_kind = capsys.readouterr().out
    assert "cron:daily-health-check" in by_kind
    assert "claude-opus-4.8" not in by_kind

    assert (
        _run_cli(
            tmp_path,
            "log",
            "--wiki",
            "ai-tooling",
            "--author",
            "claude-opus-4.8",
            "--kind",
            "cron",
        )
        == 0
    )
    assert "No log entries." in capsys.readouterr().out

    assert _run_cli(tmp_path, "log", "--wiki", "ai-tooling", "--limit", "2", "--offset", "0") == 0
    window = capsys.readouterr().out
    assert "claude-opus-4.8" in window
    assert "cron:daily-health-check" in window
    assert "profile:ai-tooling" not in window

    assert _run_cli(tmp_path, "log", "--wiki", "ai-tooling", "--kind", "bogus") == 2


def test_agent_edit_reattributes_current_author_but_preserves_create_provenance(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Edits move current frontmatter/pages author while prior authors remain in log/git."""

    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_WIKI", "ai-tooling")

    from hermes_wiki.tools import wiki_create_page

    monkeypatch.setenv("HERMES_MODEL", "agent-alpha")
    first = wiki_create_page(
        title="Field Notes",
        body="# Field Notes\n\nInitial body.",
        type="concept",
        wiki="ai-tooling",
    )
    assert isinstance(first, dict)

    monkeypatch.setenv("HERMES_MODEL", "agent-beta")
    second = wiki_create_page(
        title="Field Notes",
        body="# Field Notes\n\nUpdated body.",
        type="concept",
        wiki="ai-tooling",
    )
    assert isinstance(second, dict)

    wiki_root = tmp_path / "wikis" / "ai-tooling"
    frontmatter, body = read_markdown(wiki_root / "concepts" / "field-notes.md")
    assert frontmatter["author"] == "agent-beta"
    assert frontmatter["author_kind"] == "agent"
    assert isinstance(frontmatter["author"], str)
    assert "agent-alpha" not in body
    assert "Page History" not in body

    with sqlite3.connect(wiki_root / "wiki.db") as conn:
        row = conn.execute(
            "SELECT author, author_kind FROM pages WHERE id='concepts/field-notes'"
        ).fetchone()
    assert row == ("agent-beta", "agent")

    log_text = (wiki_root / "log.md").read_text(encoding="utf-8")
    assert "agent-alpha" in log_text
    assert "agent-beta" in log_text
    subjects = _git(wiki_root, "log", "--format=%s").stdout
    assert "wiki: create-page concepts/field-notes [agent-alpha]" in subjects
    assert "wiki: create-page concepts/field-notes [agent-beta]" in subjects
