"""Typed adapter seams for Hermes Wiki integration points.

The core ``hermes_wiki`` package depends on these Protocols, not on Hermes
internals. Runtime selection imports either ``adapters.standalone`` or
``adapters.hermes`` lazily so the default standalone path has no Hermes import
side effects.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

ToolCallable = Callable[..., Any]
ToolCheck = Callable[[], bool]


class AdapterSelectionError(ValueError):
    """Raised when adapter selection receives an unknown adapter name."""


@dataclass(frozen=True)
class MonitorJob:
    """Desired wiki-owned monitor job reconciled through the cron seam."""

    name: str
    schedule: str
    prompt: str
    skills: Sequence[str] = field(default_factory=tuple)
    env: Mapping[str, str] = field(default_factory=dict)
    enabled: bool = True
    origin: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CronReconcileResult:
    """Summary of a cron reconcile operation."""

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@runtime_checkable
class HomeResolver(Protocol):
    """Resolves Hermes home and the profile-local current Wiki."""

    def home(self) -> Path:
        """Return the active Hermes home path."""

    def current_wiki(self, profile: str | None = None) -> str | None:
        """Return the resolved current wiki slug for a profile, if any."""


@runtime_checkable
class ConfigLoader(Protocol):
    """Loads Hermes or standalone configuration."""

    def load(self) -> dict[str, Any]:
        """Return configuration as a plain dictionary."""


@runtime_checkable
class ToolRegistry(Protocol):
    """Registers Hermes Wiki agent tools behind an integration seam."""

    def register(
        self,
        name: str,
        fn: ToolCallable,
        check_fn: ToolCheck | None = None,
        *,
        schema: Mapping[str, Any] | None = None,
    ) -> None:
        """Register a tool function, optionally gated by ``check_fn``."""


@runtime_checkable
class PromptInjector(Protocol):
    """Builds the prompt block that exposes visible Wikis to an agent."""

    def available_wikis_block(self, profile: str | None = None) -> str:
        """Return a ``# Available Wikis`` system-prompt block."""


@runtime_checkable
class KanbanReader(Protocol):
    """Read-only Kanban seam. Implementations must not mutate kanban state."""

    def get_task(self, task_id: str) -> Mapping[str, Any] | None:
        """Return task metadata for ``task_id`` when it exists."""

    def list_tasks(
        self,
        *,
        status: str | None = None,
        assignee: str | None = None,
        limit: int | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        """Return read-only task metadata."""


@runtime_checkable
class CronAdapter(Protocol):
    """Cron seam for idempotently reconciling Wiki monitor jobs."""

    def reconcile(
        self,
        jobs: Sequence[MonitorJob],
        *,
        owner_prefix: str | None = None,
    ) -> CronReconcileResult:
        """Create/update/remove wiki-owned jobs to match ``jobs``."""

    def list_jobs(self, *, include_disabled: bool = False) -> Sequence[Mapping[str, Any]]:
        """Return cron job metadata."""


@runtime_checkable
class DashboardLoader(Protocol):
    """Dashboard plugin loader seam."""

    def manifest(self) -> Mapping[str, Any]:
        """Return the dashboard plugin manifest for the Wiki tab."""

    def router(self) -> Any | None:
        """Return the dashboard API router when one is available."""


@dataclass(frozen=True)
class AdapterSet:
    """Concrete implementation bundle for every Hermes Wiki seam."""

    name: str
    home: HomeResolver
    config: ConfigLoader
    tools: ToolRegistry
    prompts: PromptInjector
    kanban: KanbanReader
    cron: CronAdapter
    dashboard: DashboardLoader


def _config_adapter_name(config: Mapping[str, Any] | None) -> str | None:
    if not config:
        return None
    for section_name in ("wiki", "hermes_wiki"):
        section = config.get(section_name)
        if isinstance(section, Mapping):
            value = section.get("adapter")
            if isinstance(value, str) and value.strip():
                return value
    value = config.get("adapter")
    if isinstance(value, str) and value.strip():
        return value
    return None


def select_adapter_name(
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Select an adapter from env/config, defaulting to ``standalone``.

    Precedence:
    1. ``HERMES_WIKI_ADAPTER`` environment variable
    2. ``wiki.adapter`` / ``hermes_wiki.adapter`` / top-level ``adapter``
    3. ``standalone``
    """

    source_env = env if env is not None else os.environ
    selected = source_env.get("HERMES_WIKI_ADAPTER") or _config_adapter_name(config)
    name = (selected or "standalone").strip().lower().replace("-", "_")
    if name not in {"standalone", "hermes"}:
        raise AdapterSelectionError(
            f"unknown Hermes Wiki adapter {selected!r}; expected 'standalone' or 'hermes'"
        )
    return name


def create_adapters(
    name: str | None = None,
    *,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> AdapterSet:
    """Create the selected adapter bundle lazily."""

    selected = (name or select_adapter_name(config=config, env=env)).strip().lower()
    selected = selected.replace("-", "_")
    if selected == "standalone":
        from adapters.standalone import create_adapters as create_standalone_adapters

        return create_standalone_adapters(env=env)
    if selected == "hermes":
        from adapters.hermes import create_adapters as create_hermes_adapters

        return create_hermes_adapters()
    raise AdapterSelectionError(
        f"unknown Hermes Wiki adapter {name!r}; expected 'standalone' or 'hermes'"
    )
