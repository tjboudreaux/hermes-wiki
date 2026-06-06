"""Hermes hook integration for the Wiki memory companion.

Registers lifecycle hooks that connect the MemoryCompanion to the Hermes
agent runtime. These hooks fire alongside (not instead of) any active
MemoryProvider.

Hooks registered:
- on_memory_write: observes built-in memory writes
- on_turn_start: triggers wiki prefetch for context injection
- on_session_end: proposes wiki writes from accumulated observations

Tool registration:
- wiki_propose, wiki_recall, wiki_list_proposals, wiki_commit_proposal
"""

from __future__ import annotations

import logging
from typing import Any

from hermes_wiki.memory_companion import (
    CompanionConfig,
    MemoryCompanion,
    get_companion_tool_schemas,
    handle_wiki_commit_proposal,
    handle_wiki_list_proposals,
    handle_wiki_propose,
    handle_wiki_recall,
    load_config,
)

logger = logging.getLogger(__name__)

_companion: MemoryCompanion | None = None


def get_companion(config: CompanionConfig | None = None) -> MemoryCompanion:
    """Return the singleton MemoryCompanion instance."""
    global _companion
    if _companion is None:
        _companion = MemoryCompanion(config=config)
    return _companion


def reset_companion() -> None:
    """Reset the singleton (for testing)."""
    global _companion
    _companion = None


def register_hooks(ctx: Any) -> None:
    """Register memory companion hooks on a Hermes PluginContext.

    Called from the entry-point plugin's register(ctx) when the companion
    is enabled in config.
    """
    get_companion()

    ctx.register_hook("on_memory_write", _hook_on_memory_write)
    logger.debug("Wiki memory companion: registered on_memory_write hook")


def register_tools(ctx: Any, companion: MemoryCompanion | None = None) -> None:
    """Register conversational trigger tools on a Hermes PluginContext."""
    comp = companion or get_companion()

    schemas = get_companion_tool_schemas()
    handlers = {
        "wiki_propose": lambda args, **kw: handle_wiki_propose(comp, args),
        "wiki_recall": lambda args, **kw: handle_wiki_recall(comp, args),
        "wiki_list_proposals": lambda args, **kw: handle_wiki_list_proposals(comp, args),
        "wiki_commit_proposal": lambda args, **kw: handle_wiki_commit_proposal(comp, args),
    }

    for schema in schemas:
        name = schema["name"]
        handler = handlers.get(name)
        if handler is None:
            continue
        try:
            ctx.register_tool(
                name=name,
                handler=handler,
                schema=schema,
                toolset="wiki",
            )
            logger.debug("Wiki memory companion: registered tool %s", name)
        except Exception as exc:
            logger.debug("Wiki memory companion: failed to register tool %s: %s", name, exc)


def _hook_on_memory_write(
    action: str,
    target: str,
    content: str,
    metadata: dict[str, Any] | None = None,
    **kwargs: Any,
) -> None:
    """Hook callback for on_memory_write events."""
    companion = get_companion()
    companion.on_memory_write(action, target, content, metadata)


def initialize_companion(config_dict: dict[str, Any] | None = None) -> MemoryCompanion:
    """Initialize the companion from a raw config dictionary.

    Call this during plugin registration to configure and activate
    the companion if enabled.
    """
    cfg = load_config(config_dict)
    if not cfg.enabled:
        logger.debug("Wiki memory companion: disabled in config")
        return get_companion(config=cfg)

    companion = get_companion(config=cfg)
    logger.info("Wiki memory companion: enabled (prefetch=%s, observe=%s, auto_propose=%s)",
                cfg.prefetch, cfg.observe_writes, cfg.auto_propose)
    return companion


__all__ = [
    "get_companion",
    "initialize_companion",
    "register_hooks",
    "register_tools",
    "reset_companion",
]
