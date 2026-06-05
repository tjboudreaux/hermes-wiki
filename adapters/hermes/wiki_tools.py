"""Hermes tool-glob entrypoint for the Wiki tool surface.

Installed Hermes discovers agent tools by importing modules that contain
top-level ``registry.register(...)`` calls. This adapter module keeps that
Hermes-specific shape out of ``hermes_wiki/`` while delegating behavior to the
core tool functions.
"""

from __future__ import annotations

import json
from typing import Any

from adapters.hermes import _import_hermes_module
from hermes_wiki import tools as wiki_tools

registry: Any = _import_hermes_module("tools.registry").registry


def _result(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _handle_wiki_list(args: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _result(wiki_tools.wiki_list(wiki=args.get("wiki")))


def _handle_wiki_search(args: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _result(
        wiki_tools.wiki_search(
            str(args.get("query") or ""),
            wiki=args.get("wiki"),
            limit=int(args.get("limit") or 5),
        )
    )


def _handle_wiki_show(args: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _result(wiki_tools.wiki_show(str(args.get("page_id") or ""), wiki=args.get("wiki")))


def _handle_wiki_health_check(args: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _result(wiki_tools.wiki_health_check(wiki=args.get("wiki")))


def _handle_wiki_inbox(args: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _result(wiki_tools.wiki_inbox(wiki=args.get("wiki")))


def _handle_wiki_ingest(args: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _result(
        wiki_tools.wiki_ingest(
            args.get("path_or_url"),
            wiki=args.get("wiki"),
            classifier=args.get("classifier"),
            inbox=bool(args.get("inbox") or False),
        )
    )


def _handle_wiki_create_page(args: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _result(
        wiki_tools.wiki_create_page(
            title=str(args.get("title") or ""),
            body=str(args.get("body") or ""),
            type=str(args.get("type") or "concept"),
            tags=args.get("tags") if isinstance(args.get("tags"), list) else [],
            sources=args.get("sources") if isinstance(args.get("sources"), list) else [],
            wiki=args.get("wiki"),
        )
    )


def _handle_wiki_link_kanban(args: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    return _result(
        wiki_tools.wiki_link_kanban(
            page_id=str(args.get("page_id") or ""),
            task_id=str(args.get("task_id") or ""),
            wiki=args.get("wiki"),
        )
    )


_WIKI_LIST_SCHEMA = {
    "name": "wiki_list",
    "description": "List visible Wikis, or pages in one visible Wiki.",
    "parameters": {
        "type": "object",
        "properties": {"wiki": {"type": "string"}},
        "required": [],
    },
}
_WIKI_SEARCH_SCHEMA = {
    "name": "wiki_search",
    "description": "Search visible Hermes Wikis with BM25 ranking.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "wiki": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["query"],
    },
}
_WIKI_SHOW_SCHEMA = {
    "name": "wiki_show",
    "description": "Show a Wiki Page with frontmatter and linked kanban refs.",
    "parameters": {
        "type": "object",
        "properties": {"page_id": {"type": "string"}, "wiki": {"type": "string"}},
        "required": ["page_id"],
    },
}
_WIKI_HEALTH_SCHEMA = {
    "name": "wiki_health_check",
    "description": "Return a structured Wiki health/lint report.",
    "parameters": {
        "type": "object",
        "properties": {"wiki": {"type": "string"}},
        "required": [],
    },
}
_WIKI_INBOX_SCHEMA = {
    "name": "wiki_inbox",
    "description": "List unprocessed inbox files with classifier suggestions.",
    "parameters": {
        "type": "object",
        "properties": {"wiki": {"type": "string"}},
        "required": [],
    },
}
_WIKI_INGEST_SCHEMA = {
    "name": "wiki_ingest",
    "description": "Ingest one source or explicitly process a Wiki inbox.",
    "parameters": {
        "type": "object",
        "properties": {
            "path_or_url": {"type": "string"},
            "wiki": {"type": "string"},
            "classifier": {"type": "string"},
            "inbox": {"type": "boolean"},
        },
        "required": [],
    },
}
_WIKI_CREATE_PAGE_SCHEMA = {
    "name": "wiki_create_page",
    "description": "Create or update a Wiki Page.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "body": {"type": "string"},
            "type": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "sources": {"type": "array", "items": {"type": "string"}},
            "wiki": {"type": "string"},
        },
        "required": ["title", "body", "type"],
    },
}
_WIKI_LINK_KANBAN_SCHEMA = {
    "name": "wiki_link_kanban",
    "description": "Link a Wiki Page to a kanban task without mutating kanban.db.",
    "parameters": {
        "type": "object",
        "properties": {
            "page_id": {"type": "string"},
            "task_id": {"type": "string"},
            "wiki": {"type": "string"},
        },
        "required": ["page_id", "task_id"],
    },
}

registry.register(
    name="wiki_list",
    toolset="wiki",
    schema=_WIKI_LIST_SCHEMA,
    handler=_handle_wiki_list,
    override=True,
)
registry.register(
    name="wiki_search",
    toolset="wiki",
    schema=_WIKI_SEARCH_SCHEMA,
    handler=_handle_wiki_search,
    override=True,
)
registry.register(
    name="wiki_show",
    toolset="wiki",
    schema=_WIKI_SHOW_SCHEMA,
    handler=_handle_wiki_show,
    override=True,
)
registry.register(
    name="wiki_health_check",
    toolset="wiki",
    schema=_WIKI_HEALTH_SCHEMA,
    handler=_handle_wiki_health_check,
    override=True,
)
registry.register(
    name="wiki_inbox",
    toolset="wiki",
    schema=_WIKI_INBOX_SCHEMA,
    handler=_handle_wiki_inbox,
    override=True,
)
registry.register(
    name="wiki_ingest",
    toolset="wiki",
    schema=_WIKI_INGEST_SCHEMA,
    handler=_handle_wiki_ingest,
    check_fn=lambda: wiki_tools._check_wiki_write_mode(None),
    override=True,
)
registry.register(
    name="wiki_create_page",
    toolset="wiki",
    schema=_WIKI_CREATE_PAGE_SCHEMA,
    handler=_handle_wiki_create_page,
    check_fn=lambda: wiki_tools._check_wiki_write_mode(None),
    override=True,
)
registry.register(
    name="wiki_link_kanban",
    toolset="wiki",
    schema=_WIKI_LINK_KANBAN_SCHEMA,
    handler=_handle_wiki_link_kanban,
    check_fn=lambda: wiki_tools._check_wiki_write_mode(None),
    override=True,
)
