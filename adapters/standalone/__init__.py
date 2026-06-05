"""Standalone adapter implementations for local tests and isolated runs."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from adapters.base import AdapterSet, CronReconcileResult, MonitorJob, ToolCallable, ToolCheck

WIKI_DASHBOARD_MANIFEST: dict[str, Any] = {
    "name": "wiki",
    "version": "1.0.0",
    "label": "Wikis",
    "icon": "FileText",
    "tab": {"path": "/wikis", "position": "after:skills"},
    "entry": "dist/index.js",
    "css": "dist/style.css",
    "api": "plugin_api.py",
}


def _repo_default_home() -> Path:
    return Path(__file__).resolve().parents[2] / ".hermes-test"


def _coerce_scalar(value: str) -> Any:
    stripped = value.strip()
    if stripped in {"", "null", "None", "~"}:
        return None
    if stripped in {"true", "True"}:
        return True
    if stripped in {"false", "False"}:
        return False
    if stripped.startswith("[") and stripped.endswith("]"):
        inner = stripped[1:-1].strip()
        if not inner:
            return []
        return [_coerce_scalar(part.strip()) for part in inner.split(",")]
    return stripped.strip("\"'")


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """Parse the small config subset used by the standalone adapter.

    This is a dependency-free fallback for simple ``config.yaml`` files. If
    PyYAML is installed, ``StandaloneConfigLoader`` uses it instead.
    """

    root: dict[str, Any] = {}
    current_section: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not raw_line.startswith(" ") and line.endswith(":"):
            current_section = line[:-1].strip()
            root[current_section] = {}
            continue
        if not raw_line.startswith(" ") and ":" in line:
            key, value = line.split(":", 1)
            root[key.strip()] = _coerce_scalar(value)
            current_section = None
            continue
        if current_section is None:
            continue
        section = root.setdefault(current_section, {})
        if isinstance(section, list) and line.strip().startswith("- "):
            section.append(_coerce_scalar(line.strip()[2:]))
            continue
        if line.strip().startswith("- "):
            root[current_section] = [_coerce_scalar(line.strip()[2:])]
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            container = root.setdefault(current_section, {})
            if isinstance(container, dict):
                container[key.strip()] = _coerce_scalar(value)
    return root


class StandaloneHomeResolver:
    """Home resolver for tests and local isolated Hermes homes."""

    def __init__(self, home_path: Path | None = None, env: Mapping[str, str] | None = None) -> None:
        self._env = env if env is not None else os.environ
        self._home_path = Path(home_path) if home_path is not None else None

    def home(self) -> Path:
        if self._home_path is not None:
            return self._home_path
        env_home = self._env.get("HERMES_HOME", "").strip()
        return Path(env_home) if env_home else _repo_default_home()

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


class StandaloneConfigLoader:
    """Reads ``config.yaml`` from the resolved standalone home."""

    def __init__(self, home: StandaloneHomeResolver) -> None:
        self._home = home

    def load(self) -> dict[str, Any]:
        path = self._home.home() / "config.yaml"
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        try:
            import yaml  # type: ignore[import-untyped]
        except Exception:
            return _parse_simple_yaml(text)
        loaded = yaml.safe_load(text)
        return loaded if isinstance(loaded, dict) else {}


class StandaloneToolRegistry:
    """In-process tool registry for tests."""

    def __init__(self) -> None:
        self._tools: dict[str, tuple[ToolCallable, ToolCheck | None, Mapping[str, Any] | None]] = {}

    def register(
        self,
        name: str,
        fn: ToolCallable,
        check_fn: ToolCheck | None = None,
        *,
        schema: Mapping[str, Any] | None = None,
    ) -> None:
        self._tools[name] = (fn, check_fn, schema)

    def registered_tools(self) -> Mapping[str, ToolCallable]:
        return {name: entry[0] for name, entry in self._tools.items()}

    def call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        fn, check_fn, _schema = self._tools[name]
        if check_fn is not None and not check_fn():
            raise PermissionError(f"tool {name!r} is not currently available")
        return fn(*args, **kwargs)


class StandalonePromptInjector:
    """Builds a deterministic Available Wikis block from local directories."""

    def __init__(self, home: StandaloneHomeResolver) -> None:
        self._home = home

    def _visible_wiki_slugs(self) -> list[str]:
        wikis_dir = self._home.home() / "wikis"
        if not wikis_dir.exists():
            return []
        return sorted(path.name for path in wikis_dir.iterdir() if path.is_dir())

    def available_wikis_block(self, profile: str | None = None) -> str:
        from hermes_wiki.prompt import available_wikis_block

        return available_wikis_block(
            profile=profile,
            home_resolver=self._home,
            config=StandaloneConfigLoader(self._home).load(),
        )


class StandaloneKanbanReader:
    """Read-only in-memory Kanban adapter for tests."""

    def __init__(self, tasks: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        self._tasks: dict[str, dict[str, Any]] = {
            task_id: dict(task) for task_id, task in (tasks or {}).items()
        }

    def add_task(self, task_id: str, task: Mapping[str, Any]) -> None:
        self._tasks[task_id] = dict(task)

    def get_task(self, task_id: str) -> Mapping[str, Any] | None:
        task = self._tasks.get(task_id)
        return dict(task) if task is not None else None

    def list_tasks(
        self,
        *,
        status: str | None = None,
        assignee: str | None = None,
        limit: int | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        tasks = list(self._tasks.values())
        if status is not None:
            tasks = [task for task in tasks if task.get("status") == status]
        if assignee is not None:
            tasks = [task for task in tasks if task.get("assignee") == assignee]
        if limit is not None:
            tasks = tasks[:limit]
        return [dict(task) for task in tasks]


class StandaloneCronAdapter:
    """Local JSON-backed cron adapter used by tests."""

    def __init__(self, home: StandaloneHomeResolver) -> None:
        self._home = home

    @property
    def _store_path(self) -> Path:
        return self._home.home() / "cron" / "wiki_jobs.json"

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            loaded = json.loads(self._store_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        if not isinstance(loaded, dict):
            return {}
        return {str(key): value for key, value in loaded.items() if isinstance(value, dict)}

    def _save(self, jobs: Mapping[str, Mapping[str, Any]]) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        self._store_path.write_text(json.dumps(jobs, indent=2, sort_keys=True), encoding="utf-8")

    def reconcile(self, jobs: Sequence[MonitorJob]) -> CronReconcileResult:
        existing = self._load()
        desired = {
            job.name: {
                **asdict(job),
                "env": dict(job.env),
                "origin": dict(job.origin),
            }
            for job in jobs
        }
        created: list[str] = []
        updated: list[str] = []
        removed: list[str] = []
        unchanged: list[str] = []

        for name, desired_job in desired.items():
            current = existing.get(name)
            if current is None:
                created.append(name)
            elif current != desired_job:
                updated.append(name)
            else:
                unchanged.append(name)
        for name in existing:
            if name not in desired:
                removed.append(name)

        self._save(desired)
        return CronReconcileResult(
            created=created,
            updated=updated,
            removed=removed,
            unchanged=unchanged,
        )

    def list_jobs(self, *, include_disabled: bool = False) -> Sequence[Mapping[str, Any]]:
        jobs = list(self._load().values())
        if not include_disabled:
            jobs = [job for job in jobs if job.get("enabled", True)]
        return jobs


class StandaloneDashboardLoader:
    """Dashboard manifest seam for standalone tests."""

    def manifest(self) -> Mapping[str, Any]:
        return dict(WIKI_DASHBOARD_MANIFEST)

    def router(self) -> Any | None:
        return None


def create_adapters(env: Mapping[str, str] | None = None) -> AdapterSet:
    """Create the standalone adapter bundle."""

    home = StandaloneHomeResolver(env=env)
    return AdapterSet(
        name="standalone",
        home=home,
        config=StandaloneConfigLoader(home),
        tools=StandaloneToolRegistry(),
        prompts=StandalonePromptInjector(home),
        kanban=StandaloneKanbanReader(),
        cron=StandaloneCronAdapter(home),
        dashboard=StandaloneDashboardLoader(),
    )


__all__ = [
    "WIKI_DASHBOARD_MANIFEST",
    "StandaloneConfigLoader",
    "StandaloneCronAdapter",
    "StandaloneDashboardLoader",
    "StandaloneHomeResolver",
    "StandaloneKanbanReader",
    "StandalonePromptInjector",
    "StandaloneToolRegistry",
    "create_adapters",
]
