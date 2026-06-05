"""Deterministic seed data shared by Hermes Wiki integration tests.

The objects in this module are intentionally plain and stable: fixed slugs,
timestamps, page IDs, source IDs, and lint-condition descriptors.  Later
milestones can import these fixtures without needing to infer expected data
from ad-hoc files on disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

FIXED_NOW = "2026-06-05T09:30:00Z"
FIXED_PREVIOUS = "2026-06-04T15:00:00Z"
FIXTURE_AUTHOR = "fixture:agent"
FIXTURE_AUTHOR_KIND = "agent"

PRIMARY_WIKI_SLUG = "ai-tooling"
ARCHIVED_WIKI_SLUG = "ungodly-economy"
PRIVATE_WIKI_SLUG = "private-lab"
PROFILE_NAME = "test-profile"

PRIMARY_WIKI_DOMAIN = "AI agents, coding tools, and research workflows"
ARCHIVED_WIKI_DOMAIN = "Archived game economy research"
PRIVATE_WIKI_DOMAIN = "Private model-evaluation lab notes"

SOURCES_DIR = Path(__file__).resolve().parent / "sources"
SAMPLE_SOURCE_FILES = {
    "article": "agent-memory-article.md",
    "paper": "agent-systems-paper.pdf",
    "transcript": "memory-workshop-transcript.txt",
    "unknown": "unknown-sample.dat",
}
SAMPLE_SOURCE_KINDS = tuple(SAMPLE_SOURCE_FILES)

PAGE_TYPE_DIRECTORIES = {
    "source": "sources",
    "entity": "entities",
    "concept": "concepts",
    "comparison": "comparisons",
    "query": "queries",
    "summary": "summaries",
}
PAGE_TYPES = tuple(PAGE_TYPE_DIRECTORIES)

RAW_SOURCE_DESTINATIONS = {
    "article": "raw/articles/2026-06-05-v1-agent-memory-article.md",
    "paper": "raw/papers/2026-06-05-v1-agent-systems-paper.pdf",
    "transcript": "raw/transcripts/2026-06-05-v1-memory-workshop-transcript.txt",
}

TAXONOMY_TAGS = (
    "agents",
    "memory",
    "research",
    "evaluation",
    "tooling",
    "operations",
)


@dataclass(frozen=True, slots=True)
class KanbanRefSeed:
    """Canonical wiki-side kanban reference for a seeded page."""

    task_id: str
    direction: str
    created: str


@dataclass(frozen=True, slots=True)
class PageSeed:
    """A deterministic Wiki Page seed."""

    id: str
    title: str
    type: str
    created: str
    updated: str
    tags: tuple[str, ...]
    sources: tuple[str, ...]
    confidence: str
    contested: bool
    author: str
    author_kind: str
    body: str
    inbound_links: int = 0
    links: tuple[str, ...] = ()
    kanban_refs: tuple[KanbanRefSeed, ...] = ()
    contradictions: str | None = None

    @property
    def relative_path(self) -> Path:
        """Return the Markdown path for this page relative to a wiki root."""

        return Path(f"{self.id}.md")


@dataclass(frozen=True, slots=True)
class LintFindingSeed:
    """Expected lint condition intentionally present in the populated fixture."""

    code: str
    severity: str
    target: str
    description: str


def sample_source_path(kind: str) -> Path:
    """Return the repository fixture file for a sample source kind."""

    try:
        filename = SAMPLE_SOURCE_FILES[kind]
    except KeyError as exc:
        expected = ", ".join(SAMPLE_SOURCE_KINDS)
        raise ValueError(
            f"unknown sample source kind {kind!r}; expected one of {expected}"
        ) from exc
    return SOURCES_DIR / filename


def _long_summary_body() -> str:
    lines = [
        "# Agent Operations Summary",
        "",
        "This deliberately long summary gives lint tests a low-severity page-size signal.",
        "It links back to [Agent Memory](../concepts/agent-memory.md).",
        "",
    ]
    lines.extend(
        f"- Operational note {index:03d}: keep wiki evidence attributed."
        for index in range(1, 206)
    )
    return "\n".join(lines)


PRIMARY_PAGES = (
    PageSeed(
        id="sources/2026-06-05-agent-memory-article",
        title="Agent Memory Article",
        type="source",
        created=FIXED_PREVIOUS,
        updated=FIXED_NOW,
        tags=("agents", "memory", "research"),
        sources=(RAW_SOURCE_DESTINATIONS["article"],),
        confidence="high",
        contested=False,
        author=FIXTURE_AUTHOR,
        author_kind=FIXTURE_AUTHOR_KIND,
        body="\n".join(
            [
                "# Agent Memory Article",
                "",
                "Curated Source Page summarizing the immutable article snapshot.",
                "The article explains why durable memory improves coding-agent continuity.",
                "Key derived pages: [Agent Memory](../concepts/agent-memory.md) and "
                "[Hermes](../entities/hermes.md).",
            ]
        ),
        links=("concepts/agent-memory", "entities/hermes"),
    ),
    PageSeed(
        id="concepts/agent-memory",
        title="Agent Memory",
        type="concept",
        created=FIXED_PREVIOUS,
        updated=FIXED_NOW,
        tags=("agents", "memory", "tooling"),
        sources=(
            RAW_SOURCE_DESTINATIONS["article"],
            RAW_SOURCE_DESTINATIONS["paper"],
            RAW_SOURCE_DESTINATIONS["transcript"],
        ),
        confidence="high",
        contested=False,
        author=FIXTURE_AUTHOR,
        author_kind=FIXTURE_AUTHOR_KIND,
        body="\n".join(
            [
                "# Agent Memory",
                "",
                "Agent memory stores reusable context between Hermes sessions.",
                "The getCwd helper appears in examples so search normalization can match get cwd.",
                "Evidence comes from [Agent Memory Article]"
                "(../sources/2026-06-05-agent-memory-article.md) and "
                "[Agent Systems Paper](../sources/2026-06-05-agent-systems-paper.md).",
                "Hermes is tracked as [Hermes](../entities/hermes.md).",
            ]
        ),
        inbound_links=3,
        links=(
            "sources/2026-06-05-agent-memory-article",
            "sources/2026-06-05-agent-systems-paper",
            "entities/hermes",
        ),
        kanban_refs=(
            KanbanRefSeed(
                task_id="KB-123",
                direction="page->task",
                created=FIXED_NOW,
            ),
        ),
    ),
    PageSeed(
        id="entities/hermes",
        title="Hermes",
        type="entity",
        created=FIXED_PREVIOUS,
        updated=FIXED_NOW,
        tags=("agents", "tooling"),
        sources=(RAW_SOURCE_DESTINATIONS["article"], RAW_SOURCE_DESTINATIONS["transcript"]),
        confidence="medium",
        contested=False,
        author=FIXTURE_AUTHOR,
        author_kind=FIXTURE_AUTHOR_KIND,
        body="\n".join(
            [
                "# Hermes",
                "",
                "Hermes is the agent environment hosting the Wiki Surface.",
                "It relies on [Agent Memory](../concepts/agent-memory.md) "
                "to retain domain context.",
            ]
        ),
        inbound_links=2,
        links=("concepts/agent-memory",),
    ),
    PageSeed(
        id="comparisons/memory-vs-scratchpad",
        title="Memory vs Scratchpad",
        type="comparison",
        created=FIXED_PREVIOUS,
        updated=FIXED_NOW,
        tags=("memory", "invalid-experimental"),
        sources=(RAW_SOURCE_DESTINATIONS["paper"],),
        confidence="medium",
        contested=False,
        author=FIXTURE_AUTHOR,
        author_kind=FIXTURE_AUTHOR_KIND,
        body="\n".join(
            [
                "# Memory vs Scratchpad",
                "",
                "[Agent Memory](../concepts/agent-memory.md) persists across sessions; scratchpads "
                "are transient.",
                "This page intentionally links to "
                "[Missing Concept](../concepts/missing-concept.md) "
                "for high-severity broken-link lint coverage.",
            ]
        ),
        links=("concepts/agent-memory", "concepts/missing-concept"),
    ),
    PageSeed(
        id="queries/evaluate-agent-memory",
        title="Evaluate Agent Memory",
        type="query",
        created=FIXED_PREVIOUS,
        updated=FIXED_NOW,
        tags=("evaluation", "memory"),
        sources=(RAW_SOURCE_DESTINATIONS["transcript"],),
        confidence="low",
        contested=True,
        contradictions="Benchmarks disagree on whether long-term memory improves every task.",
        author=FIXTURE_AUTHOR,
        author_kind=FIXTURE_AUTHOR_KIND,
        body="\n".join(
            [
                "# Evaluate Agent Memory",
                "",
                "[unverified] Which benchmark best predicts useful long-term agent memory?",
                "Consult [Agent Memory](../concepts/agent-memory.md) before "
                "changing acceptance gates.",
            ]
        ),
        links=("concepts/agent-memory",),
    ),
    PageSeed(
        id="summaries/agent-operations",
        title="Agent Operations Summary",
        type="summary",
        created=FIXED_PREVIOUS,
        updated=FIXED_NOW,
        tags=("operations", "agents", "memory"),
        sources=(RAW_SOURCE_DESTINATIONS["article"], RAW_SOURCE_DESTINATIONS["transcript"]),
        confidence="medium",
        contested=False,
        author=FIXTURE_AUTHOR,
        author_kind=FIXTURE_AUTHOR_KIND,
        body=_long_summary_body(),
        links=("concepts/agent-memory",),
    ),
)

CLEAN_PRIMARY_PAGES = (
    PageSeed(
        id="sources/2026-06-05-agent-memory-article",
        title="Agent Memory Article",
        type="source",
        created=FIXED_PREVIOUS,
        updated=FIXED_NOW,
        tags=("agents", "memory", "research"),
        sources=(RAW_SOURCE_DESTINATIONS["article"],),
        confidence="high",
        contested=False,
        author=FIXTURE_AUTHOR,
        author_kind=FIXTURE_AUTHOR_KIND,
        body="\n".join(
            [
                "# Agent Memory Article",
                "",
                "Curated Source Page summarizing the immutable article snapshot.",
                "The article explains why durable memory improves coding-agent continuity.",
                "Key derived pages: [Agent Memory](../concepts/agent-memory.md) and "
                "[Hermes](../entities/hermes.md).",
            ]
        ),
        links=("concepts/agent-memory", "entities/hermes"),
    ),
    PageSeed(
        id="sources/2026-06-05-agent-systems-paper",
        title="Agent Systems Paper",
        type="source",
        created=FIXED_PREVIOUS,
        updated=FIXED_NOW,
        tags=("agents", "research", "evaluation"),
        sources=(RAW_SOURCE_DESTINATIONS["paper"],),
        confidence="high",
        contested=False,
        author=FIXTURE_AUTHOR,
        author_kind=FIXTURE_AUTHOR_KIND,
        body="\n".join(
            [
                "# Agent Systems Paper",
                "",
                "Curated Source Page summarizing the paper snapshot about agent systems.",
                "It grounds [Agent Memory](../concepts/agent-memory.md) and "
                "[Memory vs Scratchpad](../comparisons/memory-vs-scratchpad.md).",
            ]
        ),
        links=("concepts/agent-memory", "comparisons/memory-vs-scratchpad"),
    ),
    PageSeed(
        id="sources/2026-06-05-memory-workshop-transcript",
        title="Memory Workshop Transcript",
        type="source",
        created=FIXED_PREVIOUS,
        updated=FIXED_NOW,
        tags=("agents", "memory", "operations"),
        sources=(RAW_SOURCE_DESTINATIONS["transcript"],),
        confidence="medium",
        contested=False,
        author=FIXTURE_AUTHOR,
        author_kind=FIXTURE_AUTHOR_KIND,
        body="\n".join(
            [
                "# Memory Workshop Transcript",
                "",
                "Curated Source Page summarizing workshop notes about operational memory use.",
                "It informs [Evaluate Agent Memory](../queries/evaluate-agent-memory.md) and "
                "[Agent Operations Summary](../summaries/agent-operations.md).",
            ]
        ),
        links=("queries/evaluate-agent-memory", "summaries/agent-operations"),
    ),
    PageSeed(
        id="concepts/agent-memory",
        title="Agent Memory",
        type="concept",
        created=FIXED_PREVIOUS,
        updated=FIXED_NOW,
        tags=("agents", "memory", "tooling"),
        sources=(
            RAW_SOURCE_DESTINATIONS["article"],
            RAW_SOURCE_DESTINATIONS["paper"],
            RAW_SOURCE_DESTINATIONS["transcript"],
        ),
        confidence="high",
        contested=False,
        author=FIXTURE_AUTHOR,
        author_kind=FIXTURE_AUTHOR_KIND,
        body="\n".join(
            [
                "# Agent Memory",
                "",
                "Agent memory stores reusable context between Hermes sessions.",
                "The getCwd helper appears in examples so search normalization can match get cwd.",
                "Evidence comes from [Agent Memory Article]"
                "(../sources/2026-06-05-agent-memory-article.md), "
                "[Agent Systems Paper](../sources/2026-06-05-agent-systems-paper.md), and "
                "[Memory Workshop Transcript]"
                "(../sources/2026-06-05-memory-workshop-transcript.md).",
                "Hermes is tracked as [Hermes](../entities/hermes.md), and memory tradeoffs are "
                "summarized in [Memory vs Scratchpad](../comparisons/memory-vs-scratchpad.md).",
            ]
        ),
        links=(
            "sources/2026-06-05-agent-memory-article",
            "sources/2026-06-05-agent-systems-paper",
            "sources/2026-06-05-memory-workshop-transcript",
            "entities/hermes",
            "comparisons/memory-vs-scratchpad",
        ),
    ),
    PageSeed(
        id="entities/hermes",
        title="Hermes",
        type="entity",
        created=FIXED_PREVIOUS,
        updated=FIXED_NOW,
        tags=("agents", "tooling"),
        sources=(RAW_SOURCE_DESTINATIONS["article"], RAW_SOURCE_DESTINATIONS["transcript"]),
        confidence="medium",
        contested=False,
        author=FIXTURE_AUTHOR,
        author_kind=FIXTURE_AUTHOR_KIND,
        body="\n".join(
            [
                "# Hermes",
                "",
                "Hermes is the agent environment hosting the Wiki Surface.",
                "It relies on [Agent Memory](../concepts/agent-memory.md) to retain domain context "
                "and cites the [Memory Workshop Transcript]"
                "(../sources/2026-06-05-memory-workshop-transcript.md).",
            ]
        ),
        links=("concepts/agent-memory", "sources/2026-06-05-memory-workshop-transcript"),
    ),
    PageSeed(
        id="comparisons/memory-vs-scratchpad",
        title="Memory vs Scratchpad",
        type="comparison",
        created=FIXED_PREVIOUS,
        updated=FIXED_NOW,
        tags=("memory", "evaluation"),
        sources=(RAW_SOURCE_DESTINATIONS["paper"],),
        confidence="medium",
        contested=False,
        author=FIXTURE_AUTHOR,
        author_kind=FIXTURE_AUTHOR_KIND,
        body="\n".join(
            [
                "# Memory vs Scratchpad",
                "",
                "[Agent Memory](../concepts/agent-memory.md) persists across sessions; scratchpads "
                "are transient.",
                "The [Agent Systems Paper](../sources/2026-06-05-agent-systems-paper.md) and "
                "[Evaluate Agent Memory](../queries/evaluate-agent-memory.md) explain when each "
                "approach is useful.",
            ]
        ),
        links=(
            "concepts/agent-memory",
            "sources/2026-06-05-agent-systems-paper",
            "queries/evaluate-agent-memory",
        ),
    ),
    PageSeed(
        id="queries/evaluate-agent-memory",
        title="Evaluate Agent Memory",
        type="query",
        created=FIXED_PREVIOUS,
        updated=FIXED_NOW,
        tags=("evaluation", "memory"),
        sources=(RAW_SOURCE_DESTINATIONS["transcript"],),
        confidence="medium",
        contested=False,
        author=FIXTURE_AUTHOR,
        author_kind=FIXTURE_AUTHOR_KIND,
        body="\n".join(
            [
                "# Evaluate Agent Memory",
                "",
                "Evaluation should compare task continuity, retrieval precision, "
                "and operator effort.",
                "Consult [Agent Memory](../concepts/agent-memory.md), "
                "[Memory Workshop Transcript]"
                "(../sources/2026-06-05-memory-workshop-transcript.md), "
                "and [Agent Operations Summary](../summaries/agent-operations.md).",
            ]
        ),
        links=(
            "concepts/agent-memory",
            "sources/2026-06-05-memory-workshop-transcript",
            "summaries/agent-operations",
        ),
    ),
    PageSeed(
        id="summaries/agent-operations",
        title="Agent Operations Summary",
        type="summary",
        created=FIXED_PREVIOUS,
        updated=FIXED_NOW,
        tags=("operations", "agents", "memory"),
        sources=(RAW_SOURCE_DESTINATIONS["article"], RAW_SOURCE_DESTINATIONS["transcript"]),
        confidence="medium",
        contested=False,
        author=FIXTURE_AUTHOR,
        author_kind=FIXTURE_AUTHOR_KIND,
        body="\n".join(
            [
                "# Agent Operations Summary",
                "",
                "Operational wiki care keeps evidence attributed, links current, "
                "and stale claims visible.",
                "The summary cites [Agent Memory](../concepts/agent-memory.md), "
                "[Hermes](../entities/hermes.md), "
                "[Agent Memory Article](../sources/2026-06-05-agent-memory-article.md), and "
                "[Memory Workshop Transcript]"
                "(../sources/2026-06-05-memory-workshop-transcript.md).",
            ]
        ),
        links=(
            "concepts/agent-memory",
            "entities/hermes",
            "sources/2026-06-05-agent-memory-article",
            "sources/2026-06-05-memory-workshop-transcript",
        ),
    ),
)

INITIAL_AGENT_MEMORY_BODY = "\n".join(
    [
        "# Agent Memory",
        "",
        "Agent memory stores reusable context between Hermes sessions.",
        "Initial draft linked only to [Hermes](../entities/hermes.md).",
    ]
)

LINT_FINDINGS = (
    LintFindingSeed(
        code="broken-relative-link",
        severity="high",
        target="comparisons/memory-vs-scratchpad",
        description="Comparison page links to a missing concept page.",
    ),
    LintFindingSeed(
        code="invalid-tag",
        severity="high",
        target="comparisons/memory-vs-scratchpad",
        description="Comparison page includes a tag outside the seeded taxonomy.",
    ),
    LintFindingSeed(
        code="contested-unresolved",
        severity="medium",
        target="queries/evaluate-agent-memory",
        description="Query page is contested and intentionally unresolved.",
    ),
    LintFindingSeed(
        code="oversized-inbox",
        severity="medium",
        target="raw/inbox/oversized-sample.bin",
        description="Oversized inbox item awaits a future media/chunking workflow.",
    ),
    LintFindingSeed(
        code="page-over-200-lines",
        severity="low",
        target="summaries/agent-operations",
        description="Summary page intentionally exceeds the recommended line count.",
    ),
)

__all__ = [
    "ARCHIVED_WIKI_DOMAIN",
    "ARCHIVED_WIKI_SLUG",
    "CLEAN_PRIMARY_PAGES",
    "FIXED_NOW",
    "FIXED_PREVIOUS",
    "FIXTURE_AUTHOR",
    "FIXTURE_AUTHOR_KIND",
    "INITIAL_AGENT_MEMORY_BODY",
    "LINT_FINDINGS",
    "PAGE_TYPES",
    "PAGE_TYPE_DIRECTORIES",
    "PRIMARY_PAGES",
    "PRIMARY_WIKI_DOMAIN",
    "PRIMARY_WIKI_SLUG",
    "PRIVATE_WIKI_DOMAIN",
    "PRIVATE_WIKI_SLUG",
    "PROFILE_NAME",
    "RAW_SOURCE_DESTINATIONS",
    "SAMPLE_SOURCE_FILES",
    "SAMPLE_SOURCE_KINDS",
    "SOURCES_DIR",
    "TAXONOMY_TAGS",
    "KanbanRefSeed",
    "LintFindingSeed",
    "PageSeed",
    "sample_source_path",
]
