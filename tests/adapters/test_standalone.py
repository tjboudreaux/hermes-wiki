"""Tests for standalone adapter seam implementations."""

from __future__ import annotations

from adapters.base import MonitorJob
from adapters.standalone import StandaloneKanbanReader, StandaloneToolRegistry, create_adapters


def test_standalone_home_and_config_use_isolated_home(tmp_path, monkeypatch) -> None:
    """Standalone adapters resolve home/config without importing Hermes."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "wiki:\n  current: ai-tooling\n  adapter: standalone\n"
        "toolsets:\n  - wiki\n",
        encoding="utf-8",
    )
    wikis_dir = tmp_path / "wikis"
    wikis_dir.mkdir()
    (wikis_dir / "research.current").write_text("ai-tooling\n", encoding="utf-8")
    (wikis_dir / "default").write_text("fallback\n", encoding="utf-8")

    adapters = create_adapters()

    assert adapters.name == "standalone"
    assert adapters.home.home() == tmp_path
    assert adapters.home.current_wiki("research") == "ai-tooling"
    assert adapters.home.current_wiki("other") == "fallback"
    assert adapters.config.load()["wiki"]["current"] == "ai-tooling"
    assert adapters.config.load()["toolsets"] == ["wiki"]


def test_standalone_tool_registry_prompt_kanban_cron_and_dashboard(tmp_path, monkeypatch) -> None:
    """Standalone seam implementations provide deterministic local behavior."""
    from fixtures.factory import build_populated_home

    home = tmp_path / "hermes-home"
    fixture = build_populated_home(home)
    monkeypatch.setenv("HERMES_HOME", str(home))
    adapters = create_adapters()

    def echo(value: str) -> str:
        return value

    assert isinstance(adapters.tools, StandaloneToolRegistry)
    adapters.tools.register("echo", echo, check_fn=lambda: True)
    assert adapters.tools.call("echo", "ok") == "ok"
    assert list(adapters.tools.registered_tools()) == ["echo"]

    block = adapters.prompts.available_wikis_block(profile="research")
    assert "# Available Wikis" in block
    assert fixture.primary_slug in block
    assert fixture.private_slug not in block
    assert fixture.archived_slug not in block

    assert isinstance(adapters.kanban, StandaloneKanbanReader)
    adapters.kanban.add_task("KB-1", {"id": "KB-1", "title": "Read-only task"})
    task = adapters.kanban.get_task("KB-1")
    assert task is not None
    assert task["title"] == "Read-only task"
    assert adapters.kanban.list_tasks(limit=1) == [{"id": "KB-1", "title": "Read-only task"}]

    job = MonitorJob(
        name="wiki:ai-tooling:weekly",
        schedule="0 9 * * 1",
        prompt="Sweep for new sources",
        env={"HERMES_WIKI": "ai-tooling"},
    )
    first = adapters.cron.reconcile([job])
    second = adapters.cron.reconcile([job])
    assert first.created == ["wiki:ai-tooling:weekly"]
    assert second.created == []
    assert adapters.cron.list_jobs()[0]["env"]["HERMES_WIKI"] == "ai-tooling"

    manifest = adapters.dashboard.manifest()
    assert manifest["name"] == "wiki"
    assert manifest["icon"] == "FileText"
