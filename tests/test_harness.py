"""Tests for the isolated Hermes validation harness."""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

import pytest

from hermes_wiki.harness import launch_dashboard, seed_isolated_home, stop_dashboard


def test_seed_isolated_home_copies_only_required_keys_without_touching_live_env(tmp_path) -> None:
    """The harness seeds a repo-local home from a read-only source env."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    live_env = tmp_path / "live.env"
    live_env.write_text(
        "\n".join(
            [
                "OPENROUTER_API_KEY=openrouter-secret",
                "EXA_API_KEY=exa-secret",
                "TAVILY_API_KEY=tavily-secret",
                "FIRECRAWL_API_KEY=firecrawl-secret",
                "ANTHROPIC_API_KEY=must-not-copy",
                "UNRELATED=value",
                "",
            ]
        ),
        encoding="utf-8",
    )
    before = live_env.read_bytes()

    result = seed_isolated_home(repo_root=repo_root, source_env=live_env)

    assert result.home == repo_root / ".hermes-test"
    assert result.env_path == repo_root / ".hermes-test" / ".env"
    assert live_env.read_bytes() == before
    assert result.seeded_keys == [
        "OPENROUTER_API_KEY",
        "EXA_API_KEY",
        "TAVILY_API_KEY",
        "FIRECRAWL_API_KEY",
    ]
    assert result.env_path.read_text(encoding="utf-8").splitlines() == [
        "OPENROUTER_API_KEY=openrouter-secret",
        "EXA_API_KEY=exa-secret",
        "TAVILY_API_KEY=tavily-secret",
        "FIRECRAWL_API_KEY=firecrawl-secret",
    ]


def test_dashboard_helper_launches_expected_command_and_stops_by_tracked_pid(
    tmp_path, monkeypatch
) -> None:
    """Dashboard launch/stop uses the isolated home and the stored PID, not --stop."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_log = tmp_path / "fake-hermes.json"
    fake_hermes = fake_bin / "hermes"
    fake_hermes.write_text(
        """#!/usr/bin/env python3
import json
import os
import signal
import sys
import time

with open(os.environ["FAKE_HERMES_LOG"], "w", encoding="utf-8") as handle:
    json.dump({"argv": sys.argv[1:], "home": os.environ.get("HERMES_HOME")}, handle)

signal.signal(signal.SIGTERM, lambda _signum, _frame: sys.exit(0))
while True:
    time.sleep(0.1)
""",
        encoding="utf-8",
    )
    fake_hermes.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_HERMES_LOG", str(fake_log))

    home = tmp_path / ".hermes-test"
    home.mkdir()
    port = 9124
    state = launch_dashboard(home=home, port=port, wait=False)
    try:
        deadline = time.monotonic() + 3
        while not fake_log.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert fake_log.exists()

        payload = json.loads(fake_log.read_text(encoding="utf-8"))
        assert payload == {
            "argv": ["dashboard", "--port", str(port), "--no-open", "--skip-build"],
            "home": str(home),
        }
        assert state.pid > 0
        assert state.state_path.exists()

        stopped = stop_dashboard(home=home, port=port, timeout=3)

        assert stopped.stopped is True
        assert stopped.pid == state.pid
        assert stopped.used_pid_file is True
        assert not state.state_path.exists()
        with pytest.raises(ProcessLookupError):
            os.kill(state.pid, 0)
    finally:
        try:
            os.kill(state.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def test_dashboard_helpers_refuse_live_dashboard_port(tmp_path: Path) -> None:
    """The harness must never manage the live Hermes dashboard port."""
    with pytest.raises(ValueError, match="9119"):
        launch_dashboard(home=tmp_path, port=9119, wait=False)

    with pytest.raises(ValueError, match="9119"):
        stop_dashboard(home=tmp_path, port=9119)
