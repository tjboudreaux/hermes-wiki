"""Monitor definition CLI coverage for M4."""

from __future__ import annotations

import os
import subprocess
import sys
from io import StringIO
from pathlib import Path

from hermes_wiki_cli.cli import main


def _run_cli(
    home: Path,
    *argv: str,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    merged = {"HERMES_HOME": str(home), "USER": "monitor-tester", **(env or {})}
    old_env = os.environ.copy()
    old_out, old_err = sys.stdout, sys.stderr
    out = StringIO()
    err = StringIO()
    try:
        os.environ.clear()
        os.environ.update(merged)
        sys.stdout = out
        sys.stderr = err
        code = main(list(argv))
        return code, out.getvalue(), err.getvalue()
    finally:
        sys.stdout = old_out
        sys.stderr = old_err
        os.environ.clear()
        os.environ.update(old_env)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _create_wiki(home: Path, slug: str) -> Path:
    code, _out, err = _run_cli(home, "create", slug, "--domain", f"{slug} domain")
    assert code == 0, err
    return home / "wikis" / slug


def test_monitor_source_persists_portable_definition_without_cron_job(tmp_path: Path) -> None:
    """A bare monitor definition edits SCHEMA.md and does not schedule cron."""
    wiki_root = _create_wiki(tmp_path, "ai-tooling")
    cron_store = tmp_path / "cron" / "wiki_jobs.json"

    code, out, err = _run_cli(tmp_path, "monitor", "--wiki", "ai-tooling", "--source", "arxiv")

    assert code == 0, err
    assert "Defined monitor weekly-arxiv-sweep source=arxiv wiki=ai-tooling" in out
    schema = (wiki_root / "SCHEMA.md").read_text(encoding="utf-8")
    assert "<!-- wiki-monitor weekly-arxiv-sweep -->" in schema
    assert "monitors:" in schema
    assert "name: weekly-arxiv-sweep" in schema
    assert "source: arxiv" in schema
    assert 'schedule: "0 9 * * 1"' in schema
    assert "skills:" in schema
    assert "- wiki-ingest" in schema
    assert "HERMES_WIKI: ai-tooling" in schema
    assert "Sweep arxiv" in schema
    assert not cron_store.exists()
    assert "wiki: monitor weekly-arxiv-sweep [monitor-tester]" in _git(
        wiki_root, "log", "-1", "--pretty=%s"
    ).stdout
    assert _git(wiki_root, "status", "--porcelain").stdout.strip() == ""


def test_monitor_supported_sources_are_distinct_and_update_in_place(tmp_path: Path) -> None:
    """Supported source kinds get distinct definitions; reusing a name updates it."""
    wiki_root = _create_wiki(tmp_path, "ai-tooling")

    for source in ("arxiv", "rss", "x"):
        code, _out, err = _run_cli(tmp_path, "monitor", "--wiki", "ai-tooling", "--source", source)
        assert code == 0, err

    code, _out, err = _run_cli(
        tmp_path,
        "monitor",
        "--wiki",
        "ai-tooling",
        "--source",
        "arxiv",
        "--schedule",
        "0 6 * * 1",
        "--prompt",
        "Updated arxiv prompt",
    )
    assert code == 0, err

    schema = (wiki_root / "SCHEMA.md").read_text(encoding="utf-8")
    assert "source: arxiv" in schema
    assert "source: rss" in schema
    assert "source: x" in schema
    assert schema.count("<!-- wiki-monitor weekly-arxiv-sweep -->") == 1
    assert schema.count("name: weekly-arxiv-sweep") == 1
    assert 'schedule: "0 6 * * 1"' in schema
    assert "Updated arxiv prompt" in schema


def test_monitor_resolution_cascade_targets_only_resolved_wiki(tmp_path: Path) -> None:
    """Monitor definitions use explicit/env/current/default wiki resolution."""
    ai_root = _create_wiki(tmp_path, "ai-tooling")
    economy_root = _create_wiki(tmp_path, "ungodly-economy")

    code, _out, err = _run_cli(tmp_path, "switch", "ai-tooling", "--profile", "research")
    assert code == 0, err
    code, _out, err = _run_cli(tmp_path, "monitor", "--profile", "research", "--source", "rss")
    assert code == 0, err
    assert "<!-- wiki-monitor daily-rss-sweep -->" in (
        ai_root / "SCHEMA.md"
    ).read_text(encoding="utf-8")
    assert "<!-- wiki-monitor daily-rss-sweep -->" not in (
        economy_root / "SCHEMA.md"
    ).read_text(encoding="utf-8")

    code, _out, err = _run_cli(
        tmp_path,
        "monitor",
        "--source",
        "x",
        env={"HERMES_WIKI": "ungodly-economy"},
    )
    assert code == 0, err
    assert "<!-- wiki-monitor daily-x-sweep -->" in (
        economy_root / "SCHEMA.md"
    ).read_text(encoding="utf-8")
    assert "<!-- wiki-monitor daily-x-sweep -->" not in (
        ai_root / "SCHEMA.md"
    ).read_text(encoding="utf-8")
