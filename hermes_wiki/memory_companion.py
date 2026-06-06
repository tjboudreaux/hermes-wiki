"""Memory companion — lightweight hook-based integration with Hermes memory.

This module provides a non-exclusive companion layer that:
1. Observes built-in memory writes (MEMORY.md/USER.md) and offers them as
   potential wiki source material
2. Enriches agent context with wiki recall before each turn (prefetch)
3. Exposes conversational trigger tools that let agents propose wiki writes
   from conversation context

It does NOT implement the full MemoryProvider ABC — wikis complement memory
providers rather than replacing them. Only one MemoryProvider can be active,
but the companion hooks can run alongside any provider.

Configuration lives in ``config.yaml`` under the ``wiki.memory`` key:

  wiki:
    memory:
      enabled: true
      prefetch: true
      prefetch_limit: 3
      observe_writes: true
      auto_propose: false
      proposal_threshold: 0.7
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from hermes_wiki.search import search_wiki

logger = logging.getLogger(__name__)

_DEFAULT_PREFETCH_LIMIT = 3
_DEFAULT_PROPOSAL_THRESHOLD = 0.7


@dataclass(frozen=True, slots=True)
class CompanionConfig:
    """Parsed memory companion configuration."""

    enabled: bool = False
    prefetch: bool = True
    prefetch_limit: int = _DEFAULT_PREFETCH_LIMIT
    observe_writes: bool = True
    auto_propose: bool = False
    proposal_threshold: float = _DEFAULT_PROPOSAL_THRESHOLD


@dataclass(slots=True)
class WriteObservation:
    """A built-in memory write observed by the companion."""

    action: str
    target: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    proposed: bool = False


@dataclass(frozen=True, slots=True)
class WikiProposal:
    """A proposed wiki write generated from conversation context."""

    title: str
    body: str
    page_type: str = "concept"
    tags: tuple[str, ...] = ()
    source_context: str = ""
    confidence: float = 0.0


def load_config(config: Mapping[str, Any] | None = None) -> CompanionConfig:
    """Load companion configuration from a config dictionary.

    Reads from ``wiki.memory`` or ``hermes_wiki.memory`` sections.
    """
    if not config:
        return CompanionConfig()

    memory_section: Mapping[str, Any] | None = None
    for parent_key in ("wiki", "hermes_wiki"):
        parent = config.get(parent_key)
        if isinstance(parent, Mapping):
            section = parent.get("memory")
            if isinstance(section, Mapping):
                memory_section = section
                break

    if memory_section is None:
        return CompanionConfig()

    return CompanionConfig(
        enabled=bool(memory_section.get("enabled", False)),
        prefetch=bool(memory_section.get("prefetch", True)),
        prefetch_limit=int(memory_section.get("prefetch_limit", _DEFAULT_PREFETCH_LIMIT)),
        observe_writes=bool(memory_section.get("observe_writes", True)),
        auto_propose=bool(memory_section.get("auto_propose", False)),
        proposal_threshold=float(
            memory_section.get("proposal_threshold", _DEFAULT_PROPOSAL_THRESHOLD)
        ),
    )


class MemoryCompanion:
    """Hook-based companion that bridges Hermes memory and Wiki.

    Instantiated once per session (or per agent lifetime). Collects write
    observations and produces wiki-relevant context for prefetch.
    """

    def __init__(self, config: CompanionConfig | None = None) -> None:
        self._config = config or CompanionConfig()
        self._observations: list[WriteObservation] = []
        self._proposals: list[WikiProposal] = []

    @property
    def config(self) -> CompanionConfig:
        return self._config

    @property
    def observations(self) -> list[WriteObservation]:
        return list(self._observations)

    @property
    def proposals(self) -> list[WikiProposal]:
        return list(self._proposals)

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> WriteObservation | None:
        """Observe a built-in memory write (MEMORY.md/USER.md).

        Returns the observation if recording is enabled, None otherwise.
        """
        if not self._config.enabled or not self._config.observe_writes:
            return None

        observation = WriteObservation(
            action=action,
            target=target,
            content=content,
            metadata=metadata or {},
        )
        self._observations.append(observation)
        logger.debug(
            "Memory companion observed write: action=%s target=%s len=%d",
            action,
            target,
            len(content),
        )
        return observation

    def prefetch(self, query: str, *, wiki: str | None = None) -> str:
        """Return wiki-relevant context for the current turn.

        Searches visible wikis using BM25 and returns a formatted context
        block suitable for system prompt injection.
        """
        if not self._config.enabled or not self._config.prefetch:
            return ""

        if not query or not query.strip():
            return ""

        try:
            results = search_wiki(query, wiki=wiki, limit=self._config.prefetch_limit)
        except Exception as exc:
            logger.debug("Memory companion prefetch failed: %s", exc)
            return ""

        if not results:
            return ""

        lines = ["# Wiki Context (auto-recalled)"]
        for row in results:
            title = row.get("title", "")
            page_id = row.get("id", "")
            snippet = row.get("context") or row.get("snippet") or ""
            lines.append(f"- **{title}** (`{page_id}`): {snippet}")
        return "\n".join(lines)

    def propose_write(
        self,
        title: str,
        body: str,
        *,
        page_type: str = "concept",
        tags: tuple[str, ...] | list[str] = (),
        source_context: str = "",
        confidence: float = 0.0,
    ) -> WikiProposal:
        """Create a wiki write proposal from conversation context.

        The proposal is stored but not executed — the agent or user must
        confirm it via the ``wiki_propose`` tool or explicit ingest.
        """
        proposal = WikiProposal(
            title=title,
            body=body,
            page_type=page_type,
            tags=tuple(tags),
            source_context=source_context,
            confidence=confidence,
        )
        self._proposals.append(proposal)
        logger.debug(
            "Memory companion proposal: title=%r type=%s confidence=%.2f",
            title,
            page_type,
            confidence,
        )
        return proposal

    def pending_proposals(
        self,
        *,
        min_confidence: float | None = None,
    ) -> list[WikiProposal]:
        """Return proposals above the confidence threshold."""
        threshold = (
            min_confidence if min_confidence is not None else self._config.proposal_threshold
        )
        return [p for p in self._proposals if p.confidence >= threshold]

    def clear_proposals(self) -> int:
        """Clear all pending proposals. Returns the count cleared."""
        count = len(self._proposals)
        self._proposals.clear()
        return count

    def clear_observations(self) -> int:
        """Clear all observations. Returns the count cleared."""
        count = len(self._observations)
        self._observations.clear()
        return count


# ---------------------------------------------------------------------------
# Conversational trigger tool schemas
# ---------------------------------------------------------------------------

WIKI_PROPOSE_SCHEMA: dict[str, Any] = {
    "name": "wiki_propose",
    "description": (
        "Propose a new wiki page or update from the current conversation context. "
        "The proposal is queued for review — it does NOT immediately write. "
        "Use when you learn something that should be captured as durable knowledge "
        "in the wiki rather than ephemeral session memory."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Proposed page title",
            },
            "body": {
                "type": "string",
                "description": "Proposed page content (markdown)",
            },
            "page_type": {
                "type": "string",
                "enum": ["concept", "entity", "comparison", "howto", "reference"],
                "description": "Wiki page type classification",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tags for categorization",
            },
            "source_context": {
                "type": "string",
                "description": "The conversation excerpt that triggered this proposal",
            },
            "confidence": {
                "type": "number",
                "description": "How confident this should become a wiki page (0-1)",
            },
        },
        "required": ["title", "body"],
    },
}

WIKI_RECALL_SCHEMA: dict[str, Any] = {
    "name": "wiki_recall",
    "description": (
        "Recall relevant wiki knowledge for the current conversation topic. "
        "Use proactively when you suspect the wiki has relevant domain knowledge "
        "that would improve your response. Lighter than wiki_search — optimized "
        "for conversational context injection."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to recall from the wiki",
            },
            "wiki": {
                "type": "string",
                "description": "Specific wiki to search (optional, searches all visible)",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum results (default: 3)",
            },
        },
        "required": ["query"],
    },
}

WIKI_COMMIT_PROPOSAL_SCHEMA: dict[str, Any] = {
    "name": "wiki_commit_proposal",
    "description": (
        "Commit a previously proposed wiki page, writing it to the wiki. "
        "Only call after the user has confirmed the proposal should be persisted. "
        "Pass the proposal index from wiki_list_proposals."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "index": {
                "type": "integer",
                "description": "Proposal index (0-based) from wiki_list_proposals",
            },
            "wiki": {
                "type": "string",
                "description": "Target wiki slug (uses current if omitted)",
            },
        },
        "required": ["index"],
    },
}

WIKI_LIST_PROPOSALS_SCHEMA: dict[str, Any] = {
    "name": "wiki_list_proposals",
    "description": (
        "List pending wiki write proposals that were generated during this session. "
        "Show these to the user for review before committing."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


def get_companion_tool_schemas() -> list[dict[str, Any]]:
    """Return all conversational trigger tool schemas."""
    return [
        WIKI_PROPOSE_SCHEMA,
        WIKI_RECALL_SCHEMA,
        WIKI_COMMIT_PROPOSAL_SCHEMA,
        WIKI_LIST_PROPOSALS_SCHEMA,
    ]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def handle_wiki_propose(companion: MemoryCompanion, args: dict[str, Any]) -> str:
    """Handle the wiki_propose tool call."""
    proposal = companion.propose_write(
        title=str(args.get("title") or ""),
        body=str(args.get("body") or ""),
        page_type=str(args.get("page_type") or "concept"),
        tags=tuple(args.get("tags") or []),
        source_context=str(args.get("source_context") or ""),
        confidence=float(args.get("confidence") or 0.5),
    )
    return json.dumps({
        "status": "proposed",
        "title": proposal.title,
        "page_type": proposal.page_type,
        "confidence": proposal.confidence,
        "message": (
            "Proposal queued. Use wiki_list_proposals to review, "
            "wiki_commit_proposal to persist."
        ),
    })


def handle_wiki_recall(companion: MemoryCompanion, args: dict[str, Any]) -> str:
    """Handle the wiki_recall tool call."""
    query = str(args.get("query") or "")
    wiki = args.get("wiki")

    if not query.strip():
        return json.dumps({"error": "query is required"})

    context = companion.prefetch(query, wiki=wiki)
    if not context:
        return json.dumps({"results": [], "message": "No relevant wiki knowledge found."})

    return json.dumps({"context": context, "query": query})


def handle_wiki_list_proposals(companion: MemoryCompanion, args: dict[str, Any]) -> str:
    """Handle the wiki_list_proposals tool call."""
    del args
    proposals = companion.proposals
    if not proposals:
        return json.dumps({"proposals": [], "message": "No pending proposals."})

    items = []
    for i, p in enumerate(proposals):
        items.append({
            "index": i,
            "title": p.title,
            "page_type": p.page_type,
            "confidence": p.confidence,
            "tags": list(p.tags),
            "body_preview": p.body[:200] + ("..." if len(p.body) > 200 else ""),
        })
    return json.dumps({"proposals": items, "count": len(items)})


def handle_wiki_commit_proposal(
    companion: MemoryCompanion,
    args: dict[str, Any],
) -> str:
    """Handle the wiki_commit_proposal tool call.

    Writes the proposal to the wiki via the standard create_page path.
    """
    index = int(args.get("index", -1))
    wiki = args.get("wiki")

    proposals = companion.proposals
    if index < 0 or index >= len(proposals):
        return json.dumps({"error": f"Invalid proposal index {index}. Have {len(proposals)}."})

    proposal = proposals[index]

    from hermes_wiki.tools import wiki_create_page

    result = wiki_create_page(
        title=proposal.title,
        body=proposal.body,
        type=proposal.page_type,
        tags=list(proposal.tags),
        sources=[],
        wiki=wiki,
    )

    companion._proposals.pop(index)

    if isinstance(result, str):
        return result
    return json.dumps({
        "status": "committed",
        "title": proposal.title,
        "result": result,
    })


__all__ = [
    "CompanionConfig",
    "MemoryCompanion",
    "WikiProposal",
    "WriteObservation",
    "get_companion_tool_schemas",
    "handle_wiki_commit_proposal",
    "handle_wiki_list_proposals",
    "handle_wiki_propose",
    "handle_wiki_recall",
    "load_config",
]
