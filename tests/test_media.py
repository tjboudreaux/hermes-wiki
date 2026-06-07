"""Media foundations: manifests, streaming hashes, policies, preflights."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from hermes_wiki import media
from hermes_wiki.media import DerivedManifest, MediaRequirement


def _manifest(**overrides: object) -> DerivedManifest:
    base: dict[str, object] = {
        "tool": "stub-extractor",
        "version": "1.2.3",
        "input_sha256": "ab" * 32,
        "input_size": 2048,
        "source_ref": "raw/audio/2026-06-07-v1-talk.wav",
        "created": "2026-06-07T00:00:00Z",
        "model_id": "tiny",
        "details": {"storage": "large"},
    }
    base.update(overrides)
    return DerivedManifest(**base)  # type: ignore[arg-type]


def test_manifest_round_trip_and_stable_rendering(tmp_path: Path) -> None:
    artifact_dir = media.derived_root(tmp_path, modality="audio", source_stem="2026-06-07-talk")
    assert artifact_dir == tmp_path / "derived" / "audio" / "2026-06-07-talk"

    manifest = _manifest()
    path = media.write_manifest(artifact_dir, manifest)

    assert path.name == media.MANIFEST_FILENAME
    assert media.read_manifest(artifact_dir) == manifest
    # Stable, sorted, newline-terminated JSON — diff-friendly in git.
    raw = path.read_text(encoding="utf-8")
    assert raw == json.dumps(json.loads(raw), indent=2, sort_keys=True) + "\n"


def test_read_manifest_is_fail_safe(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "derived" / "audio" / "x"
    assert media.read_manifest(artifact_dir) is None

    artifact_dir.mkdir(parents=True)
    (artifact_dir / media.MANIFEST_FILENAME).write_text("{not json", encoding="utf-8")
    assert media.read_manifest(artifact_dir) is None

    (artifact_dir / media.MANIFEST_FILENAME).write_text('{"tool": "x"}', encoding="utf-8")
    assert media.read_manifest(artifact_dir) is None  # missing required keys


def test_sha256_stream_matches_full_read_and_copy_stream(tmp_path: Path) -> None:
    payload = b"hermes media bytes " * 200_000  # ~3.8MB, multiple chunks
    source = tmp_path / "big.bin"
    source.write_bytes(payload)

    digest, size = media.sha256_stream(source)
    assert digest == hashlib.sha256(payload).hexdigest()
    assert size == len(payload)

    destination = tmp_path / "nested" / "copy.bin"
    media.copy_stream(source, destination)
    assert destination.read_bytes() == payload


def test_keep_originals_mode_resolution() -> None:
    assert media.keep_originals_mode(None) == "local"
    assert media.keep_originals_mode({}) == "local"
    assert media.keep_originals_mode({"media": {"keep_originals": "NONE"}}) == "none"
    assert media.keep_originals_mode({"media": {"keep_originals": "all"}}) == "all"
    assert media.keep_originals_mode({"media": {"keep_originals": "bogus"}}) == "local"
    assert media.keep_originals_mode({"media": "not-a-dict"}) == "local"


def test_missing_dependencies_and_status_rendering() -> None:
    registry: dict[str, tuple[MediaRequirement, ...]] = {
        "audio": (
            MediaRequirement("binary", "definitely-not-a-binary-xyz", "brew install x"),
            MediaRequirement("python", "definitely_not_a_module_xyz", "hermes-wiki[audio]"),
            MediaRequirement("python", "json", "stdlib"),  # present
        ),
    }
    missing = media.missing_dependencies("audio", requirements=registry)
    assert [req.name for req in missing] == [
        "definitely-not-a-binary-xyz",
        "definitely_not_a_module_xyz",
    ]
    status = media.needs_deps_status(missing)
    assert status.startswith("needs-deps: ")
    assert "brew install x" in status and "hermes-wiki[audio]" in status

    assert media.missing_dependencies("image") == []  # no requirements registered
    assert media.missing_dependencies("unmapped-modality") == []
