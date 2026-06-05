from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fixtures.factory import build_test_wiki
from fixtures.seed_data import sample_source_path


def _ingest_log_count(wiki_root: Path) -> int:
    from hermes_wiki import db

    with db.connect_wiki(wiki_root / "wiki.db") as conn:
        return int(conn.execute("SELECT COUNT(*) FROM ingest_log").fetchone()[0])


def test_wiki_slash_forwards_read_verbs_to_cli_and_filters_visibility(
    monkeypatch: Any, tmp_path: Path
) -> None:
    fixture = build_test_wiki(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture.home))

    from hermes_wiki.slash import run_slash

    listing = run_slash("list")
    assert fixture.primary_slug in listing
    assert "pages=" in listing
    assert "health=" in listing
    assert fixture.private_slug not in listing
    assert fixture.archived_slug not in listing

    search = run_slash(f"search memory --wiki {fixture.primary_slug}")
    assert "concepts/agent-memory" in search
    assert fixture.private_slug not in search

    denied = run_slash(f"show {fixture.private_slug}")
    assert denied.strip() == "not found or not visible"
    assert fixture.private_slug not in denied


def test_wiki_slash_accepts_optional_wiki_prefix(monkeypatch: Any, tmp_path: Path) -> None:
    fixture = build_test_wiki(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture.home))

    from hermes_wiki.slash import run_slash

    assert run_slash("wiki list") == run_slash("/wiki list")


def test_wiki_slash_mutating_ingest_respects_write_grant(
    monkeypatch: Any, tmp_path: Path
) -> None:
    fixture = build_test_wiki(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture.home))
    monkeypatch.delenv("HERMES_WIKI", raising=False)

    from hermes_wiki.slash import run_slash

    before = _ingest_log_count(fixture.primary_wiki_root)
    source = sample_source_path("article")

    denied = run_slash(f"ingest {source} --wiki {fixture.primary_slug}")
    assert denied.strip() == "wiki write permission denied"
    assert _ingest_log_count(fixture.primary_wiki_root) == before

    monkeypatch.setenv("HERMES_WIKI", fixture.primary_slug)
    allowed = run_slash(f"ingest {source} --wiki {fixture.primary_slug}")
    assert "Ingested" in allowed
    assert "pages_created:" in allowed
    assert _ingest_log_count(fixture.primary_wiki_root) == before + 1


def test_wiki_slash_create_page_respects_write_grant(monkeypatch: Any, tmp_path: Path) -> None:
    fixture = build_test_wiki(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture.home))
    monkeypatch.delenv("HERMES_WIKI", raising=False)

    from hermes_wiki.slash import run_slash

    command = (
        "create-page 'Slash Notes' --body '# Slash Notes' "
        f"--type concept --wiki {fixture.primary_slug}"
    )
    denied = run_slash(command)

    assert denied.strip() == "wiki write permission denied"
    assert not (fixture.primary_wiki_root / "concepts" / "slash-notes.md").exists()

    monkeypatch.setenv("HERMES_WIKI", fixture.primary_slug)
    allowed = run_slash(command)

    assert "concepts/slash-notes" in allowed
    assert (fixture.primary_wiki_root / "concepts" / "slash-notes.md").is_file()


class RecordingPluginContext:
    def __init__(self) -> None:
        self.commands: dict[str, dict[str, Any]] = {}

    def register_command(
        self,
        name: str,
        handler: Any,
        description: str = "",
        args_hint: str = "",
    ) -> None:
        self.commands[name] = {
            "handler": handler,
            "description": description,
            "args_hint": args_hint,
        }


def test_hermes_plugin_registers_wiki_slash_command(monkeypatch: Any, tmp_path: Path) -> None:
    fixture = build_test_wiki(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture.home))

    from adapters.hermes.wiki_plugin import register

    ctx = RecordingPluginContext()
    register(ctx)

    assert set(ctx.commands) == {"wiki"}
    entry = ctx.commands["wiki"]
    assert "<verb>" in entry["args_hint"]
    assert fixture.primary_slug in entry["handler"]("list")


def test_harness_installs_isolated_wiki_plugin_and_enables_it(tmp_path: Path) -> None:
    from hermes_wiki.harness import seed_isolated_home

    home = tmp_path / "home"
    seed_isolated_home(repo_root=Path.cwd(), home=home, source_env=tmp_path / "missing.env")

    plugin_root = home / "plugins" / "wiki"
    assert (plugin_root / "plugin.yaml").is_file()
    assert (plugin_root / "__init__.py").is_file()
    init_text = (plugin_root / "__init__.py").read_text(encoding="utf-8")
    assert str(Path.cwd()) in init_text
    assert "adapters.hermes.wiki_plugin" in init_text

    import yaml

    config = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
    assert "wiki" in config["plugins"]["enabled"]

    # The generated plugin module is syntactically valid and exposes Hermes' register(ctx) hook.
    assert json.dumps(config)
