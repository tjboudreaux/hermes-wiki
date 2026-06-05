"""Tests for per-wiki git repository operations."""

from __future__ import annotations

import subprocess
from pathlib import Path

from hermes_wiki import git_ops


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_initialize_wiki_repo_creates_per_wiki_repo_and_gitignore(tmp_path: Path) -> None:
    """A wiki repo is initialized under <home>/wikis/<slug>/ with projection ignores."""
    home = tmp_path / "home"

    wiki_root = git_ops.initialize_wiki_repo(home, "ai-tooling")

    assert wiki_root == home / "wikis" / "ai-tooling"
    assert (wiki_root / ".git").is_dir()
    assert _git(wiki_root, "rev-parse", "--show-toplevel") == str(wiki_root)

    gitignore = (wiki_root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "wiki.db" in gitignore
    assert "wiki.db.tmp" in gitignore
    assert "db_versions/*.db" in gitignore
    assert "!db_versions/manifest.jsonl" in gitignore


def test_commit_change_commits_durable_files_with_attributed_message(tmp_path: Path) -> None:
    """Commit helper stages durable wiki files, tracks manifest, and attributes the commit."""
    wiki_root = git_ops.initialize_wiki_repo(tmp_path / "home", "ai-tooling")
    (wiki_root / "index.md").write_text("# Index\n", encoding="utf-8")
    (wiki_root / "wiki.db").write_bytes(b"projection")
    (wiki_root / "wiki.db.tmp").write_bytes(b"tmp projection")
    (wiki_root / "db_versions").mkdir()
    (wiki_root / "db_versions" / "wiki-20260605.db").write_bytes(b"old projection")
    (wiki_root / "db_versions" / "manifest.jsonl").write_text(
        '{"version_id":"v1"}\n',
        encoding="utf-8",
    )

    result = git_ops.commit_change(
        wiki_root,
        action="ingest",
        what="vaswani.pdf",
        author="profile:ai-tooling",
    )

    assert result.committed is True
    assert result.message == "wiki: ingest vaswani.pdf [profile:ai-tooling]"
    assert _git(wiki_root, "log", "-1", "--pretty=%s") == result.message

    tracked = set(_git(wiki_root, "ls-tree", "-r", "--name-only", "HEAD").splitlines())
    assert ".gitignore" in tracked
    assert "index.md" in tracked
    assert "db_versions/manifest.jsonl" in tracked
    assert "wiki.db" not in tracked
    assert "wiki.db.tmp" not in tracked
    assert "db_versions/wiki-20260605.db" not in tracked


def test_commit_change_noops_when_only_projection_binaries_changed(tmp_path: Path) -> None:
    """Projection binaries are ignored and never produce a git commit by themselves."""
    wiki_root = git_ops.initialize_wiki_repo(tmp_path / "home", "ai-tooling")
    (wiki_root / "index.md").write_text("# Index\n", encoding="utf-8")
    first = git_ops.commit_change(
        wiki_root,
        action="create",
        what="index",
        author="human:test",
    )
    assert first.committed is True

    (wiki_root / "wiki.db").write_bytes(b"projection")
    (wiki_root / "wiki.db.tmp").write_bytes(b"tmp")
    (wiki_root / "db_versions").mkdir(exist_ok=True)
    (wiki_root / "db_versions" / "wiki-20260605.db").write_bytes(b"old")

    second = git_ops.commit_change(
        wiki_root,
        action="rebuild",
        what="projection",
        author="agent:test",
    )

    assert second.committed is False
    assert second.commit_id is None
    assert _git(wiki_root, "rev-list", "--count", "HEAD") == "1"
    assert _git(wiki_root, "status", "--short") == ""
