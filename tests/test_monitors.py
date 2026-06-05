"""Monitor definition CLI coverage for M4."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from email.message import Message
from io import StringIO
from pathlib import Path
from typing import Any

import yaml

from hermes_wiki import pipeline
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


class _FakeUrlResponse:
    def __init__(self, content: bytes) -> None:
        self._content = content

    def __enter__(self) -> _FakeUrlResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int = -1) -> bytes:
        return self._content


def _read_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    _, metadata_text, body = text.split("---", 2)
    metadata = yaml.safe_load(metadata_text) or {}
    assert isinstance(metadata, dict)
    return metadata, body


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


def test_monitor_sweep_url_dedups_drifts_and_attributes_cron(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A monitor sweep feeds URL ingest, sha dedup, drift rows, lint, and cron attribution."""
    wiki_root = _create_wiki(tmp_path, "ai-tooling")
    code, _out, err = _run_cli(tmp_path, "monitor", "--wiki", "ai-tooling", "--source", "arxiv")
    assert code == 0, err
    code, _out, err = _run_cli(tmp_path, "monitor", "--wiki", "ai-tooling", "--setup", "--yes")
    assert code == 0, err
    assert "wiki:ai-tooling:weekly-arxiv-sweep" in _cron_jobs(tmp_path)
    url = "https://example.test/weekly-hermes-drift.md"
    contents = [
        "\n".join(
            [
                "# Weekly Hermes Drift",
                "",
                "Clipped article about monitor sweeps and Source Snapshots.",
            ]
        ).encode(),
        "\n".join(
            [
                "# Weekly Hermes Drift",
                "",
                "Clipped article about monitor sweeps, Source Snapshots, and drift changes.",
            ]
        ).encode(),
    ]
    current = {"content": contents[0]}

    def fake_urlopen(*_args: object, **_kwargs: object) -> _FakeUrlResponse:
        return _FakeUrlResponse(current["content"])

    monkeypatch.setattr(pipeline.urllib.request, "urlopen", fake_urlopen)

    code, out, err = _run_cli(
        tmp_path,
        "monitor",
        "--wiki",
        "ai-tooling",
        "--name",
        "weekly-arxiv-sweep",
        "--sweep-url",
        url,
    )
    assert code == 0, err
    assert "Sweep ingested" in out
    with sqlite3.connect(wiki_root / "wiki.db") as conn:
        conn.row_factory = sqlite3.Row
        first_source = conn.execute("SELECT * FROM sources WHERE source_url=?", (url,)).fetchone()
        first_log = conn.execute("SELECT * FROM ingest_log ORDER BY id DESC LIMIT 1").fetchone()
    assert first_source is not None
    assert first_source["version"] == 1
    assert first_source["is_latest"] == 1
    assert first_log["author"] == "cron:wiki:ai-tooling:weekly-arxiv-sweep"
    assert first_log["author_kind"] == "cron"
    first_raw = wiki_root / str(first_source["id"])
    first_raw_bytes = first_raw.read_bytes()
    commits_after_first = int(_git(wiki_root, "rev-list", "--count", "HEAD").stdout.strip())

    code, out, err = _run_cli(
        tmp_path,
        "monitor",
        "--wiki",
        "ai-tooling",
        "--name",
        "weekly-arxiv-sweep",
        "--sweep-url",
        url,
    )
    assert code == 0, err
    assert "no change" in out
    with sqlite3.connect(wiki_root / "wiki.db") as conn:
        assert conn.execute("SELECT count(*) FROM sources WHERE source_url=?", (url,)).fetchone()[
            0
        ] == 1
    assert int(_git(wiki_root, "rev-list", "--count", "HEAD").stdout.strip()) == commits_after_first

    current["content"] = contents[1]
    code, out, err = _run_cli(
        tmp_path,
        "monitor",
        "--wiki",
        "ai-tooling",
        "--name",
        "weekly-arxiv-sweep",
        "--sweep-url",
        url,
    )
    assert code == 0, err
    assert "drift_detected=1" in out
    with sqlite3.connect(wiki_root / "wiki.db") as conn:
        conn.row_factory = sqlite3.Row
        rows = list(
            conn.execute(
                "SELECT * FROM sources WHERE source_url=? ORDER BY version",
                (url,),
            )
        )
        latest_log = conn.execute(
            "SELECT * FROM ingest_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert [(row["version"], row["is_latest"]) for row in rows] == [(1, 0), (2, 1)]
    assert rows[1]["previous_source_id"] == rows[0]["id"]
    assert rows[0]["sha256"] != rows[1]["sha256"]
    assert first_raw.read_bytes() == first_raw_bytes
    assert (wiki_root / str(rows[1]["id"])).is_file()
    assert latest_log["drift_detected"] == 1
    assert latest_log["sha256"] == rows[1]["sha256"]
    assert latest_log["author"] == "cron:wiki:ai-tooling:weekly-arxiv-sweep"
    assert latest_log["author_kind"] == "cron"
    updated_page = wiki_root / "entities" / "weekly-hermes-drift.md"
    metadata, body = _read_frontmatter(updated_page)
    assert rows[1]["id"] in metadata["sources"]
    assert metadata["author"] == "cron:wiki:ai-tooling:weekly-arxiv-sweep"
    assert metadata["author_kind"] == "cron"
    assert "drift changes" in body
    assert "cron:wiki:ai-tooling:weekly-arxiv-sweep" in _git(
        wiki_root, "log", "-1", "--pretty=%s"
    ).stdout

    code, lint_out, err = _run_cli(tmp_path, "lint", "--wiki", "ai-tooling")
    assert code == 0, err
    report = json.loads(lint_out)
    assert any(finding["check"] == "external_source_drift" for finding in report["findings"])
    assert not [finding for finding in report["findings"] if finding["check"] == "broken_link"]


def test_monitor_sweep_unreachable_url_has_no_side_effects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """An unreachable URL during a sweep fails cleanly without snapshot, DB, or git writes."""
    wiki_root = _create_wiki(tmp_path, "ai-tooling")
    code, _out, err = _run_cli(tmp_path, "monitor", "--wiki", "ai-tooling", "--source", "rss")
    assert code == 0, err
    commits_before = _git(wiki_root, "rev-list", "--count", "HEAD").stdout.strip()

    def fail_urlopen(*_args: object, **_kwargs: object) -> object:
        raise pipeline.urllib.error.HTTPError(
            "https://example.invalid/unreachable",
            503,
            "Service Unavailable",
            hdrs=Message(),
            fp=None,
        )

    monkeypatch.setattr(pipeline.urllib.request, "urlopen", fail_urlopen)

    code, out, err = _run_cli(
        tmp_path,
        "monitor",
        "--wiki",
        "ai-tooling",
        "--name",
        "daily-rss-sweep",
        "--sweep-url",
        "https://example.invalid/unreachable",
    )

    assert code == 1
    assert out == ""
    assert "failed to fetch URL" in err
    assert _git(wiki_root, "rev-list", "--count", "HEAD").stdout.strip() == commits_before
    with sqlite3.connect(wiki_root / "wiki.db") as conn:
        assert conn.execute("SELECT count(*) FROM sources").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM ingest_log").fetchone() == (0,)
    assert not list((wiki_root / "raw" / "articles").glob("*"))
    assert _git(wiki_root, "status", "--porcelain").stdout.strip() == ""
