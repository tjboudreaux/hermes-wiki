"""Read-only tests for Hermes-backed adapter stubs."""

from __future__ import annotations

from pathlib import Path

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
