"""Core package for the Hermes Wiki Plugin."""

from __future__ import annotations

try:
    from importlib.metadata import version
except ImportError:  # pragma: no cover - Python 3.11+ always has importlib.metadata
    __version__ = "0.11.0"
else:
    try:
        __version__ = version("hermes-wiki")
    except Exception:  # pragma: no cover - importable before installation
        __version__ = "0.0.0"

__all__ = ["__version__"]
