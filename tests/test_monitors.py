"""Monitor definition CLI coverage for M4."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
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


def _cron_jobs(home: Path) -> dict[str, dict[str, object]]:
    store = home / "cron" / "wiki_jobs.json"
    if not store.exists():
        return {}
    loaded = json.loads(store.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


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


def test_monitor_setup_requires_confirmation_then_creates_scoped_cron_job(
    tmp_path: Path,
) -> None:
    wiki_root = _create_wiki(tmp_path, "ai-tooling")
    code, _out, err = _run_cli(tmp_path, "monitor", "--wiki", "ai-tooling", "--source", "arxiv")
    assert code == 0, err

    code, out, err = _run_cli(tmp_path, "monitor", "--wiki", "ai-tooling", "--setup")
    assert code == 1
    assert "confirmation required" in err
    assert _cron_jobs(tmp_path) == {}

    code, out, err = _run_cli(
        tmp_path,
        "monitor",
        "--wiki",
        "ai-tooling",
        "--setup",
        "--yes",
    )
    assert code == 0, err
    assert "created: wiki:ai-tooling:weekly-arxiv-sweep" in out

    jobs = _cron_jobs(tmp_path)
    assert set(jobs) == {"wiki:ai-tooling:weekly-arxiv-sweep"}
    job = jobs["wiki:ai-tooling:weekly-arxiv-sweep"]
    assert job["name"] == "wiki:ai-tooling:weekly-arxiv-sweep"
    assert job["env"] == {"HERMES_WIKI": "ai-tooling"}
    assert job["schedule_display"] == "0 9 * * 1"
    assert job["parsed_schedule"] == {
        "kind": "cron",
        "minute": "0",
        "hour": "9",
        "day_of_month": "*",
        "month": "*",
        "day_of_week": "1",
        "display": "0 9 * * 1",
    }
    next_run = datetime.fromisoformat(str(job["next_run_at"]).replace("Z", "+00:00"))
    assert next_run.weekday() == 0
    assert (next_run.hour, next_run.minute) == (9, 0)
    assert job["skills"] == ["wiki-ingest"]
    assert "Sweep arxiv" in str(job["prompt"])
    assert job["origin"] == {
        "source": "hermes-wiki",
        "wiki_slug": "ai-tooling",
        "monitor_name": "weekly-arxiv-sweep",
        "source_kind": "arxiv",
    }
    assert _git(wiki_root, "status", "--porcelain").stdout.strip() == ""


def test_monitor_setup_is_idempotent_updates_and_removes_only_owned_jobs(tmp_path: Path) -> None:
    _create_wiki(tmp_path, "ai-tooling")
    for source in ("arxiv", "rss"):
        code, _out, err = _run_cli(tmp_path, "monitor", "--wiki", "ai-tooling", "--source", source)
        assert code == 0, err

    store = tmp_path / "cron" / "wiki_jobs.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(
        json.dumps(
            {
                "some-other-job": {"name": "some-other-job", "prompt": "foreign"},
                "wiki:other-slug:daily": {
                    "name": "wiki:other-slug:daily",
                    "prompt": "other wiki",
                    "origin": {
                        "source": "hermes-wiki",
                        "wiki_slug": "other-slug",
                        "monitor_name": "daily",
                    },
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    code, out, err = _run_cli(tmp_path, "monitor", "--wiki", "ai-tooling", "--setup", "--yes")
    assert code == 0, err
    first = _cron_jobs(tmp_path)
    assert {"wiki:ai-tooling:weekly-arxiv-sweep", "wiki:ai-tooling:daily-rss-sweep"} <= set(first)

    code, out, err = _run_cli(tmp_path, "monitor", "--wiki", "ai-tooling", "--setup", "--yes")
    assert code == 0, err
    second = _cron_jobs(tmp_path)
    assert second == first
    assert "unchanged: wiki:ai-tooling:daily-rss-sweep" in out

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
    code, out, err = _run_cli(tmp_path, "monitor", "--wiki", "ai-tooling", "--setup", "--yes")
    assert code == 0, err
    updated = _cron_jobs(tmp_path)
    assert updated["wiki:ai-tooling:weekly-arxiv-sweep"]["schedule_display"] == "0 6 * * 1"
    assert updated["wiki:ai-tooling:weekly-arxiv-sweep"]["prompt"] == "Updated arxiv prompt"
    assert "updated: wiki:ai-tooling:weekly-arxiv-sweep" in out
    assert "some-other-job" in updated
    assert updated["some-other-job"] == {"name": "some-other-job", "prompt": "foreign"}
    assert "wiki:other-slug:daily" in updated

    schema = tmp_path / "wikis" / "ai-tooling" / "SCHEMA.md"
    text = schema.read_text(encoding="utf-8")
    start = text.index("<!-- wiki-monitor daily-rss-sweep -->")
    end = text.index("```", text.index("```", start) + 3) + 3
    schema.write_text(text[:start] + text[end:], encoding="utf-8")
    code, out, err = _run_cli(tmp_path, "monitor", "--wiki", "ai-tooling", "--setup", "--yes")
    assert code == 0, err
    removed = _cron_jobs(tmp_path)
    assert "wiki:ai-tooling:daily-rss-sweep" not in removed
    assert "wiki:ai-tooling:weekly-arxiv-sweep" in removed
    assert "some-other-job" in removed
    assert "wiki:other-slug:daily" in removed
    assert "removed: wiki:ai-tooling:daily-rss-sweep" in out


def test_monitor_setup_reports_collisions_and_invalid_schedules_without_clobber(
    tmp_path: Path,
) -> None:
    _create_wiki(tmp_path, "ai-tooling")
    code, _out, err = _run_cli(tmp_path, "monitor", "--wiki", "ai-tooling", "--source", "arxiv")
    assert code == 0, err
    code, _out, err = _run_cli(
        tmp_path,
        "monitor",
        "--wiki",
        "ai-tooling",
        "--source",
        "rss",
        "--schedule",
        "not a cron",
    )
    assert code == 0, err

    store = tmp_path / "cron" / "wiki_jobs.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    foreign = {
        "name": "wiki:ai-tooling:weekly-arxiv-sweep",
        "prompt": "foreign same-name job",
        "origin": {"source": "not-hermes-wiki"},
    }
    store.write_text(
        json.dumps({"wiki:ai-tooling:weekly-arxiv-sweep": foreign}, sort_keys=True),
        encoding="utf-8",
    )

    code, out, err = _run_cli(tmp_path, "monitor", "--wiki", "ai-tooling", "--setup", "--yes")

    assert code == 1
    combined = out + err
    assert "collision: wiki:ai-tooling:weekly-arxiv-sweep" in combined
    assert "invalid schedule for wiki:ai-tooling:daily-rss-sweep" in combined
    jobs = _cron_jobs(tmp_path)
    assert jobs["wiki:ai-tooling:weekly-arxiv-sweep"] == foreign
    assert "wiki:ai-tooling:daily-rss-sweep" not in jobs
