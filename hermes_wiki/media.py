"""Media foundations: derived-artifact tier, manifests, storage tiers, preflights.

Implements the cross-modality plumbing from ``docs/media-ingestion-design.md``:

- D2 — ``derived/<modality>/<source-id>/`` artifact tier with provenance
  manifests recording tool + version + model identity + input fingerprint.
- D3 — dependency preflights that report *actionable* missing requirements
  instead of crashing (``needs-deps`` retention upstream).
- D4 — two-tier storage constants and the ``keep_originals`` policy for media
  larger than the git-tracked snapshot cap.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

#: Media above the git-tracked snapshot cap is processed up to this size (D4).
MAX_MEDIA_BYTES = 2 * 1024 * 1024 * 1024

#: Gitignored home for sha-pinned large originals (``keep_originals: local``).
LARGE_MEDIA_REL = "raw/large"

#: Labels handled by the media foundations (PDFs stay under ``paper``).
MEDIA_LABELS = ("image", "audio", "video")

#: ``keep_originals`` policy values (D4).
KEEP_ORIGINALS_MODES = ("local", "none", "all")
DEFAULT_KEEP_ORIGINALS = "local"

MANIFEST_FILENAME = "manifest.json"

#: Label -> derived-directory modality mapping (labels not listed map to themselves).
_DERIVED_MODALITIES = {"paper": "pdf"}


def derived_modality(label: str) -> str:
    """Resolve the ``derived/<modality>/`` directory name for a label."""

    return _DERIVED_MODALITIES.get(label, label)

_STREAM_CHUNK = 1024 * 1024


@dataclass(frozen=True, slots=True)
class MediaRequirement:
    """One installable requirement for a modality."""

    kind: str  # "python" | "binary"
    name: str
    install_hint: str


#: Per-modality dependency registry (D3). Extraction tools land in their
#: modality phases; binaries that gate them are declared here so preflights
#: and ``needs-deps`` statuses stay in one place.
MEDIA_REQUIREMENTS: dict[str, tuple[MediaRequirement, ...]] = {
    "image": (),
    "audio": (MediaRequirement("binary", "ffmpeg", "brew install ffmpeg | apt install ffmpeg"),),
    "video": (MediaRequirement("binary", "ffmpeg", "brew install ffmpeg | apt install ffmpeg"),),
}


@dataclass(frozen=True, slots=True)
class DerivedManifest:
    """Provenance manifest for one derived-artifact set (D2)."""

    tool: str
    version: str
    input_sha256: str
    input_size: int
    source_ref: str
    created: str
    model_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def package_version() -> str:
    """Resolve the installed hermes-wiki version for manifest stamping."""

    try:
        return importlib.metadata.version("hermes-wiki")
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover - dev tree
        return "0.0.0+unknown"


def derived_root(wiki_root: Path, *, modality: str, source_stem: str) -> Path:
    """Return ``derived/<modality>/<source_stem>/`` under ``wiki_root``."""

    return Path(wiki_root) / "derived" / modality / source_stem


def write_manifest(artifact_dir: Path, manifest: DerivedManifest) -> Path:
    """Persist the manifest as stable JSON; returns the manifest path."""

    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / MANIFEST_FILENAME
    path.write_text(
        json.dumps(asdict(manifest), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def read_manifest(artifact_dir: Path) -> DerivedManifest | None:
    """Load a manifest; ``None`` when absent or unreadable (fail-safe)."""

    path = Path(artifact_dir) / MANIFEST_FILENAME
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(loaded, dict):
        return None
    try:
        return DerivedManifest(
            tool=str(loaded["tool"]),
            version=str(loaded["version"]),
            input_sha256=str(loaded["input_sha256"]),
            input_size=int(loaded["input_size"]),
            source_ref=str(loaded["source_ref"]),
            created=str(loaded["created"]),
            model_id=(None if loaded.get("model_id") is None else str(loaded["model_id"])),
            details=dict(loaded.get("details") or {}),
        )
    except (KeyError, TypeError, ValueError):
        return None


def sha256_stream(path: Path) -> tuple[str, int]:
    """Chunked sha256 + size for files too large to read into memory."""

    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(_STREAM_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def copy_stream(source: Path, destination: Path) -> None:
    """Stream-copy ``source`` to ``destination`` (parents created)."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    with Path(source).open("rb") as src, destination.open("wb") as dst:
        shutil.copyfileobj(src, dst, _STREAM_CHUNK)


def keep_originals_mode(config: dict[str, Any] | None) -> str:
    """Resolve the ``wiki.media.keep_originals`` policy from a config mapping."""

    if isinstance(config, dict):
        media_cfg = config.get("media")
        if isinstance(media_cfg, dict):
            mode = str(media_cfg.get("keep_originals") or "").strip().lower()
            if mode in KEEP_ORIGINALS_MODES:
                return mode
    return DEFAULT_KEEP_ORIGINALS


def missing_dependencies(
    modality: str,
    *,
    requirements: dict[str, tuple[MediaRequirement, ...]] | None = None,
) -> list[MediaRequirement]:
    """Return unmet requirements for ``modality`` (empty list when ready)."""

    registry = MEDIA_REQUIREMENTS if requirements is None else requirements
    missing: list[MediaRequirement] = []
    for requirement in registry.get(modality, ()):
        if requirement.kind == "binary":
            if shutil.which(requirement.name) is None:
                missing.append(requirement)
        elif requirement.kind == "python":
            if importlib.util.find_spec(requirement.name) is None:
                missing.append(requirement)
    return missing


def needs_deps_status(missing: list[MediaRequirement]) -> str:
    """Render the inbox-status string for unmet requirements."""

    rendered = ", ".join(f"{req.name} ({req.install_hint})" for req in missing)
    return f"needs-deps: {rendered}"


__all__ = [
    "DEFAULT_KEEP_ORIGINALS",
    "KEEP_ORIGINALS_MODES",
    "LARGE_MEDIA_REL",
    "MANIFEST_FILENAME",
    "MAX_MEDIA_BYTES",
    "MEDIA_LABELS",
    "MEDIA_REQUIREMENTS",
    "DerivedManifest",
    "MediaRequirement",
    "copy_stream",
    "derived_modality",
    "derived_root",
    "keep_originals_mode",
    "missing_dependencies",
    "needs_deps_status",
    "package_version",
    "read_manifest",
    "sha256_stream",
    "write_manifest",
]
