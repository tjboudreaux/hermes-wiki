"""Tests for runtime adapter selection."""

from __future__ import annotations

import subprocess
import sys

from adapters.base import create_adapters, select_adapter_name


def test_adapter_selection_defaults_to_standalone(monkeypatch) -> None:
    """Tests and default runs use standalone unless env/config requests otherwise."""
    monkeypatch.delenv("HERMES_WIKI_ADAPTER", raising=False)

    assert select_adapter_name() == "standalone"
    assert create_adapters().name == "standalone"


def test_adapter_selection_supports_env_and_config(monkeypatch) -> None:
    """Env selection wins over config; config can select Hermes when env is absent."""
    monkeypatch.setenv("HERMES_WIKI_ADAPTER", "hermes")
    assert select_adapter_name({"wiki": {"adapter": "standalone"}}) == "hermes"

    monkeypatch.delenv("HERMES_WIKI_ADAPTER")
    assert select_adapter_name({"wiki": {"adapter": "hermes"}}) == "hermes"
    assert select_adapter_name({"hermes_wiki": {"adapter": "standalone"}}) == "standalone"


def test_default_adapter_creation_does_not_import_hermes_modules() -> None:
    """Creating the default adapter set has no installed-Hermes import side effect."""
    code = (
        "from adapters.base import create_adapters; "
        "adapters = create_adapters(); "
        "import sys; "
        "assert adapters.name == 'standalone'; "
        "assert 'hermes_cli.config' not in sys.modules; "
        "assert 'cron.jobs' not in sys.modules"
    )
    result = subprocess.run([sys.executable, "-c", code], check=False, text=True)

    assert result.returncode == 0
