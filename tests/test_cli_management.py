"""Integration tests for the wiki management CLI surface."""

from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

from hermes_wiki_cli.cli import main


def _run_cli(tmp_path: Path, *argv: str, env: dict[str, str] | None = None) -> int:
    merged = {"HERMES_HOME": str(tmp_path), "USER": "cli-tester", **(env or {})}
    old = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(merged)
        return main(list(argv))
    finally:
        os.environ.clear()
        os.environ.update(old)


def _registry_rows(home: Path) -> list[sqlite3.Row]:
    conn = sqlite3.connect(home / "wikis" / "wikis.db")
    conn.row_factory = sqlite3.Row
    try:
        return list(conn.execute("SELECT * FROM wikis ORDER BY slug"))
    finally:
        conn.close()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_create_scaffolds_registry_projection_and_attributed_git(
    tmp_path: Path,
    capsys,
) -> None:
    """`wiki create` creates the complete on-disk, DB, projection, and git state."""
    rc = _run_cli(tmp_path, "create", "ai-tooling", "--domain", "AI agents")

    assert rc == 0
    assert "ai-tooling" in capsys.readouterr().out
    wiki_root = tmp_path / "wikis" / "ai-tooling"
    for rel in (
        "raw",
        "raw/inbox",
        "entities",
        "concepts",
        "comparisons",
        "sources",
        "queries",
        "_archive",
        "plugins",
        "plugins/classifiers",
        "plugins/processors",
    ):
        assert (wiki_root / rel).is_dir()
    for name in ("SCHEMA.md", "index.md", "log.md", ".gitignore", "db_versions/manifest.jsonl"):
        assert (wiki_root / name).exists()
        assert (wiki_root / name).stat().st_size > 0

    row = _registry_rows(tmp_path)[0]
    assert dict(row)
    assert row["slug"] == "ai-tooling"
    assert row["path"] == str(wiki_root)
    assert row["archived"] == 0
    assert row["page_count"] == 0
    assert row["source_count"] == 0

    with sqlite3.connect(wiki_root / "wiki.db") as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {
            "pages",
            "pages_fts",
            "ingest_log",
            "sources",
            "taxonomy",
            "trusted_plugins",
            "kanban_refs",
            "projection_versions",
        } <= tables
        assert conn.execute("SELECT count(*) FROM pages").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM sources").fetchone() == (0,)
        assert conn.execute(
            "SELECT rebuild_reason, status FROM projection_versions"
        ).fetchone() == ("initial", "active")

    assert _git(wiki_root, "rev-parse", "--is-inside-work-tree").stdout.strip() == "true"
    assert _git(wiki_root, "log", "-1", "--pretty=%s").stdout.strip() == (
        "wiki: create ai-tooling [cli-tester]"
    )
    assert _git(
        wiki_root,
        "check-ignore",
        "wiki.db",
        "wiki.db.tmp",
        "db_versions/x.db",
    ).returncode == 0
    assert _git(wiki_root, "check-ignore", "db_versions/manifest.jsonl").returncode == 1
    assert _git(wiki_root, "status", "--porcelain").stdout.strip() == ""


def test_create_duplicate_and_invalid_slug_fail_without_clobbering(
    tmp_path: Path,
    capsys,
) -> None:
    """Duplicate and invalid wiki slugs fail cleanly without partial state."""
    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    wiki_root = tmp_path / "wikis" / "ai-tooling"
    first_commit = _git(wiki_root, "rev-parse", "HEAD").stdout.strip()

    assert _run_cli(tmp_path, "create", "ai-tooling") == 1
    assert "already exists" in capsys.readouterr().err
    assert _git(wiki_root, "rev-parse", "HEAD").stdout.strip() == first_commit
    assert len(_registry_rows(tmp_path)) == 1

    assert _run_cli(tmp_path, "create", "Has Spaces/Bad") == 1
    assert "invalid wiki slug" in capsys.readouterr().err
    assert not (tmp_path / "wikis" / "Has Spaces").exists()
    assert len(_registry_rows(tmp_path)) == 1


def test_list_hides_archived_by_default_and_can_show_archived(
    tmp_path: Path,
    capsys,
) -> None:
    """`wiki list` includes metadata, hides archived rows, and has an archive flag."""
    assert _run_cli(tmp_path, "list") == 0
    assert "No wikis" in capsys.readouterr().out
    assert _run_cli(tmp_path, "create", "ai-tooling", "--domain", "AI agents") == 0
    assert _run_cli(tmp_path, "create", "ungodly-economy", "--domain", "Game economy") == 0
    assert _run_cli(tmp_path, "archive", "ungodly-economy") == 0
    capsys.readouterr()

    assert _run_cli(tmp_path, "list") == 0
    out = capsys.readouterr().out
    assert "ai-tooling" in out
    assert "AI agents" in out
    assert "pages=0" in out
    assert "health=1.00" in out
    assert "ungodly-economy" not in out

    assert _run_cli(tmp_path, "list", "--archived") == 0
    out = capsys.readouterr().out
    assert "ungodly-economy" in out
    assert "archived" in out


def test_show_resolves_current_flag_env_and_default_precedence(
    tmp_path: Path,
    capsys,
) -> None:
    """`wiki show` follows the `--wiki`/env > profile current > default cascade."""
    assert _run_cli(tmp_path, "create", "ai-tooling", "--domain", "AI agents") == 0
    assert _run_cli(tmp_path, "create", "ungodly-economy", "--domain", "Game economy") == 0
    (tmp_path / "wikis" / "default").write_text("ungodly-economy\n", encoding="utf-8")

    assert _run_cli(tmp_path, "switch", "ai-tooling", "--profile", "research") == 0
    assert _run_cli(tmp_path, "show", "--profile", "research") == 0
    assert "slug: ai-tooling" in capsys.readouterr().out

    assert _run_cli(tmp_path, "show", "--profile", "research", "--wiki", "ungodly-economy") == 0
    assert "slug: ungodly-economy" in capsys.readouterr().out

    assert _run_cli(
        tmp_path,
        "show",
        "--profile",
        "research",
        env={"HERMES_WIKI": "ungodly-economy"},
    ) == 0
    assert "slug: ungodly-economy" in capsys.readouterr().out

    (tmp_path / "wikis" / "research.current").unlink()
    assert _run_cli(tmp_path, "show", "--profile", "research") == 0
    assert "slug: ungodly-economy" in capsys.readouterr().out

    (tmp_path / "wikis" / "default").unlink()
    assert _run_cli(tmp_path, "show", "--profile", "research") == 1
    assert "No wiki could be resolved" in capsys.readouterr().err


def test_switch_is_profile_local_and_denies_nonexistent_or_archived(
    tmp_path: Path,
    capsys,
) -> None:
    """`wiki switch` writes only the selected profile's current marker."""
    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    assert _run_cli(tmp_path, "create", "ungodly-economy") == 0
    (tmp_path / "wikis" / "default").write_text("ungodly-economy\n", encoding="utf-8")

    assert _run_cli(tmp_path, "switch", "ai-tooling", "--profile", "research") == 0
    assert (tmp_path / "wikis" / "research.current").read_text(encoding="utf-8") == (
        "ai-tooling\n"
    )
    assert not (tmp_path / "wikis" / "coding.current").exists()
    assert (tmp_path / "wikis" / "default").read_text(encoding="utf-8") == "ungodly-economy\n"

    assert _run_cli(tmp_path, "show", "--profile", "coding") == 0
    assert "slug: ungodly-economy" in capsys.readouterr().out

    assert _run_cli(tmp_path, "switch", "nope", "--profile", "research") == 1
    assert "not found or not visible" in capsys.readouterr().err
    assert (tmp_path / "wikis" / "research.current").read_text(encoding="utf-8") == (
        "ai-tooling\n"
    )

    assert _run_cli(tmp_path, "archive", "ungodly-economy") == 0
    assert _run_cli(tmp_path, "switch", "ungodly-economy", "--profile", "research") == 1
    assert "not found or not visible" in capsys.readouterr().err
    assert (tmp_path / "wikis" / "research.current").read_text(encoding="utf-8") == (
        "ai-tooling\n"
    )


def test_archive_is_reversible_non_destructive_and_purge_refuses(
    tmp_path: Path,
    capsys,
) -> None:
    """Archive marks registry state, preserves files, commits, and can be undone."""
    assert _run_cli(tmp_path, "create", "ungodly-economy") == 0
    wiki_root = tmp_path / "wikis" / "ungodly-economy"
    before_schema = (wiki_root / "SCHEMA.md").read_text(encoding="utf-8")

    assert _run_cli(tmp_path, "archive", "ungodly-economy") == 0
    row = _registry_rows(tmp_path)[0]
    assert row["archived"] == 1
    assert row["archived_at"]
    assert (wiki_root / "SCHEMA.md").read_text(encoding="utf-8") == before_schema
    assert "wiki: archive ungodly-economy [cli-tester]" in _git(
        wiki_root, "log", "-1", "--pretty=%s"
    ).stdout

    assert _run_cli(tmp_path, "show", "ungodly-economy") == 1
    assert capsys.readouterr().err.strip() == "not found or not visible"

    assert _run_cli(tmp_path, "archive", "ungodly-economy", "--undo") == 0
    row = _registry_rows(tmp_path)[0]
    assert row["archived"] == 0
    assert row["archived_at"] is None
    assert _run_cli(tmp_path, "list") == 0
    assert "ungodly-economy" in capsys.readouterr().out

    assert _run_cli(tmp_path, "purge", "ungodly-economy") == 1
    assert "not available" in capsys.readouterr().err
    assert wiki_root.exists()


def test_list_and_show_honor_private_and_profile_visibility_config(
    tmp_path: Path,
    capsys,
) -> None:
    """Private, whitelisted, and blacklisted wikis follow visibility config."""
    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    assert _run_cli(tmp_path, "create", "private-lab") == 0
    schema = tmp_path / "wikis" / "private-lab" / "SCHEMA.md"
    schema.write_text(
        schema.read_text(encoding="utf-8").replace("private: false", "private: true"),
        encoding="utf-8",
    )
    capsys.readouterr()

    assert _run_cli(tmp_path, "list") == 0
    out = capsys.readouterr().out
    assert "ai-tooling" in out
    assert "private-lab" not in out

    assert _run_cli(tmp_path, "show", "private-lab") == 1
    assert capsys.readouterr().err.strip() == "not found or not visible"

    (tmp_path / "config.yaml").write_text(
        "wiki:\n  whitelist: [private-lab]\n",
        encoding="utf-8",
    )
    assert _run_cli(tmp_path, "list") == 0
    out = capsys.readouterr().out
    assert "private-lab" in out
    assert "ai-tooling" not in out
    assert _run_cli(tmp_path, "show", "private-lab") == 0
    assert "slug: private-lab" in capsys.readouterr().out

    (tmp_path / "config.yaml").write_text(
        "wiki:\n  blacklist: [ai-tooling]\n",
        encoding="utf-8",
    )
    assert _run_cli(tmp_path, "list") == 0
    out = capsys.readouterr().out
    assert "ai-tooling" not in out
    assert "private-lab" not in out

    assert _run_cli(tmp_path, "list", "--profile", "../outside") == 1
    assert "invalid profile name" in capsys.readouterr().err


def test_explicit_bogus_resolution_does_not_fall_through_to_default(
    tmp_path: Path,
    capsys,
) -> None:
    """Explicit `--wiki`/`HERMES_WIKI` misses deny instead of using fallback."""
    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    (tmp_path / "wikis" / "default").write_text("ai-tooling\n", encoding="utf-8")

    assert _run_cli(tmp_path, "show", "--wiki", "nope") == 1
    err = capsys.readouterr().err
    assert "not found or not visible" in err
    assert "ai-tooling" not in err

    assert _run_cli(tmp_path, "show", env={"HERMES_WIKI": "nope"}) == 1
    err = capsys.readouterr().err
    assert "not found or not visible" in err
    assert "ai-tooling" not in err
