"""Standalone adapter implementations for local tests and isolated runs."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
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

    def __init__(
        self,
        tasks: Mapping[str, Mapping[str, Any]] | None = None,
        home: StandaloneHomeResolver | None = None,
    ) -> None:
        self._home = home
        self._tasks: dict[str, dict[str, Any]] = {
            task_id: dict(task) for task_id, task in (tasks or {}).items()
        }

    def add_task(self, task_id: str, task: Mapping[str, Any]) -> None:
        self._tasks[task_id] = dict(task)

    def get_task(self, task_id: str) -> Mapping[str, Any] | None:
        task = self._tasks.get(task_id)
        if task is not None:
            return dict(task)
        task = self._json_task(task_id)
        if task is not None:
            return task
        return self._sqlite_task(task_id)

    def list_tasks(
        self,
        *,
        status: str | None = None,
        assignee: str | None = None,
        limit: int | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        tasks = list(self._tasks.values()) + list(self._json_tasks().values())
        if status is not None:
            tasks = [task for task in tasks if task.get("status") == status]
        if assignee is not None:
            tasks = [task for task in tasks if task.get("assignee") == assignee]
        if limit is not None:
            tasks = tasks[:limit]
        return [dict(task) for task in tasks]

    def _json_tasks(self) -> dict[str, dict[str, Any]]:
        if self._home is None:
            return {}
        path = self._home.home() / "kanban_tasks.json"
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        if not isinstance(loaded, dict):
            raise RuntimeError(f"invalid kanban task fixture: {path}")
        tasks: dict[str, dict[str, Any]] = {}
        for key, value in loaded.items():
            if not isinstance(value, Mapping):
                continue
            task_id = str(value.get("id") or value.get("task_id") or key)
            tasks[task_id] = {"id": task_id, **dict(value)}
        return tasks

    def _json_task(self, task_id: str) -> Mapping[str, Any] | None:
        return self._json_tasks().get(task_id)

    def _sqlite_task(self, task_id: str) -> Mapping[str, Any] | None:
        if self._home is None:
            return None
        path = self._home.home() / "kanban.db"
        if not path.exists():
            return None
        uri = f"file:{path.as_posix()}?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            return None
        return None if row is None else dict(row)


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

    @staticmethod
    def _origin(job: MonitorJob) -> dict[str, Any]:
        return {
            "source": "hermes-wiki",
            **dict(job.origin),
        }

    @staticmethod
    def _is_wiki_owned(job: Mapping[str, Any], *, owner_prefix: str | None) -> bool:
        name = job.get("name")
        origin = job.get("origin")
        if not isinstance(name, str) or not isinstance(origin, Mapping):
            return False
        if origin.get("source") != "hermes-wiki":
            return False
        return owner_prefix is None or name.startswith(owner_prefix)

    def _job_record(self, job: MonitorJob) -> dict[str, Any]:
        parsed = _parse_standalone_schedule(job.schedule)
        return {
            **asdict(job),
            "skills": [str(skill) for skill in job.skills],
            "env": dict(job.env),
            "origin": self._origin(job),
            "schedule_display": parsed["display"],
            "parsed_schedule": parsed,
            "next_run_at": _compute_standalone_next_run(parsed),
        }

    def reconcile(
        self,
        jobs: Sequence[MonitorJob],
        *,
        owner_prefix: str | None = None,
    ) -> CronReconcileResult:
        existing = self._load()
        desired: dict[str, dict[str, Any]] = {}
        created: list[str] = []
        updated: list[str] = []
        removed: list[str] = []
        unchanged: list[str] = []
        failed: list[str] = []
        errors: list[str] = []

        for job in jobs:
            try:
                desired[job.name] = self._job_record(job)
            except ValueError as exc:
                failed.append(job.name)
                errors.append(f"invalid schedule for {job.name}: {exc}")

        next_jobs: dict[str, dict[str, Any]] = {name: dict(job) for name, job in existing.items()}

        for name, desired_job in desired.items():
            current = existing.get(name)
            if current is None:
                next_jobs[name] = desired_job
                created.append(name)
            elif not self._is_wiki_owned(current, owner_prefix=owner_prefix):
                failed.append(name)
                errors.append(f"collision: {name}")
            elif current != desired_job:
                next_jobs[name] = desired_job
                updated.append(name)
            else:
                unchanged.append(name)

        for name, current in existing.items():
            if (
                name not in desired
                and self._is_wiki_owned(current, owner_prefix=owner_prefix)
            ):
                next_jobs.pop(name, None)
                removed.append(name)

        self._save(next_jobs)
        return CronReconcileResult(
            created=created,
            updated=updated,
            removed=removed,
            unchanged=unchanged,
            failed=failed,
            errors=errors,
        )

    def list_jobs(self, *, include_disabled: bool = False) -> Sequence[Mapping[str, Any]]:
        jobs = list(self._load().values())
        if not include_disabled:
            jobs = [job for job in jobs if job.get("enabled", True)]
        return jobs


def _parse_standalone_schedule(schedule: str) -> dict[str, str]:
    parts = str(schedule).strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid schedule {schedule!r}; expected five cron fields")
    minute, hour, day_of_month, month, day_of_week = parts
    _validate_cron_field(minute, minimum=0, maximum=59, field="minute")
    _validate_cron_field(hour, minimum=0, maximum=23, field="hour")
    _validate_cron_field(day_of_month, minimum=1, maximum=31, field="day_of_month")
    _validate_cron_field(month, minimum=1, maximum=12, field="month")
    _validate_cron_field(day_of_week, minimum=0, maximum=7, field="day_of_week")
    return {
        "kind": "cron",
        "minute": minute,
        "hour": hour,
        "day_of_month": day_of_month,
        "month": month,
        "day_of_week": day_of_week,
        "display": " ".join(parts),
    }


def _validate_cron_field(value: str, *, minimum: int, maximum: int, field: str) -> None:
    for part in value.split(","):
        base = part
        if "/" in base:
            base, step = base.split("/", 1)
            if not step.isdigit() or int(step) <= 0:
                raise ValueError(f"{field} has invalid step {part!r}")
        if base == "*":
            continue
        if "-" in base:
            start, end = base.split("-", 1)
            if not start.isdigit() or not end.isdigit():
                raise ValueError(f"{field} has invalid range {part!r}")
            if not (minimum <= int(start) <= int(end) <= maximum):
                raise ValueError(f"{field} range {part!r} is out of bounds")
            continue
        if not base.isdigit() or not (minimum <= int(base) <= maximum):
            raise ValueError(f"{field} value {part!r} is out of bounds")


def _compute_standalone_next_run(parsed: Mapping[str, str]) -> str | None:
    minute = parsed.get("minute")
    hour = parsed.get("hour")
    if not (minute and hour and minute.isdigit() and hour.isdigit()):
        return None
    day_of_week = parsed.get("day_of_week") or "*"
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    candidate = now + timedelta(minutes=1)
    for _ in range(60 * 24 * 366):
        if (
            candidate.minute == int(minute)
            and candidate.hour == int(hour)
            and _cron_day_matches(candidate, day_of_week)
        ):
            return candidate.isoformat().replace("+00:00", "Z")
        candidate += timedelta(minutes=1)
    return None


def _cron_day_matches(candidate: datetime, day_of_week: str) -> bool:
    if day_of_week == "*":
        return True
    cron_weekday = (candidate.weekday() + 1) % 7
    for part in day_of_week.split(","):
        if part.isdigit():
            value = int(part)
            if value == 7:
                value = 0
            if cron_weekday == value:
                return True
    return False


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
        kanban=StandaloneKanbanReader(home=home),
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
