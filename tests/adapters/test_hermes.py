"""Read-only tests for Hermes-backed adapter stubs."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

from adapters.hermes import (
    HermesConfigLoader,
    HermesCronAdapter,
    HermesDashboardLoader,
    HermesHomeResolver,
    HermesKanbanReader,
    HermesPromptInjector,
    HermesToolRegistry,
    create_adapters,
)


def test_hermes_adapters_import_real_installed_symbols(monkeypatch) -> None:
    """Hermes adapter classes resolve the installed Hermes v0.15.1 modules."""
    isolated_home = Path.cwd() / ".hermes-test"
    monkeypatch.setenv("HERMES_HOME", str(isolated_home))

    adapters = create_adapters()

    assert adapters.name == "hermes"
    assert isinstance(adapters.home, HermesHomeResolver)
    assert isinstance(adapters.config, HermesConfigLoader)
    assert isinstance(adapters.tools, HermesToolRegistry)
    assert isinstance(adapters.prompts, HermesPromptInjector)
    assert isinstance(adapters.kanban, HermesKanbanReader)
    assert isinstance(adapters.cron, HermesCronAdapter)
    assert isinstance(adapters.dashboard, HermesDashboardLoader)

    assert adapters.home.home() == isolated_home
    assert isinstance(adapters.config.load(), dict)
    assert callable(adapters.kanban.module.get_task)
    assert callable(adapters.kanban.module.list_tasks)
    assert callable(adapters.cron.module.create_job)
    assert callable(adapters.cron.module.list_jobs)
    assert callable(adapters.cron.module.compute_next_run)
    assert callable(adapters.prompts.module.build_skills_system_prompt)
    assert callable(adapters.dashboard.module._discover_dashboard_plugins)


def test_hermes_prompt_injector_uses_visible_wiki_block(monkeypatch, tmp_path) -> None:
    from fixtures.factory import build_test_wiki

    fixture = build_test_wiki(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture.home))

    injector = HermesPromptInjector()
    block = injector.available_wikis_block(profile=fixture.profile)

    assert "# Available Wikis" in block
    assert fixture.primary_slug in block
    assert fixture.private_slug not in block
    assert fixture.archived_slug not in block
    assert "AI agents, coding tools, and research workflows" in block
    assert "Use wiki_search" in block


def test_hermes_prompt_injection_installs_idempotent_system_prompt_wrapper(
    monkeypatch, tmp_path
) -> None:
    from adapters.hermes import install_prompt_injection
    from fixtures.factory import build_test_wiki

    fixture = build_test_wiki(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(fixture.home))

    fake_system_prompt = ModuleType("agent.system_prompt")

    def build_system_prompt_parts(agent, system_message=None):
        del agent, system_message
        return {"stable": "base stable", "context": "", "volatile": ""}

    fake_system_prompt.__dict__["build_system_prompt_parts"] = build_system_prompt_parts
    monkeypatch.setitem(sys.modules, "agent.system_prompt", fake_system_prompt)

    assert install_prompt_injection()
    assert install_prompt_injection()

    wrapped = fake_system_prompt.__dict__["build_system_prompt_parts"]
    parts = wrapped(object())
    assert parts["stable"].count("# Available Wikis") == 1
    assert fixture.primary_slug in parts["stable"]
    assert fixture.private_slug not in parts["stable"]
