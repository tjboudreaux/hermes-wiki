"""Shared validation helpers for wiki slugs and profile marker names."""

from __future__ import annotations

import re

SLUG_PATTERN = r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$"
PROFILE_PATTERN = SLUG_PATTERN

SLUG_RE = re.compile(SLUG_PATTERN)
PROFILE_RE = re.compile(PROFILE_PATTERN)


class ValidationError(ValueError):
    """Raised when a user-provided identifier is invalid."""


def validate_slug(value: str) -> str:
    """Return a clean wiki slug or raise ``ValidationError``.

    Slugs are intentionally path-safe and URL-friendly: lowercase ASCII letters,
    digits, and internal hyphens only. This keeps wiki roots unambiguous and
    prevents accidental path traversal or mixed-case duplicates.
    """

    slug = _one_line(value, "wiki slug")
    if slug in {".", ".."} or not SLUG_RE.fullmatch(slug):
        raise ValidationError(
            "invalid wiki slug: use lowercase letters, digits, and internal hyphens"
        )
    return slug


def validate_profile(value: str) -> str:
    """Return a clean profile marker name or raise ``ValidationError``."""

    profile = _one_line(value, "profile name")
    if profile in {".", ".."} or not PROFILE_RE.fullmatch(profile):
        raise ValidationError(
            "invalid profile name: use lowercase letters, digits, and internal hyphens"
        )
    return profile


def _one_line(value: str, label: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValidationError(f"{label} is required")
    if "\n" in clean or "\r" in clean:
        raise ValidationError(f"{label} must be a single line")
    return clean


__all__ = [
    "PROFILE_PATTERN",
    "PROFILE_RE",
    "SLUG_PATTERN",
    "SLUG_RE",
    "ValidationError",
    "validate_profile",
    "validate_slug",
]
