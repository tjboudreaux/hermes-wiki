"""Health/lint coverage for SPEC.md §11 checks."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from hermes_wiki import db, projection
from hermes_wiki_cli.cli import main


def _run_cli(home: Path, *argv: str) -> int:
    merged = {"HERMES_HOME": str(home), "USER": "lint-tester"}
    old = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(merged)
        return main(list(argv))
    finally:
        os.environ.clear()
        os.environ.update(old)


def _lint(home: Path, capsys, *argv: str) -> tuple[int, dict[str, Any]]:
    code = _run_cli(home, "lint", *argv)
    captured = capsys.readouterr()
    assert captured.err == ""
    return code, json.loads(captured.out)


def _write_page(
    wiki_root: Path,
    page_id: str,
    *,
    title: str | None = None,
    page_type: str = "concept",
    tags: list[str] | None = None,
    sources: list[str] | None = None,
    body: str = "This page summarizes a factual claim from cited evidence.",
    extra: dict[str, Any] | None = None,
    omit: set[str] | None = None,
) -> Path:
    metadata: dict[str, Any] = {
        "id": page_id,
        "title": title or page_id.rsplit("/", 1)[-1].replace("-", " ").title(),
        "type": page_type,
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-06-01T00:00:00Z",
        "tags": tags or ["agents"],
        "sources": sources if sources is not None else ["raw/articles/evidence.md"],
        "author": "lint-tester",
        "author_kind": "human",
    }
    metadata.update(extra or {})
    for field in omit or set():
        metadata.pop(field, None)
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


def _rewrite_index(wiki_root: Path, page_ids: list[str]) -> None:
    lines = ["# Index", ""]
    lines.extend(f"- [{page_id}]({page_id}.md) — `{page_id}`" for page_id in page_ids)
    (wiki_root / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _seed_projection(wiki_root: Path, *, taxonomy: list[str] | None = None) -> None:
    projection.rebuild_projection(
        wiki_root,
        rebuild_reason="manual",
        author="lint-tester",
        author_kind="human",
    )
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        for tag in taxonomy or ["agents", "memory", "research"]:
            db.add_taxonomy_tag(conn, tag=tag)
        conn.commit()


def _checks(report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for finding in report["findings"]:
        grouped.setdefault(finding["check"], []).append(finding)
        assert finding["severity"] in {"high", "medium", "low"}
        assert finding["check"] == finding["code"]
        assert any(key in finding for key in ("page", "path", "file", "wiki"))
    return grouped


def test_clean_wiki_lint_outputs_stable_json_and_updates_registry(
    tmp_path: Path,
    capsys,
) -> None:
    """A fresh clean wiki has no high findings and records health metadata."""

    assert _run_cli(tmp_path, "create", "ai-tooling", "--domain", "AI tooling") == 0
    capsys.readouterr()

    code, report = _lint(tmp_path, capsys, "--wiki", "ai-tooling")

    assert code == 0
    assert report["wiki"] == "ai-tooling"
    assert report["status"] == "clean"
    assert report["findings"] == []
    assert report["summary"] == {"total": 0, "high": 0, "medium": 0, "low": 0}
    assert report["health_score"] > 0.9
    with db.connect_registry(tmp_path / "wikis" / "wikis.db") as conn:
        row = db.get_wiki(conn, "ai-tooling")
    assert row is not None
    assert row["last_lint"]
    assert float(row["health_score"]) == report["health_score"]


def test_lint_reports_page_level_checks_with_correct_severities(
    tmp_path: Path,
    capsys,
) -> None:
    """Page checks include orphan, links, citations, dates, index, tags, and source pages."""

    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    wiki_root = tmp_path / "wikis" / "ai-tooling"
    _write_page(wiki_root, "concepts/orphan", body="A cited isolated page.")
    _write_page(
        wiki_root,
        "concepts/broken",
        body="A cited page with [missing](../concepts/missing.md).",
    )
    _write_page(
        wiki_root,
        "concepts/no-citation",
        sources=[],
        body="Hermes Wiki factual claims need an evidence citation.",
    )
    old = (datetime.now(UTC) - timedelta(days=15)).date().isoformat()
    fresh = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    _write_page(
        wiki_root,
        "concepts/stale-unverified",
        body=f"[unverified:{old}] An old unverified claim with a citation.",
    )
    _write_page(
        wiki_root,
        "concepts/fresh-unverified",
        body=f"[unverified:{fresh}] A fresh unverified claim with a citation.",
    )
    _write_page(wiki_root, "concepts/unindexed")
    _write_page(
        wiki_root,
        "concepts/too-long",
        body="\n".join(f"Line {index}" for index in range(201)),
    )
    _write_page(wiki_root, "concepts/bad-tag", tags=["bogus-tag"])
    _write_page(wiki_root, "concepts/missing-title", omit={"title"})
    _write_page(
        wiki_root,
        "concepts/contested",
        extra={"contested": True},
    )
    _write_page(
        wiki_root,
        "sources/unindexed-source",
        page_type="source",
        body="A Source Page omitted from the index must still be linted.",
    )
    _rewrite_index(
        wiki_root,
        [
            "concepts/orphan",
            "concepts/broken",
            "concepts/no-citation",
            "concepts/stale-unverified",
            "concepts/fresh-unverified",
            "concepts/too-long",
            "concepts/bad-tag",
            "concepts/missing-title",
            "concepts/contested",
        ],
    )
    _seed_projection(wiki_root, taxonomy=["agents"])
    capsys.readouterr()

    _code, report = _lint(tmp_path, capsys, "--wiki", "ai-tooling")
    checks = _checks(report)

    expected = {
        "orphan_page": "medium",
        "broken_link": "high",
        "missing_citation": "high",
        "stale_unverified": "medium",
        "missing_from_index": "medium",
        "page_too_long": "low",
        "invalid_tag": "high",
        "missing_frontmatter_field": "high",
        "unresolved_contested": "medium",
    }
    for check, severity in expected.items():
        assert checks[check][0]["severity"] == severity
    assert not [
        finding
        for finding in checks.get("stale_unverified", [])
        if finding.get("page") == "concepts/fresh-unverified"
    ]
    assert any(
        finding.get("page") == "sources/unindexed-source"
        for finding in checks["missing_from_index"]
    )


def test_lint_flags_embedded_page_history_blocks(
    tmp_path: Path,
    capsys,
) -> None:
    """Page History belongs outside Wiki Page bodies and is linted if embedded."""

    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    wiki_root = tmp_path / "wikis" / "ai-tooling"
    _write_page(
        wiki_root,
        "concepts/history-in-body",
        body=(
            "# History In Body\n\n"
            "Knowledge content belongs here.\n\n"
            "## Page History\n\n"
            "- 2026-06-05 agent-alpha edited this page."
        ),
    )
    _rewrite_index(wiki_root, ["concepts/history-in-body"])
    _seed_projection(wiki_root, taxonomy=["agents"])
    capsys.readouterr()

    _code, report = _lint(tmp_path, capsys, "--wiki", "ai-tooling")
    checks = _checks(report)

    assert checks["history_in_body"][0]["severity"] == "high"
    assert checks["history_in_body"][0]["page"] == "concepts/history-in-body"


def test_lint_reports_storage_plugin_inbox_and_projection_checks(
    tmp_path: Path,
    capsys,
) -> None:
    """Non-page §11 checks aggregate in one deterministic JSON report."""

    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    wiki_root = tmp_path / "wikis" / "ai-tooling"
    raw = wiki_root / "raw" / "articles" / "evidence.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("original raw bytes", encoding="utf-8")
    page_path = _write_page(
        wiki_root,
        "concepts/storage",
        sources=[raw.relative_to(wiki_root).as_posix()],
        extra={
            "updated": "2026-01-01T00:00:00Z",
            "kanban_refs": [
                {
                    "task_id": "KB-123",
                    "direction": "page->task",
                    "created": "2026-06-05T00:00:00Z",
                }
            ],
        },
    )
    _rewrite_index(wiki_root, ["concepts/storage", "concepts/missing-index-row"])
    for index in range(501):
        with (wiki_root / "log.md").open("a", encoding="utf-8") as handle:
            handle.write(
                f"| 2026-06-05T00:00:{index % 60:02d}Z | edit | x | lint-tester | human | row |\n"
            )
    plugin = wiki_root / "plugins" / "classifiers" / "foo.py"
    plugin.parent.mkdir(parents=True, exist_ok=True)
    plugin.write_text("def classify(path):\n    return None\n", encoding="utf-8")
    untrusted = wiki_root / "plugins" / "processors" / "bar.py"
    untrusted.parent.mkdir(parents=True, exist_ok=True)
    untrusted.write_text("def process(path, label):\n    return []\n", encoding="utf-8")
    inbox = wiki_root / "raw" / "inbox" / "big.bin"
    inbox.parent.mkdir(parents=True, exist_ok=True)
    with inbox.open("wb") as handle:
        handle.truncate(50 * 1024 * 1024 + 1)
    _seed_projection(wiki_root, taxonomy=["agents"])
    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        db.upsert_source(
            conn,
            id=raw.relative_to(wiki_root).as_posix(),
            ingested_at="2026-06-05T00:00:00Z",
            sha256=projection.sha256_file(raw),
            source_url="https://fixtures.invalid/evidence",
            source_path=raw.relative_to(wiki_root).as_posix(),
            classified_as="article",
        )
        db.insert_ingest_log(
            conn,
            ingested_at="2026-06-05T00:00:00Z",
            source_type="article",
            source_url="https://fixtures.invalid/evidence",
            source_path=raw.relative_to(wiki_root).as_posix(),
            sha256=projection.sha256_file(raw),
            pages_created=["concepts/storage"],
            pages_updated=[],
            drift_detected=1,
            author="lint-tester",
            author_kind="human",
        )
        db.upsert_trusted_plugin(
            conn,
            name="foo",
            kind="classifier",
            path="plugins/classifiers/foo.py",
            sha256=projection.sha256_file(plugin),
            trusted_at="2026-06-05T00:00:00Z",
        )
        db.upsert_kanban_ref(
            conn,
            page_id="concepts/storage",
            task_id="KB-999",
            direction="page->task",
            created="2026-06-05T00:00:00Z",
        )
        conn.commit()
    raw.write_text("mutated raw bytes", encoding="utf-8")
    plugin.write_text("def classify(path):\n    raise RuntimeError('changed')\n", encoding="utf-8")
    page_path.write_text(
        page_path.read_text(encoding="utf-8").replace("title: Storage", "title: Storage Drift"),
        encoding="utf-8",
    )
    capsys.readouterr()

    first_code, first_report = _lint(tmp_path, capsys, "--wiki", "ai-tooling")
    second_code, second_report = _lint(tmp_path, capsys, "--wiki", "ai-tooling")
    checks = _checks(first_report)

    expected = {
        "log_too_long": "low",
        "raw_snapshot_mutation": "high",
        "external_source_drift": "medium",
        "projection_version_mismatch": "high",
        "kanban_projection_drift": "medium",
        "trusted_plugin_hash_mismatch": "high",
        "untrusted_plugin_present": "medium",
        "oversized_inbox_item": "medium",
        "cross_consistency": "high",
        "stale_content": "medium",
    }
    for check, severity in expected.items():
        assert checks[check][0]["severity"] == severity
    assert {finding["check"] for finding in first_report["findings"]} >= set(expected)
    assert first_code == second_code
    assert second_report["findings"]
    assert first_report["health_score"] < 0.9


def test_lint_uses_current_resolution_and_denies_archived_without_disclosure(
    tmp_path: Path,
    capsys,
) -> None:
    """The lint CLI follows wiki resolution and visibility discipline."""

    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    assert _run_cli(tmp_path, "create", "old-wiki") == 0
    assert _run_cli(tmp_path, "switch", "ai-tooling") == 0
    capsys.readouterr()

    _code, current_report = _lint(tmp_path, capsys)
    _code, explicit_report = _lint(tmp_path, capsys, "--wiki", "ai-tooling")
    assert current_report["wiki"] == explicit_report["wiki"] == "ai-tooling"

    assert _run_cli(tmp_path, "archive", "old-wiki") == 0
    capsys.readouterr()
    assert _run_cli(tmp_path, "lint", "--wiki", "old-wiki") == 1
    captured = capsys.readouterr()
    assert captured.err.strip() == "not found or not visible"
    assert captured.out == ""


def test_lint_flags_unresolved_citations(tmp_path: Path, capsys) -> None:
    """``sources:`` entries must resolve to a page id or a wiki-local file."""

    assert _run_cli(tmp_path, "create", "ai-tooling") == 0
    wiki_root = tmp_path / "wikis" / "ai-tooling"
    raw = wiki_root / "raw" / "articles" / "evidence.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("evidence snapshot", encoding="utf-8")
    _write_page(
        wiki_root,
        "sources/2026-06-05-evidence",
        page_type="source",
        sources=["raw/articles/evidence.md"],
    )
    _write_page(
        wiki_root,
        "concepts/cited-ok",
        sources=["raw/articles/evidence.md", "sources/2026-06-05-evidence"],
    )
    _write_page(
        wiki_root,
        "concepts/cited-broken",
        sources=[
            "raw/articles/never-snapshotted.md",
            "../outside-the-wiki.md",
            "https://example.com/external-provenance",
        ],
    )
    _rewrite_index(
        wiki_root,
        ["sources/2026-06-05-evidence", "concepts/cited-ok", "concepts/cited-broken"],
    )
    _seed_projection(wiki_root)
    capsys.readouterr()

    _code, report = _lint(tmp_path, capsys, "--wiki", "ai-tooling")
    unresolved = _checks(report).get("unresolved_citation", [])

    assert {finding["citation"] for finding in unresolved} == {
        "raw/articles/never-snapshotted.md",
        "../outside-the-wiki.md",
    }
    assert all(finding["page"] == "concepts/cited-broken" for finding in unresolved)
    assert all(finding["severity"] == "high" for finding in unresolved)


def test_dangling_kanban_findings_survive_midloop_unavailability(monkeypatch) -> None:
    """Findings confirmed before kanban becomes unreachable must be kept."""

    from hermes_wiki import kanban_link, lint
    from hermes_wiki.kanban_link import KanbanUnavailableError

    calls: list[str] = []

    def fake_read_task(task_id: str):
        calls.append(task_id)
        if task_id == "KB-1":
            return None  # confirmed dangling while kanban was reachable
        raise KanbanUnavailableError("kanban went away mid-scan")

    monkeypatch.setattr(kanban_link, "read_task", fake_read_task)

    refs = {
        ("concepts/a", "KB-1", "page->task"),
        ("concepts/b", "KB-2", "page->task"),
        ("concepts/c", "KB-3", "page->task"),
    }
    findings = lint._dangling_kanban_findings(refs)

    assert calls == ["KB-1", "KB-2"]  # sorted order; scan stops at the failure
    assert [finding["task_id"] for finding in findings] == ["KB-1"]
    assert findings[0]["check"] == "dangling_kanban_ref"

    # Kanban down from the very first call: no refs were confirmed, report none.
    monkeypatch.setattr(
        kanban_link,
        "read_task",
        lambda task_id: (_ for _ in ()).throw(KanbanUnavailableError("down")),
    )
    assert lint._dangling_kanban_findings(refs) == []
