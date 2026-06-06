"""Read-only tests for Hermes-backed adapter stubs."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from adapters.base import MonitorJob
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

_has_hermes_cli = importlib.util.find_spec("hermes_cli") is not None


class _FakeCronModule:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []
        self.crash_on_first_update = False
        self.crash_on_update_call: int | None = None
        self.update_calls = 0

    def parse_schedule(self, schedule: str) -> dict[str, str]:
        parts = schedule.split()
        if len(parts) == 5 or "T" in schedule:
            return {"display": schedule}
        raise ValueError(f"invalid schedule: {schedule}")

    def list_jobs(self, include_disabled: bool = False) -> list[dict[str, Any]]:
        if include_disabled:
            return [dict(job) for job in self.jobs]
        return [dict(job) for job in self.jobs if job.get("enabled", True)]

    def create_job(
        self,
        prompt: str,
        schedule: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        job = {
            "id": f"job-{len(self.jobs) + 1}",
            "name": kwargs["name"],
            "prompt": prompt,
            "schedule_display": schedule,
            "skills": list(kwargs.get("skills") or []),
            "origin": dict(kwargs.get("origin") or {}),
            "enabled": True,
            "state": "scheduled",
        }
        self.jobs.append(job)
        return dict(job)

    def update_job(self, job_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        self.update_calls += 1
        if (self.crash_on_first_update and self.update_calls == 1) or (
            self.crash_on_update_call == self.update_calls
        ):
            raise RuntimeError("simulated crash after create_job")
        for job in self.jobs:
            if job["id"] == job_id:
                job.update(updates)
                if "schedule" in updates:
                    job["schedule_display"] = updates["schedule"]
                return dict(job)
        return None

    def remove_job(self, job_id: str) -> None:
        self.jobs = [job for job in self.jobs if job["id"] != job_id]


class _FakeHermesCronAdapter(HermesCronAdapter):
    def __init__(self, module: _FakeCronModule) -> None:
        self._module = module

    @property
    def module(self) -> _FakeCronModule:
        return self._module


@pytest.mark.skipif(not _has_hermes_cli, reason="hermes-agent not installed")
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


def test_hermes_cron_reconcile_interrupted_create_is_inert_then_repaired() -> None:
    """A crash between create/update must not leave a runnable env-less wiki job."""
    module = _FakeCronModule()
    module.crash_on_first_update = True
    adapter = _FakeHermesCronAdapter(module)
    desired = MonitorJob(
        name="wiki:ai-tooling:weekly-arxiv-sweep",
        schedule="0 9 * * 1",
        prompt="Sweep arxiv for new AI agent papers",
        skills=("wiki-ingest",),
        env={"HERMES_WIKI": "ai-tooling"},
        origin={
            "wiki_slug": "ai-tooling",
            "monitor_name": "weekly-arxiv-sweep",
            "source_kind": "arxiv",
        },
    )

    try:
        adapter.reconcile([desired], owner_prefix="wiki:ai-tooling:")
    except RuntimeError as exc:
        assert "simulated crash" in str(exc)
    else:  # pragma: no cover - documents the intended failure simulation
        raise AssertionError("first reconcile should simulate an interrupted update")

    assert len(module.jobs) == 1
    interrupted = module.jobs[0]
    assert interrupted.get("env") is None
    assert interrupted["origin"].get("source") == "hermes-wiki"
    assert interrupted["origin"].get("not_ready") is True
    assert interrupted["prompt"] != desired.prompt
    assert interrupted["schedule_display"] != desired.schedule

    module.crash_on_first_update = False
    result = adapter.reconcile([desired], owner_prefix="wiki:ai-tooling:")

    assert result.created == []
    assert result.updated == ["wiki:ai-tooling:weekly-arxiv-sweep"]
    repaired = module.jobs[0]
    assert repaired["env"] == {"HERMES_WIKI": "ai-tooling"}
    assert repaired["origin"] == {
        "source": "hermes-wiki",
        "env": {"HERMES_WIKI": "ai-tooling"},
        "wiki_slug": "ai-tooling",
        "monitor_name": "weekly-arxiv-sweep",
        "source_kind": "arxiv",
    }
    assert repaired["prompt"] == desired.prompt
    assert repaired["schedule_display"] == desired.schedule
    assert repaired["skills"] == ["wiki-ingest"]
    assert repaired["enabled"] is True


def test_hermes_cron_reconcile_repairs_legacy_job_missing_env_origin() -> None:
    """A prior interrupted two-step reconcile is repaired on the next pass."""
    module = _FakeCronModule()
    adapter = _FakeHermesCronAdapter(module)
    desired = MonitorJob(
        name="wiki:ai-tooling:weekly-arxiv-sweep",
        schedule="0 9 * * 1",
        prompt="Sweep arxiv for new AI agent papers",
        skills=("wiki-ingest",),
        env={"HERMES_WIKI": "ai-tooling"},
        origin={
            "wiki_slug": "ai-tooling",
            "monitor_name": "weekly-arxiv-sweep",
            "source_kind": "arxiv",
        },
    )
    module.jobs.append(
        {
            "id": "job-legacy",
            "name": "wiki:ai-tooling:weekly-arxiv-sweep",
            "prompt": desired.prompt,
            "schedule_display": desired.schedule,
            "skills": ["wiki-ingest"],
            "enabled": True,
        }
    )

    result = adapter.reconcile([desired], owner_prefix="wiki:ai-tooling:")

    assert result.updated == ["wiki:ai-tooling:weekly-arxiv-sweep"]
    assert result.failed == []
    repaired = module.jobs[0]
    assert repaired["env"] == {"HERMES_WIKI": "ai-tooling"}
    assert repaired["origin"]["source"] == "hermes-wiki"
    assert repaired["origin"]["wiki_slug"] == "ai-tooling"


def test_hermes_cron_reconcile_interrupted_after_disable_enables_last() -> None:
    """If final activation is interrupted, next reconcile enables only after repair."""
    module = _FakeCronModule()
    module.crash_on_update_call = 2
    adapter = _FakeHermesCronAdapter(module)
    desired = MonitorJob(
        name="wiki:ai-tooling:weekly-arxiv-sweep",
        schedule="0 9 * * 1",
        prompt="Sweep arxiv for new AI agent papers",
        skills=("wiki-ingest",),
        env={"HERMES_WIKI": "ai-tooling"},
        origin={
            "wiki_slug": "ai-tooling",
            "monitor_name": "weekly-arxiv-sweep",
            "source_kind": "arxiv",
        },
    )

    try:
        adapter.reconcile([desired], owner_prefix="wiki:ai-tooling:")
    except RuntimeError as exc:
        assert "simulated crash" in str(exc)
    else:  # pragma: no cover - documents the intended failure simulation
        raise AssertionError("second update should simulate interrupted activation")

    interrupted = module.jobs[0]
    assert interrupted["env"] == {"HERMES_WIKI": "ai-tooling"}
    assert interrupted["origin"]["source"] == "hermes-wiki"
    assert interrupted["enabled"] is False
    assert interrupted["state"] == "paused"
    assert interrupted["prompt"] != desired.prompt

    module.crash_on_update_call = None
    result = adapter.reconcile([desired], owner_prefix="wiki:ai-tooling:")

    assert result.updated == ["wiki:ai-tooling:weekly-arxiv-sweep"]
    repaired = module.jobs[0]
    assert repaired["prompt"] == desired.prompt
    assert repaired["schedule_display"] == desired.schedule
    assert repaired["enabled"] is True
    assert repaired["state"] == "scheduled"
    assert repaired["paused_reason"] is None


def test_hermes_cron_reconcile_keeps_explicit_same_name_foreign_job_untouched() -> None:
    """Explicitly foreign jobs with colliding names remain collisions, not repairs."""
    module = _FakeCronModule()
    adapter = _FakeHermesCronAdapter(module)
    desired = MonitorJob(
        name="wiki:ai-tooling:weekly-arxiv-sweep",
        schedule="0 9 * * 1",
        prompt="Sweep arxiv for new AI agent papers",
        env={"HERMES_WIKI": "ai-tooling"},
    )
    foreign = {
        "id": "job-foreign",
        "name": "wiki:ai-tooling:weekly-arxiv-sweep",
        "prompt": desired.prompt,
        "origin": {"source": "not-hermes-wiki"},
        "enabled": True,
    }
    module.jobs.append(dict(foreign))

    result = adapter.reconcile([desired], owner_prefix="wiki:ai-tooling:")

    assert result.failed == ["wiki:ai-tooling:weekly-arxiv-sweep"]
    assert result.errors == ["collision: wiki:ai-tooling:weekly-arxiv-sweep"]
    assert module.jobs == [foreign]


@pytest.mark.skipif(not _has_hermes_cli, reason="hermes-agent not installed")
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


@pytest.mark.skipif(not _has_hermes_cli, reason="hermes-agent not installed")
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
