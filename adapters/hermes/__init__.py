"""Hermes-backed adapter implementations.

This layer is the only place the plugin imports installed Hermes modules.
Imports are lazy and read-only by default so the standalone package can run
without Hermes on ``sys.path``.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from adapters.base import AdapterSet, CronReconcileResult, MonitorJob, ToolCallable, ToolCheck
from adapters.standalone import WIKI_DASHBOARD_MANIFEST


def _default_hermes_agent_path() -> Path:
    return Path.home() / ".hermes" / "hermes-agent"


def _ensure_hermes_agent_on_path() -> None:
    if importlib.util.find_spec("hermes_cli") is not None:
        return
    candidate = Path(os.environ.get("HERMES_AGENT_PATH", "") or _default_hermes_agent_path())
    if candidate.exists():
        sys.path.insert(0, str(candidate))


def _import_hermes_module(name: str) -> ModuleType:
    _ensure_hermes_agent_on_path()
    return importlib.import_module(name)


def _mapping_from_object(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {"value": value}


class HermesHomeResolver:
    """Home resolver backed by installed Hermes configuration helpers."""

    @property
    def module(self) -> ModuleType:
        return _import_hermes_module("hermes_cli.config")

    def home(self) -> Path:
        return Path(self.module.get_hermes_home())

    def current_wiki(self, profile: str | None = None) -> str | None:
        wikis_dir = self.home() / "wikis"
        candidates: list[Path] = []
        if profile:
            candidates.append(wikis_dir / f"{profile}.current")
        candidates.append(wikis_dir / "default")
        for path in candidates:
            try:
                value = path.read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                continue
            if value:
                return value
        return None


class HermesConfigLoader:
    """Configuration loader backed by ``hermes_cli.config.load_config``."""

    @property
    def module(self) -> ModuleType:
        return _import_hermes_module("hermes_cli.config")

    def load(self) -> dict[str, Any]:
        loaded = self.module.load_config()
        return dict(loaded) if isinstance(loaded, Mapping) else {}


class HermesToolRegistry:
    """Adapter around Hermes' central ``tools.registry`` singleton."""

    @property
    def module(self) -> ModuleType:
        return _import_hermes_module("tools.registry")

    def register(
        self,
        name: str,
        fn: ToolCallable,
        check_fn: ToolCheck | None = None,
        *,
        schema: Mapping[str, Any] | None = None,
    ) -> None:
        tool_schema = dict(
            schema
            or {
                "name": name,
                "description": f"Hermes Wiki tool {name}",
                "parameters": {"type": "object", "properties": {}},
            }
        )
        self.module.registry.register(
            name=name,
            toolset="wiki",
            schema=tool_schema,
            handler=fn,
            check_fn=check_fn,
            override=True,
        )


class HermesPromptInjector:
    """Prompt seam that imports Hermes prompt-builder symbols."""

    @property
    def module(self) -> ModuleType:
        return _import_hermes_module("agent.prompt_builder")

    def available_wikis_block(self, profile: str | None = None) -> str:
        del profile
        return (
            "# Available Wikis\n"
            "Wiki discovery is provided by Hermes Wiki prompt integration. "
            "Use wiki_search to consult visible knowledge bases."
        )


class HermesKanbanReader:
    """Read-only adapter over ``hermes_cli.kanban_db``."""

    @property
    def module(self) -> ModuleType:
        return _import_hermes_module("hermes_cli.kanban_db")

    def get_task(self, task_id: str) -> Mapping[str, Any] | None:
        conn = self.module.connect()
        try:
            task = self.module.get_task(conn, task_id)
            return _mapping_from_object(task) if task is not None else None
        finally:
            conn.close()

    def list_tasks(
        self,
        *,
        status: str | None = None,
        assignee: str | None = None,
        limit: int | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        conn = self.module.connect()
        try:
            tasks = self.module.list_tasks(
                conn,
                status=status,
                assignee=assignee,
                limit=limit,
            )
            return [_mapping_from_object(task) for task in tasks]
        finally:
            conn.close()


class HermesCronAdapter:
    """Adapter over installed Hermes cron job helpers."""

    @property
    def module(self) -> ModuleType:
        return _import_hermes_module("cron.jobs")

    @staticmethod
    def _origin(job: MonitorJob) -> dict[str, Any]:
        return {
            "source": "hermes-wiki",
            "name": job.name,
            "env": dict(job.env),
        } | dict(job.origin)

    @staticmethod
    def _is_wiki_job(job: Mapping[str, Any]) -> bool:
        name = job.get("name")
        origin = job.get("origin")
        return (
            isinstance(name, str)
            and name.startswith("wiki:")
            and isinstance(origin, Mapping)
            and origin.get("source") == "hermes-wiki"
        )

    def reconcile(self, jobs: Sequence[MonitorJob]) -> CronReconcileResult:
        desired = {job.name: job for job in jobs}
        existing = {
            job["name"]: job
            for job in self.module.list_jobs(include_disabled=True)
            if isinstance(job.get("name"), str) and self._is_wiki_job(job)
        }
        created: list[str] = []
        updated: list[str] = []
        removed: list[str] = []
        unchanged: list[str] = []

        for name, desired_job in desired.items():
            current = existing.get(name)
            origin = self._origin(desired_job)
            if current is None:
                self.module.create_job(
                    desired_job.prompt,
                    desired_job.schedule,
                    name=name,
                    origin=origin,
                    enabled_toolsets=["wiki"],
                )
                created.append(name)
                continue

            updates: dict[str, Any] = {}
            if current.get("prompt") != desired_job.prompt:
                updates["prompt"] = desired_job.prompt
            if current.get("schedule_display") != desired_job.schedule:
                updates["schedule"] = desired_job.schedule
            if current.get("origin") != origin:
                updates["origin"] = origin
            if bool(current.get("enabled", True)) != desired_job.enabled:
                updates["enabled"] = desired_job.enabled
            if updates:
                self.module.update_job(str(current["id"]), updates)
                updated.append(name)
            else:
                unchanged.append(name)

        for name, current in existing.items():
            if name not in desired:
                self.module.remove_job(str(current["id"]))
                removed.append(name)

        return CronReconcileResult(
            created=created,
            updated=updated,
            removed=removed,
            unchanged=unchanged,
        )

    def list_jobs(self, *, include_disabled: bool = False) -> Sequence[Mapping[str, Any]]:
        return list(self.module.list_jobs(include_disabled=include_disabled))


class HermesDashboardLoader:
    """Dashboard loader seam backed by Hermes' plugin discovery module."""

    @property
    def module(self) -> ModuleType:
        return _import_hermes_module("hermes_cli.web_server")

    def manifest(self) -> Mapping[str, Any]:
        return dict(WIKI_DASHBOARD_MANIFEST)

    def router(self) -> Any | None:
        return None

    def discover_dashboard_plugins(self) -> Sequence[Any]:
        return list(self.module._discover_dashboard_plugins())


def create_adapters() -> AdapterSet:
    """Create the Hermes-backed adapter bundle."""

    return AdapterSet(
        name="hermes",
        home=HermesHomeResolver(),
        config=HermesConfigLoader(),
        tools=HermesToolRegistry(),
        prompts=HermesPromptInjector(),
        kanban=HermesKanbanReader(),
        cron=HermesCronAdapter(),
        dashboard=HermesDashboardLoader(),
    )


__all__ = [
    "HermesConfigLoader",
    "HermesCronAdapter",
    "HermesDashboardLoader",
    "HermesHomeResolver",
    "HermesKanbanReader",
    "HermesPromptInjector",
    "HermesToolRegistry",
    "create_adapters",
]
