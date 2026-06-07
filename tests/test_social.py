"""Social modality: adapters, evidence snapshots, quoted pages (design PR5)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from hermes_wiki import pipeline, social
from hermes_wiki.social import SocialFetchError, fetch_social_post, match_social_url

BLUESKY_URL = "https://bsky.app/profile/alice.bsky.social/post/3kabc7xyz2a"
MASTODON_URL = "https://hachyderm.io/@bob/112233445566"
X_URL = "https://x.com/carol/status/9988776655"

BLUESKY_THREAD = {
    "thread": {
        "post": {
            "author": {"did": "did:plc:abc", "handle": "alice.bsky.social",
                       "displayName": "Alice"},
            "record": {
                "text": "Modular memory keeps agents honest.\nSecond line.",
                "createdAt": "2026-06-01T10:00:00Z",
            },
        }
    }
}
MASTODON_STATUS = {
    "id": "112233445566",
    "created_at": "2026-05-30T08:30:00Z",
    "content": "<p>Retrieval &amp; rot: archive what you fetched.</p>",
    "account": {"acct": "bob", "username": "bob", "display_name": "Bob B."},
}
X_OEMBED = {
    "author_name": "Carol",
    "html": '<blockquote><p>Anchors beat vibes for provenance.</p></blockquote>',
}


def _fake_fetch(url: str) -> dict[str, Any]:
    if "resolveHandle" in url:
        return {"did": "did:plc:abc"}
    if "getPostThread" in url:
        assert "at%3A%2F%2Fdid%3Aplc%3Aabc" in url  # resolved DID is used
        return BLUESKY_THREAD
    if "/api/v1/statuses/" in url:
        return MASTODON_STATUS
    if "publish.twitter.com/oembed" in url:
        return X_OEMBED
    raise AssertionError(f"unexpected fetch: {url}")


@pytest.fixture(autouse=True)
def _patched_fetch(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(social, "_default_fetch_json", _fake_fetch)


def _with_env(tmp_path: Path, fn):
    merged = {"HERMES_HOME": str(tmp_path), "HERMES_WIKI": "ai-tooling", "USER": "soc-tester"}
    old = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(merged)
        return fn()
    finally:
        os.environ.clear()
        os.environ.update(old)


def _create_wiki(tmp_path: Path) -> Path:
    from hermes_wiki_cli.cli import main

    assert _with_env(tmp_path, lambda: main(["create", "ai-tooling"])) == 0
    return tmp_path / "wikis" / "ai-tooling"


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        (BLUESKY_URL, "bluesky"),
        (MASTODON_URL, "mastodon"),
        (X_URL, "x"),
        ("https://twitter.com/carol/status/1", "x"),
        ("https://example.com/@looks/like/nothing", None),
        ("https://x.com/@carol/9988776655", None),  # not a status path
        ("https://bsky.app/profile/alice.bsky.social", None),
    ],
)
def test_match_social_url(url: str, platform: str | None) -> None:
    assert match_social_url(url) == platform


def test_fetch_adapters_normalize_posts() -> None:
    bsky = fetch_social_post(BLUESKY_URL, fetch_json=_fake_fetch)
    assert bsky.author_handle == "alice.bsky.social"
    assert bsky.created_at == "2026-06-01T10:00:00Z"
    assert "Modular memory keeps agents honest." in bsky.text

    masto = fetch_social_post(MASTODON_URL, fetch_json=_fake_fetch)
    assert masto.author_handle == "bob@hachyderm.io"
    assert masto.text == "Retrieval & rot: archive what you fetched."  # tags stripped

    x_post = fetch_social_post(X_URL, fetch_json=_fake_fetch)
    assert x_post.author_name == "Carol"
    assert x_post.created_at == ""  # oEmbed has no timestamp
    assert "Anchors beat vibes" in x_post.text


def test_social_url_ingest_snapshots_api_evidence(tmp_path: Path) -> None:
    wiki_root = _create_wiki(tmp_path)

    result = _with_env(
        tmp_path, lambda: pipeline.ingest_source(BLUESKY_URL, wiki="ai-tooling")
    )

    assert result.classified_as == "social"
    assert result.raw_snapshot.startswith("raw/social/")
    snapshot = json.loads((wiki_root / result.raw_snapshot).read_text(encoding="utf-8"))
    assert snapshot == BLUESKY_THREAD  # archived exactly what we fetched

    page_id = result.pages_created[0]
    page_text = (wiki_root / f"{page_id}.md").read_text(encoding="utf-8")
    assert "> Modular memory keeps agents honest." in page_text  # quoted
    assert "Alice (@alice.bsky.social)" in page_text
    assert BLUESKY_URL in page_text
    assert "tags:" in page_text and "social" in page_text


def test_mastodon_ingest_renders_attributed_quote(tmp_path: Path) -> None:
    wiki_root = _create_wiki(tmp_path)

    result = _with_env(
        tmp_path, lambda: pipeline.ingest_source(MASTODON_URL, wiki="ai-tooling")
    )

    page_text = (wiki_root / f"{result.pages_created[0]}.md").read_text(encoding="utf-8")
    assert "> Retrieval & rot: archive what you fetched." in page_text
    assert "Bob B. (@bob@hachyderm.io)" in page_text
    assert "Posted: 2026-05-30T08:30:00Z" in page_text


def test_fetch_failure_is_a_clean_ingest_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _create_wiki(tmp_path)

    def broken(url: str) -> dict[str, Any]:
        raise SocialFetchError(f"social fetch failed for {url}: boom")

    monkeypatch.setattr(social, "_default_fetch_json", broken)
    with pytest.raises(pipeline.IngestError, match="social fetch failed"):
        _with_env(tmp_path, lambda: pipeline.ingest_source(X_URL, wiki="ai-tooling"))


def test_reingest_unchanged_post_is_deduped(tmp_path: Path) -> None:
    _create_wiki(tmp_path)

    first = _with_env(tmp_path, lambda: pipeline.ingest_source(X_URL, wiki="ai-tooling"))
    again = _with_env(tmp_path, lambda: pipeline.ingest_source(X_URL, wiki="ai-tooling"))

    assert not first.skipped
    assert again.skipped and again.message == "no change"
