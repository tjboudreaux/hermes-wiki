"""Tests for the Wiki memory companion module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fixtures.factory import build_test_wiki
from hermes_wiki.memory_companion import (
    CompanionConfig,
    MemoryCompanion,
    WikiProposal,
    WriteObservation,
    get_companion_tool_schemas,
    handle_wiki_commit_proposal,
    handle_wiki_list_proposals,
    handle_wiki_propose,
    handle_wiki_recall,
    load_config,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_empty_config_returns_defaults(self) -> None:
        cfg = load_config(None)
        assert cfg.enabled is False
        assert cfg.prefetch is True
        assert cfg.prefetch_limit == 3
        assert cfg.observe_writes is True
        assert cfg.auto_propose is False
        assert cfg.proposal_threshold == 0.7

    def test_loads_from_wiki_memory_section(self) -> None:
        config = {
            "wiki": {
                "memory": {
                    "enabled": True,
                    "prefetch": False,
                    "prefetch_limit": 5,
                    "observe_writes": False,
                    "auto_propose": True,
                    "proposal_threshold": 0.9,
                }
            }
        }
        cfg = load_config(config)
        assert cfg.enabled is True
        assert cfg.prefetch is False
        assert cfg.prefetch_limit == 5
        assert cfg.observe_writes is False
        assert cfg.auto_propose is True
        assert cfg.proposal_threshold == 0.9

    def test_loads_from_hermes_wiki_memory_section(self) -> None:
        config = {
            "hermes_wiki": {
                "memory": {
                    "enabled": True,
                    "prefetch_limit": 7,
                }
            }
        }
        cfg = load_config(config)
        assert cfg.enabled is True
        assert cfg.prefetch_limit == 7

    def test_wiki_section_takes_precedence_over_hermes_wiki(self) -> None:
        config = {
            "wiki": {"memory": {"enabled": True, "prefetch_limit": 2}},
            "hermes_wiki": {"memory": {"enabled": False, "prefetch_limit": 10}},
        }
        cfg = load_config(config)
        assert cfg.enabled is True
        assert cfg.prefetch_limit == 2

    def test_missing_memory_section_returns_defaults(self) -> None:
        config = {"wiki": {"other_key": "value"}}
        cfg = load_config(config)
        assert cfg.enabled is False


# ---------------------------------------------------------------------------
# MemoryCompanion — observation
# ---------------------------------------------------------------------------


class TestObservation:
    def test_disabled_companion_does_not_observe(self) -> None:
        companion = MemoryCompanion(config=CompanionConfig(enabled=False))
        result = companion.on_memory_write("add", "memory", "test content")
        assert result is None
        assert companion.observations == []

    def test_enabled_companion_records_observation(self) -> None:
        companion = MemoryCompanion(
            config=CompanionConfig(enabled=True, observe_writes=True)
        )
        result = companion.on_memory_write("add", "memory", "User prefers dark mode")
        assert result is not None
        assert isinstance(result, WriteObservation)
        assert result.action == "add"
        assert result.target == "memory"
        assert result.content == "User prefers dark mode"
        assert companion.observations == [result]

    def test_observe_writes_disabled_skips_recording(self) -> None:
        companion = MemoryCompanion(
            config=CompanionConfig(enabled=True, observe_writes=False)
        )
        result = companion.on_memory_write("add", "memory", "content")
        assert result is None
        assert companion.observations == []

    def test_multiple_observations_accumulate(self) -> None:
        companion = MemoryCompanion(
            config=CompanionConfig(enabled=True, observe_writes=True)
        )
        companion.on_memory_write("add", "memory", "fact 1")
        companion.on_memory_write("replace", "user", "fact 2")
        companion.on_memory_write("add", "memory", "fact 3")
        assert len(companion.observations) == 3
        assert companion.observations[1].action == "replace"
        assert companion.observations[1].target == "user"

    def test_clear_observations(self) -> None:
        companion = MemoryCompanion(
            config=CompanionConfig(enabled=True, observe_writes=True)
        )
        companion.on_memory_write("add", "memory", "data")
        companion.on_memory_write("add", "memory", "more data")
        count = companion.clear_observations()
        assert count == 2
        assert companion.observations == []

    def test_metadata_is_captured(self) -> None:
        companion = MemoryCompanion(
            config=CompanionConfig(enabled=True, observe_writes=True)
        )
        meta = {"session_id": "abc123", "tool_name": "memory"}
        result = companion.on_memory_write("add", "memory", "content", metadata=meta)
        assert result is not None
        assert result.metadata == meta


# ---------------------------------------------------------------------------
# MemoryCompanion — prefetch
# ---------------------------------------------------------------------------


class TestPrefetch:
    def test_disabled_companion_returns_empty(self) -> None:
        companion = MemoryCompanion(config=CompanionConfig(enabled=False))
        assert companion.prefetch("anything") == ""

    def test_prefetch_disabled_returns_empty(self) -> None:
        companion = MemoryCompanion(
            config=CompanionConfig(enabled=True, prefetch=False)
        )
        assert companion.prefetch("anything") == ""

    def test_empty_query_returns_empty(self) -> None:
        companion = MemoryCompanion(
            config=CompanionConfig(enabled=True, prefetch=True)
        )
        assert companion.prefetch("") == ""
        assert companion.prefetch("   ") == ""

    def test_prefetch_returns_formatted_context(
        self, monkeypatch: Any, tmp_path: Path
    ) -> None:
        fixture = build_test_wiki(tmp_path)
        monkeypatch.setenv("HERMES_HOME", str(fixture.home))

        companion = MemoryCompanion(
            config=CompanionConfig(enabled=True, prefetch=True, prefetch_limit=2)
        )
        result = companion.prefetch("memory", wiki=fixture.primary_slug)
        assert "# Wiki Context (auto-recalled)" in result
        assert "agent-memory" in result

    def test_prefetch_respects_limit(self, monkeypatch: Any, tmp_path: Path) -> None:
        fixture = build_test_wiki(tmp_path)
        monkeypatch.setenv("HERMES_HOME", str(fixture.home))

        companion = MemoryCompanion(
            config=CompanionConfig(enabled=True, prefetch=True, prefetch_limit=1)
        )
        result = companion.prefetch("memory", wiki=fixture.primary_slug)
        lines = [line for line in result.strip().split("\n") if line.startswith("- ")]
        assert len(lines) <= 1

    def test_prefetch_no_results_returns_empty(
        self, monkeypatch: Any, tmp_path: Path
    ) -> None:
        fixture = build_test_wiki(tmp_path)
        monkeypatch.setenv("HERMES_HOME", str(fixture.home))

        companion = MemoryCompanion(
            config=CompanionConfig(enabled=True, prefetch=True)
        )
        result = companion.prefetch(
            "xyznonexistentquery12345", wiki=fixture.primary_slug
        )
        assert result == ""


# ---------------------------------------------------------------------------
# MemoryCompanion — proposals
# ---------------------------------------------------------------------------


class TestProposals:
    def test_propose_write_creates_proposal(self) -> None:
        companion = MemoryCompanion(config=CompanionConfig(enabled=True))
        proposal = companion.propose_write(
            title="Test Concept",
            body="This is a test body.",
            page_type="concept",
            tags=("test", "demo"),
            confidence=0.8,
        )
        assert isinstance(proposal, WikiProposal)
        assert proposal.title == "Test Concept"
        assert proposal.body == "This is a test body."
        assert proposal.page_type == "concept"
        assert proposal.tags == ("test", "demo")
        assert proposal.confidence == 0.8
        assert companion.proposals == [proposal]

    def test_pending_proposals_filters_by_threshold(self) -> None:
        companion = MemoryCompanion(
            config=CompanionConfig(enabled=True, proposal_threshold=0.7)
        )
        companion.propose_write(title="Low", body="low", confidence=0.3)
        companion.propose_write(title="Mid", body="mid", confidence=0.7)
        companion.propose_write(title="High", body="high", confidence=0.9)

        pending = companion.pending_proposals()
        assert len(pending) == 2
        assert pending[0].title == "Mid"
        assert pending[1].title == "High"

    def test_pending_proposals_custom_threshold(self) -> None:
        companion = MemoryCompanion(config=CompanionConfig(enabled=True))
        companion.propose_write(title="A", body="a", confidence=0.5)
        companion.propose_write(title="B", body="b", confidence=0.9)

        pending = companion.pending_proposals(min_confidence=0.8)
        assert len(pending) == 1
        assert pending[0].title == "B"

    def test_clear_proposals(self) -> None:
        companion = MemoryCompanion(config=CompanionConfig(enabled=True))
        companion.propose_write(title="X", body="x", confidence=0.5)
        companion.propose_write(title="Y", body="y", confidence=0.9)
        count = companion.clear_proposals()
        assert count == 2
        assert companion.proposals == []


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------


class TestToolSchemas:
    def test_schemas_are_valid_openai_format(self) -> None:
        schemas = get_companion_tool_schemas()
        assert len(schemas) == 4
        names = {s["name"] for s in schemas}
        assert names == {
            "wiki_propose",
            "wiki_recall",
            "wiki_commit_proposal",
            "wiki_list_proposals",
        }
        for schema in schemas:
            assert "name" in schema
            assert "description" in schema
            assert "parameters" in schema
            assert schema["parameters"]["type"] == "object"


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


class TestHandleWikiPropose:
    def test_creates_proposal_and_returns_json(self) -> None:
        companion = MemoryCompanion(config=CompanionConfig(enabled=True))
        result = handle_wiki_propose(companion, {
            "title": "Test Page",
            "body": "Content here",
            "page_type": "howto",
            "tags": ["demo"],
            "confidence": 0.85,
        })
        data = json.loads(result)
        assert data["status"] == "proposed"
        assert data["title"] == "Test Page"
        assert data["page_type"] == "howto"
        assert data["confidence"] == 0.85
        assert len(companion.proposals) == 1


class TestHandleWikiRecall:
    def test_empty_query_returns_error(self) -> None:
        companion = MemoryCompanion(config=CompanionConfig(enabled=True))
        result = handle_wiki_recall(companion, {"query": ""})
        data = json.loads(result)
        assert "error" in data

    def test_recall_with_results(self, monkeypatch: Any, tmp_path: Path) -> None:
        fixture = build_test_wiki(tmp_path)
        monkeypatch.setenv("HERMES_HOME", str(fixture.home))

        companion = MemoryCompanion(
            config=CompanionConfig(enabled=True, prefetch=True, prefetch_limit=2)
        )
        result = handle_wiki_recall(companion, {
            "query": "memory",
            "wiki": fixture.primary_slug,
        })
        data = json.loads(result)
        assert "context" in data
        assert "Wiki Context" in data["context"]

    def test_recall_no_results(self, monkeypatch: Any, tmp_path: Path) -> None:
        fixture = build_test_wiki(tmp_path)
        monkeypatch.setenv("HERMES_HOME", str(fixture.home))

        companion = MemoryCompanion(
            config=CompanionConfig(enabled=True, prefetch=True)
        )
        result = handle_wiki_recall(companion, {"query": "xyznonexistent99999"})
        data = json.loads(result)
        assert data["results"] == []


class TestHandleWikiListProposals:
    def test_empty_proposals(self) -> None:
        companion = MemoryCompanion(config=CompanionConfig(enabled=True))
        result = handle_wiki_list_proposals(companion, {})
        data = json.loads(result)
        assert data["proposals"] == []

    def test_lists_proposals_with_preview(self) -> None:
        companion = MemoryCompanion(config=CompanionConfig(enabled=True))
        companion.propose_write(title="Page A", body="Short body", confidence=0.9)
        companion.propose_write(
            title="Page B",
            body="X" * 300,
            page_type="reference",
            tags=("long",),
            confidence=0.6,
        )
        result = handle_wiki_list_proposals(companion, {})
        data = json.loads(result)
        assert data["count"] == 2
        assert data["proposals"][0]["title"] == "Page A"
        assert data["proposals"][1]["body_preview"].endswith("...")


class TestHandleWikiCommitProposal:
    def test_invalid_index_returns_error(self) -> None:
        companion = MemoryCompanion(config=CompanionConfig(enabled=True))
        result = handle_wiki_commit_proposal(companion, {"index": 5})
        data = json.loads(result)
        assert "error" in data

    def test_commits_proposal_to_wiki(self, monkeypatch: Any, tmp_path: Path) -> None:
        fixture = build_test_wiki(tmp_path)
        monkeypatch.setenv("HERMES_HOME", str(fixture.home))
        monkeypatch.setenv("HERMES_WIKI_MODE", "write")
        monkeypatch.setenv("HERMES_WIKI", fixture.primary_slug)

        companion = MemoryCompanion(config=CompanionConfig(enabled=True))
        companion.propose_write(
            title="Committed Page",
            body="This was proposed and committed.",
            page_type="concept",
            confidence=0.9,
        )

        result = handle_wiki_commit_proposal(
            companion, {"index": 0, "wiki": fixture.primary_slug}
        )
        data = json.loads(result)
        assert data["status"] == "committed"
        assert data["title"] == "Committed Page"
        assert len(companion.proposals) == 0

    def test_removes_committed_proposal_from_list(
        self, monkeypatch: Any, tmp_path: Path
    ) -> None:
        fixture = build_test_wiki(tmp_path)
        monkeypatch.setenv("HERMES_HOME", str(fixture.home))
        monkeypatch.setenv("HERMES_WIKI_MODE", "write")

        companion = MemoryCompanion(config=CompanionConfig(enabled=True))
        companion.propose_write(title="A", body="first", confidence=0.9)
        companion.propose_write(title="B", body="second", confidence=0.9)

        handle_wiki_commit_proposal(
            companion, {"index": 0, "wiki": fixture.primary_slug}
        )
        assert len(companion.proposals) == 1
        assert companion.proposals[0].title == "B"


# ---------------------------------------------------------------------------
# Hermes hook integration
# ---------------------------------------------------------------------------


class TestMemoryHooks:
    def test_register_hooks_wires_on_memory_write(self) -> None:
        from adapters.hermes.memory_hooks import (
            get_companion,
            initialize_companion,
            register_hooks,
            reset_companion,
        )

        reset_companion()
        initialize_companion({"wiki": {"memory": {"enabled": True}}})

        class FakeCtx:
            def __init__(self) -> None:
                self.hooks: dict[str, Any] = {}

            def register_hook(self, name: str, fn: Any) -> None:
                self.hooks[name] = fn

        ctx = FakeCtx()
        register_hooks(ctx)
        assert "on_memory_write" in ctx.hooks

        ctx.hooks["on_memory_write"]("add", "memory", "test data")
        companion = get_companion()
        assert len(companion.observations) == 1
        assert companion.observations[0].content == "test data"

        reset_companion()

    def test_initialize_companion_reads_config(self) -> None:
        from adapters.hermes.memory_hooks import initialize_companion, reset_companion

        reset_companion()
        config = {"wiki": {"memory": {"enabled": True, "prefetch_limit": 7}}}
        companion = initialize_companion(config)
        assert companion.config.enabled is True
        assert companion.config.prefetch_limit == 7
        reset_companion()

    def test_initialize_disabled_companion(self) -> None:
        from adapters.hermes.memory_hooks import initialize_companion, reset_companion

        reset_companion()
        config = {"wiki": {"memory": {"enabled": False}}}
        companion = initialize_companion(config)
        assert companion.config.enabled is False
        reset_companion()

    def test_register_tools_creates_handlers(self) -> None:
        from adapters.hermes.memory_hooks import reset_companion

        reset_companion()

        class FakeToolCtx:
            def __init__(self) -> None:
                self.tools: dict[str, Any] = {}

            def register_tool(self, name: str, handler: Any, schema: Any, toolset: str) -> None:
                self.tools[name] = {"handler": handler, "schema": schema, "toolset": toolset}

        from adapters.hermes.memory_hooks import register_tools

        ctx = FakeToolCtx()
        register_tools(ctx)

        assert "wiki_propose" in ctx.tools
        assert "wiki_recall" in ctx.tools
        assert "wiki_list_proposals" in ctx.tools
        assert "wiki_commit_proposal" in ctx.tools
        assert all(t["toolset"] == "wiki" for t in ctx.tools.values())
        reset_companion()
