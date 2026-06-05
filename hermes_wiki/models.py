"""Core dataclasses used by Wiki ingest and projection surfaces."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ClassLabel:
    """Classification result for a Raw Source."""

    name: str
    confidence: str = "medium"
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class WikiPage:
    """A planned or materialized Wiki Page."""

    id: str
    title: str
    type: str
    body: str
    tags: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    links: tuple[str, ...] = ()
    confidence: str = "medium"
    contested: bool = False


@dataclass(frozen=True, slots=True)
class Source:
    """Projected metadata for an immutable Source Snapshot."""

    id: str
    sha256: str
    source_path: str
    source_url: str | None
    classified_as: str
    version: int = 1
    previous_source_id: str | None = None
    is_latest: bool = True


@dataclass(frozen=True, slots=True)
class MonitorJob:
    """Portable monitor definition placeholder for later milestones."""

    name: str
    source: str
    schedule: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    prompt: str | None = None
    enabled: bool = False
