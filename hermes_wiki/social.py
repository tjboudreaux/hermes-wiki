"""Social-post ingestion adapters (media design PR5 / D9).

Matched post URLs are fetched through platform APIs and the *fetched JSON
response* is snapshotted into ``raw/social/`` as the immutable evidence —
archive what we fetched, because reference rot is real. Fetchers are
injectable so tests run on recorded fixtures, never the live network.

Platforms: Bluesky (public XRPC), Mastodon (public statuses API), X (public
oEmbed). Anything else falls through to normal URL ingestion; the
wiki-media-ingestion skill's social protocol covers read-and-note fallbacks.
"""

from __future__ import annotations

import html as html_module
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

FETCH_TIMEOUT_SECONDS = 15

_BLUESKY_RE = re.compile(
    r"^https?://bsky\.app/profile/(?P<actor>[^/]+)/post/(?P<rkey>[A-Za-z0-9.~_-]+)/?$"
)
_MASTODON_RE = re.compile(r"^https?://(?P<host>[^/]+)/@(?P<user>[^/@]+)/(?P<id>\d+)/?$")
_X_RE = re.compile(
    r"^https?://(?:www\.)?(?:x\.com|twitter\.com)/(?P<user>[^/]+)/status/(?P<id>\d+)"
)

FetchJson = Callable[[str], dict[str, Any]]


class SocialFetchError(RuntimeError):
    """Raised when a matched social post cannot be fetched or parsed."""


@dataclass(frozen=True, slots=True)
class SocialPost:
    """One fetched social post with its raw API evidence."""

    platform: str
    post_id: str
    url: str
    author_name: str
    author_handle: str
    created_at: str
    text: str
    raw: dict[str, Any] = field(default_factory=dict)


def match_social_url(url: str) -> str | None:
    """Return the platform name for a recognized social-post URL."""

    if _BLUESKY_RE.match(url):
        return "bluesky"
    if _X_RE.match(url):
        return "x"
    match = _MASTODON_RE.match(url)
    if match and match.group("host") not in {"x.com", "twitter.com", "bsky.app"}:
        return "mastodon"
    return None


def fetch_social_post(url: str, *, fetch_json: FetchJson | None = None) -> SocialPost:
    """Fetch a matched post via its platform adapter (raises SocialFetchError)."""

    fetcher = fetch_json or _default_fetch_json
    platform = match_social_url(url)
    try:
        if platform == "bluesky":
            return _fetch_bluesky(url, fetcher)
        if platform == "mastodon":
            return _fetch_mastodon(url, fetcher)
        if platform == "x":
            return _fetch_x(url, fetcher)
    except SocialFetchError:
        raise
    except Exception as exc:
        raise SocialFetchError(f"social fetch failed for {url}: {exc}") from exc
    raise SocialFetchError(f"not a recognized social post URL: {url}")


def _default_fetch_json(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_SECONDS) as response:
            loaded = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SocialFetchError(f"social fetch failed for {url}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise SocialFetchError(f"unexpected response shape from {url}")
    return loaded


def _fetch_bluesky(url: str, fetch_json: FetchJson) -> SocialPost:
    match = _BLUESKY_RE.match(url)
    assert match is not None
    actor, rkey = match.group("actor"), match.group("rkey")
    if actor.startswith("did:"):
        did = actor
    else:
        resolved = fetch_json(
            "https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle?handle="
            + urllib.parse.quote(actor, safe="")
        )
        did = str(resolved.get("did") or "")
        if not did:
            raise SocialFetchError(f"could not resolve Bluesky handle: {actor}")
    at_uri = f"at://{did}/app.bsky.feed.post/{rkey}"
    thread = fetch_json(
        "https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread?depth=0&uri="
        + urllib.parse.quote(at_uri, safe="")
    )
    post = (thread.get("thread") or {}).get("post") or {}
    record = post.get("record") or {}
    author = post.get("author") or {}
    text = str(record.get("text") or "").strip()
    if not text and not author:
        raise SocialFetchError(f"empty Bluesky thread response for {url}")
    return SocialPost(
        platform="bluesky",
        post_id=rkey,
        url=url,
        author_name=str(author.get("displayName") or author.get("handle") or actor),
        author_handle=str(author.get("handle") or actor),
        created_at=str(record.get("createdAt") or ""),
        text=text,
        raw=thread,
    )


def _fetch_mastodon(url: str, fetch_json: FetchJson) -> SocialPost:
    match = _MASTODON_RE.match(url)
    assert match is not None
    host, status_id = match.group("host"), match.group("id")
    status = fetch_json(f"https://{host}/api/v1/statuses/{status_id}")
    account = status.get("account") or {}
    text = strip_html(str(status.get("content") or ""))
    if not text and not account:
        raise SocialFetchError(f"empty Mastodon status response for {url}")
    handle = str(account.get("acct") or match.group("user"))
    if "@" not in handle:
        handle = f"{handle}@{host}"
    return SocialPost(
        platform="mastodon",
        post_id=status_id,
        url=url,
        author_name=str(account.get("display_name") or account.get("username") or handle),
        author_handle=handle,
        created_at=str(status.get("created_at") or ""),
        text=text,
        raw=status,
    )


def _fetch_x(url: str, fetch_json: FetchJson) -> SocialPost:
    match = _X_RE.match(url)
    assert match is not None
    oembed = fetch_json(
        "https://publish.twitter.com/oembed?omit_script=1&url=" + urllib.parse.quote(url, safe="")
    )
    text = strip_html(str(oembed.get("html") or ""))
    if not text:
        raise SocialFetchError(f"empty X oEmbed response for {url}")
    return SocialPost(
        platform="x",
        post_id=match.group("id"),
        url=url,
        author_name=str(oembed.get("author_name") or match.group("user")),
        author_handle=match.group("user"),
        created_at="",  # oEmbed does not expose the post timestamp
        text=text,
        raw=oembed,
    )


def strip_html(markup: str) -> str:
    """Plain text from post HTML: tags out, entities unescaped, spacing sane."""

    no_breaks = re.sub(r"(?i)<\s*(br|/p)\s*/?>", "\n", markup)
    no_tags = re.sub(r"<[^>]+>", "", no_breaks)
    unescaped = html_module.unescape(no_tags)
    lines = [" ".join(line.split()) for line in unescaped.splitlines()]
    return "\n".join(line for line in lines if line).strip()


class SocialProcessor:
    """Render one fetched social post as a quoted, attributed source page."""

    def __init__(self, post: SocialPost) -> None:
        self._post = post

    def process(self, request: Any) -> list[Any]:
        from hermes_wiki.models import WikiPage
        from hermes_wiki.pipeline import GeneratedPage

        post = self._post
        snippet = " ".join(post.text.split())[:60]
        title = f"{post.author_handle} ({post.platform}): {snippet}".rstrip(": ")
        quoted = "\n".join(f"> {line}" for line in post.text.splitlines() if line.strip())
        lines = [
            f"# {title}",
            "",
            quoted or "> *(no text content)*",
            "",
            f"- Platform: {post.platform}",
            f"- Author: {post.author_name} (@{post.author_handle})",
        ]
        if post.created_at:
            lines.append(f"- Posted: {post.created_at}")
        lines.extend(
            [
                f"- Origin: [{post.url}]({post.url})",
                f"- Evidence: fetched API response at `{request.snapshot_relpath}`",
                "",
                "Quoted text is the author's; commentary belongs in your own pages "
                "per the wiki-media-ingestion social protocol.",
            ]
        )
        page = WikiPage(
            id=request.source_page_id,
            title=title,
            type="source",
            body="\n".join(lines),
            tags=("ingest", "social", post.platform),
            sources=(request.snapshot_relpath,),
            confidence=request.label.confidence,
        )
        return [GeneratedPage(page)]


__all__ = [
    "FETCH_TIMEOUT_SECONDS",
    "SocialFetchError",
    "SocialPost",
    "SocialProcessor",
    "fetch_social_post",
    "match_social_url",
    "strip_html",
]
