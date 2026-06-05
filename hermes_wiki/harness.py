"""Isolated Hermes harness used by integration and end-to-end validation.

All helpers in this module are intentionally scoped to the repository-local
``.hermes-test`` home. The live ``~/.hermes`` directory is a read-only source
for selected API keys only; dashboard lifecycle management is done only through
the PID recorded by this harness.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

REQUIRED_ENV_KEYS: tuple[str, ...] = (
    "OPENROUTER_API_KEY",
    "EXA_API_KEY",
    "TAVILY_API_KEY",
    "FIRECRAWL_API_KEY",
)
DASHBOARD_PORT = 9123
LIVE_DASHBOARD_PORT = 9119
MISSION_PORT_RANGE = range(9120, 9130)


@dataclass(frozen=True)
class IsolatedHomeSeedResult:
    """Result of creating and seeding the isolated Hermes home."""

    home: Path
    env_path: Path
    seeded_keys: list[str]
    missing_keys: list[str]


@dataclass(frozen=True)
class DashboardState:
    """Tracked dashboard process state."""

    pid: int
    port: int
    home: Path
    state_path: Path
    log_path: Path
    command: list[str]
    started_at: float


@dataclass(frozen=True)
class DashboardStopResult:
    """Result of stopping a tracked dashboard process."""

    pid: int | None
    port: int
    stopped: bool
    used_pid_file: bool
    message: str


def repo_root_from_module() -> Path:
    """Return the repository root containing this package."""

    return Path(__file__).resolve().parents[1]


def isolated_home(repo_root: Path | str | None = None) -> Path:
    """Return the repo-local isolated Hermes home path."""

    root = Path(repo_root) if repo_root is not None else repo_root_from_module()
    return root / ".hermes-test"


def _default_source_env() -> Path:
    return Path.home() / ".hermes" / ".env"


def _parse_env_file(path: Path) -> dict[str, str]:
    """Read dotenv-style key/value lines without expanding or logging values."""

    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return values

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].lstrip()
        key, separator, value = stripped.partition("=")
        key = key.strip()
        if separator and key in REQUIRED_ENV_KEYS and value:
            values[key] = value
    return values


def seed_isolated_home(
    *,
    repo_root: Path | str | None = None,
    home: Path | str | None = None,
    source_env: Path | str | None = None,
) -> IsolatedHomeSeedResult:
    """Create ``.hermes-test`` and seed its ``.env`` from the live env source.

    Only ``REQUIRED_ENV_KEYS`` are copied, and the source env file is never
    opened for writing.
    """

    target_home = Path(home) if home is not None else isolated_home(repo_root)
    env_source = Path(source_env) if source_env is not None else _default_source_env()
    target_home.mkdir(parents=True, exist_ok=True)

    parsed = _parse_env_file(env_source)
    seeded_keys = [key for key in REQUIRED_ENV_KEYS if parsed.get(key)]
    missing_keys = [key for key in REQUIRED_ENV_KEYS if key not in seeded_keys]
    env_lines = [f"{key}={parsed[key]}" for key in seeded_keys]

    env_path = target_home / ".env"
    tmp_path = env_path.with_name(f"{env_path.name}.tmp")
    tmp_path.write_text("\n".join(env_lines) + ("\n" if env_lines else ""), encoding="utf-8")
    tmp_path.chmod(0o600)
    tmp_path.replace(env_path)
    env_path.chmod(0o600)

    return IsolatedHomeSeedResult(
        home=target_home,
        env_path=env_path,
        seeded_keys=seeded_keys,
        missing_keys=missing_keys,
    )


def _validate_dashboard_port(port: int) -> None:
    if port == LIVE_DASHBOARD_PORT:
        raise ValueError(f"refusing to manage live Hermes dashboard port {LIVE_DASHBOARD_PORT}")
    if port not in MISSION_PORT_RANGE:
        raise ValueError(
            f"dashboard port {port} is outside the mission port range "
            f"{MISSION_PORT_RANGE.start}-{MISSION_PORT_RANGE.stop - 1}"
        )


def _state_path(home: Path, port: int) -> Path:
    return home / "run" / f"dashboard-{port}.json"


def _log_path(home: Path, port: int) -> Path:
    return home / "logs" / f"dashboard-{port}.log"


def _is_process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_command(pid: int) -> str:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _tcp_port_accepts_connections(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) == 0


def _load_dashboard_state(path: Path) -> DashboardState | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    try:
        return DashboardState(
            pid=int(raw["pid"]),
            port=int(raw["port"]),
            home=Path(raw["home"]),
            state_path=path,
            log_path=Path(raw["log_path"]),
            command=[str(part) for part in raw["command"]],
            started_at=float(raw["started_at"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _write_dashboard_state(state: DashboardState) -> None:
    state.state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(state)
    payload["home"] = str(state.home)
    payload["state_path"] = str(state.state_path)
    payload["log_path"] = str(state.log_path)
    state.state_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _wait_for_process_exit(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            waited_pid, _status = os.waitpid(pid, os.WNOHANG)
            if waited_pid == pid:
                return True
        except ChildProcessError:
            if not _is_process_running(pid):
                return True
        if not _is_process_running(pid):
            return True
        time.sleep(0.05)
    return False


def _assert_tracked_dashboard_process(state: DashboardState) -> None:
    command = _process_command(state.pid)
    if not command:
        return
    if "dashboard" not in command or "--port" not in command or str(state.port) not in command:
        raise RuntimeError(
            f"refusing to stop PID {state.pid}: command does not match tracked dashboard "
            f"on port {state.port}"
        )


def wait_for_dashboard(port: int = DASHBOARD_PORT, *, timeout: float = 30.0) -> bool:
    """Wait until the dashboard root responds on localhost."""

    _validate_dashboard_port(port)
    url = f"http://127.0.0.1:{port}/"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if 200 <= response.status < 500:
                    return True
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    return False


def launch_dashboard(
    *,
    home: Path | str | None = None,
    repo_root: Path | str | None = None,
    port: int = DASHBOARD_PORT,
    wait: bool = True,
    timeout: float = 30.0,
    extra_env: Mapping[str, str] | None = None,
) -> DashboardState:
    """Launch the isolated Hermes dashboard and record its PID.

    The exact dashboard command is:
    ``hermes dashboard --port 9123 --no-open --skip-build`` by default.
    """

    _validate_dashboard_port(port)
    target_home = Path(home) if home is not None else isolated_home(repo_root)
    target_home.mkdir(parents=True, exist_ok=True)
    state_file = _state_path(target_home, port)
    log_file = _log_path(target_home, port)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    existing = _load_dashboard_state(state_file)
    if existing is not None:
        if _is_process_running(existing.pid):
            return existing
        state_file.unlink(missing_ok=True)

    if _tcp_port_accepts_connections(port):
        raise RuntimeError(
            f"port {port} is already in use, but no tracked dashboard PID is running; "
            "refusing to interfere with an unknown process"
        )

    command = ["hermes", "dashboard", "--port", str(port), "--no-open", "--skip-build"]
    child_env = os.environ.copy()
    child_env["HERMES_HOME"] = str(target_home)
    if extra_env:
        child_env.update(extra_env)

    with log_file.open("ab") as log_handle:
        process = subprocess.Popen(
            command,
            cwd=repo_root_from_module(),
            env=child_env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=False,
        )

    state = DashboardState(
        pid=process.pid,
        port=port,
        home=target_home,
        state_path=state_file,
        log_path=log_file,
        command=command,
        started_at=time.time(),
    )
    _write_dashboard_state(state)

    if wait and not wait_for_dashboard(port, timeout=timeout):
        stop_dashboard(home=target_home, port=port, timeout=5.0)
        raise TimeoutError(f"dashboard on 127.0.0.1:{port} did not become healthy")
    return state


def stop_dashboard(
    *,
    home: Path | str | None = None,
    repo_root: Path | str | None = None,
    port: int = DASHBOARD_PORT,
    timeout: float = 10.0,
) -> DashboardStopResult:
    """Stop the isolated dashboard using only the PID recorded by the harness."""

    _validate_dashboard_port(port)
    target_home = Path(home) if home is not None else isolated_home(repo_root)
    state_file = _state_path(target_home, port)
    state = _load_dashboard_state(state_file)
    if state is None:
        state_file.unlink(missing_ok=True)
        return DashboardStopResult(
            pid=None,
            port=port,
            stopped=False,
            used_pid_file=False,
            message="no tracked dashboard PID",
        )

    if not _is_process_running(state.pid):
        state_file.unlink(missing_ok=True)
        return DashboardStopResult(
            pid=state.pid,
            port=port,
            stopped=False,
            used_pid_file=True,
            message="tracked dashboard PID was not running",
        )

    _assert_tracked_dashboard_process(state)
    os.kill(state.pid, signal.SIGTERM)
    stopped = _wait_for_process_exit(state.pid, timeout)
    if not stopped and _is_process_running(state.pid):
        os.kill(state.pid, signal.SIGKILL)
        stopped = _wait_for_process_exit(state.pid, 2.0)

    if stopped:
        state_file.unlink(missing_ok=True)
    return DashboardStopResult(
        pid=state.pid,
        port=port,
        stopped=stopped,
        used_pid_file=True,
        message="stopped tracked dashboard PID" if stopped else "dashboard PID did not exit",
    )


def _cmd_init(args: argparse.Namespace) -> int:
    result = seed_isolated_home(repo_root=args.repo_root, source_env=args.source_env)
    print(f"[harness] isolated HERMES_HOME={result.home}")
    for key in result.seeded_keys:
        print(f"[harness] seeded {key} into isolated .env")
    for key in result.missing_keys:
        print(f"[harness] WARNING: {key} missing from source env")
    return 0


def _cmd_dashboard_start(args: argparse.Namespace) -> int:
    state = launch_dashboard(
        repo_root=args.repo_root,
        port=args.port,
        wait=not args.no_wait,
        timeout=args.timeout,
    )
    print(f"[harness] dashboard pid={state.pid} port={state.port} home={state.home}")
    return 0


def _cmd_dashboard_stop(args: argparse.Namespace) -> int:
    result = stop_dashboard(repo_root=args.repo_root, port=args.port, timeout=args.timeout)
    print(f"[harness] {result.message}")
    return 0 if result.stopped or not result.used_pid_file else 1


def _cmd_dashboard_status(args: argparse.Namespace) -> int:
    home = isolated_home(args.repo_root)
    state = _load_dashboard_state(_state_path(home, args.port))
    if state is None:
        print("[harness] dashboard not tracked")
        return 1
    running = _is_process_running(state.pid)
    healthy = wait_for_dashboard(args.port, timeout=0.5) if running else False
    print(
        json.dumps(
            {
                "pid": state.pid,
                "port": state.port,
                "home": str(state.home),
                "running": running,
                "healthy": healthy,
                "state_path": str(state.state_path),
                "log_path": str(state.log_path),
            },
            sort_keys=True,
        )
    )
    return 0 if running else 1


def build_parser() -> argparse.ArgumentParser:
    """Build the harness CLI parser."""

    parser = argparse.ArgumentParser(prog="python -m hermes_wiki.harness")
    parser.add_argument("--repo-root", type=Path, default=repo_root_from_module())
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="create and seed the isolated Hermes home")
    init_parser.add_argument("--source-env", type=Path, default=_default_source_env())
    init_parser.set_defaults(func=_cmd_init)

    dashboard = subparsers.add_parser("dashboard", help="manage the isolated dashboard")
    dashboard_subparsers = dashboard.add_subparsers(dest="dashboard_command", required=True)

    start = dashboard_subparsers.add_parser("start", help="launch the isolated dashboard")
    start.add_argument("--port", type=int, default=DASHBOARD_PORT)
    start.add_argument("--timeout", type=float, default=30.0)
    start.add_argument("--no-wait", action="store_true")
    start.set_defaults(func=_cmd_dashboard_start)

    stop = dashboard_subparsers.add_parser("stop", help="stop the tracked dashboard PID")
    stop.add_argument("--port", type=int, default=DASHBOARD_PORT)
    stop.add_argument("--timeout", type=float, default=10.0)
    stop.set_defaults(func=_cmd_dashboard_stop)

    status = dashboard_subparsers.add_parser("status", help="show tracked dashboard status")
    status.add_argument("--port", type=int, default=DASHBOARD_PORT)
    status.set_defaults(func=_cmd_dashboard_status)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the harness CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)
    func = args.func
    if not callable(func):
        parser.error("missing command")
    return int(func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
