"""YouTube ingestion (media design PR6 / D8): notes by default, captions opt-in.

Policy-first modality. YouTube's Developer Policies prohibit storing copies of
audiovisual content and cap most stored API data at 30-day retention — both
incompatible with append-only snapshots. So:

- ``notes`` (default): only public oEmbed metadata is snapshotted (citation
  metadata, not content); knowledge capture is agent-side watch-and-note with
  citations anchoring to YouTube itself (``…&t=<seconds>s``).
- ``captions`` (opt-in via ``wiki.media.youtube``): existing captions are
  fetched through yt-dlp (``hermes-wiki[youtube]``) into a derived transcript
  with the retrieval method stamped in the manifest. The operator enabled
  this knowingly.
- Audio/video download is never available here (build-your-own-plugin
  territory, per the design).
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from hermes_wiki import social
from hermes_wiki.social import SocialFetchError

_WATCH_RE = re.compile(
    r"^https?://(?:www\.|m\.)?youtube\.com/watch\?(?:[^#]*&)?v=(?P<id>[A-Za-z0-9_-]{6,})"
)
_SHORT_RE = re.compile(r"^https?://youtu\.be/(?P<id>[A-Za-z0-9_-]{6,})")
_SHORTS_RE = re.compile(
    r"^https?://(?:www\.|m\.)?youtube\.com/shorts/(?P<id>[A-Za-z0-9_-]{6,})"
)

#: (start_seconds, end_seconds, text) caption segments.
CaptionSegments = list[tuple[float, float, str]]
CaptionFetcher = Callable[[str], "tuple[CaptionSegments, dict[str, Any]]"]


@dataclass(frozen=True, slots=True)
class YouTubeMetadata:
    """Public oEmbed citation metadata for one video."""

    video_id: str
    url: str
    title: str
    channel: str
    channel_url: str
    raw: dict[str, Any] = field(default_factory=dict)


def match_youtube_url(url: str) -> str | None:
    """Return the video id for a recognized YouTube URL."""

    for pattern in (_WATCH_RE, _SHORT_RE, _SHORTS_RE):
        match = pattern.match(url)
        if match:
            return match.group("id")
    return None


def fetch_metadata(
    url: str,
    video_id: str,
    *,
    fetch_json: Callable[[str], dict[str, Any]] | None = None,
) -> YouTubeMetadata:
    """Fetch public oEmbed metadata (title/channel) for a video."""

    fetcher = fetch_json or social._default_fetch_json
    oembed = fetcher(
        "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(url, safe="")
    )
    title = str(oembed.get("title") or "").strip()
    if not title:
        raise SocialFetchError(f"empty YouTube oEmbed response for {url}")
    return YouTubeMetadata(
        video_id=video_id,
        url=f"https://www.youtube.com/watch?v={video_id}",
        title=title,
        channel=str(oembed.get("author_name") or "unknown channel"),
        channel_url=str(oembed.get("author_url") or ""),
        raw=oembed,
    )


def default_caption_fetcher_or_none() -> CaptionFetcher | None:
    """Return the yt-dlp caption fetcher when the extra is installed."""

    import importlib.util

    if importlib.util.find_spec("yt_dlp") is None:
        return None
    return _fetch_captions_ytdlp


def _fetch_captions_ytdlp(url: str) -> tuple[CaptionSegments, dict[str, Any]]:
    """Fetch existing captions via yt-dlp (manual preferred over automatic)."""

    import json

    import yt_dlp  # ty: ignore[unresolved-import]

    options = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)

    for kind, table in (("manual", info.get("subtitles") or {}),
                        ("automatic", info.get("automatic_subtitles") or
                         info.get("automatic_captions") or {})):
        for language in sorted(table, key=lambda lang: (not lang.startswith("en"), lang)):
            entries = table[language]
            json3 = next(
                (entry for entry in entries if entry.get("ext") == "json3"), None
            )
            vtt = next((entry for entry in entries if entry.get("ext") == "vtt"), None)
            chosen = json3 or vtt
            if not chosen or not chosen.get("url"):
                continue
            with urllib.request.urlopen(chosen["url"], timeout=15) as response:
                payload = response.read().decode("utf-8", errors="replace")
            segments = (
                _parse_json3(json.loads(payload)) if chosen is json3 else _parse_vtt(payload)
            )
            if segments:
                import importlib.metadata

                meta = {
                    "retrieval": "yt-dlp",
                    "language": language,
                    "kind": kind,
                    "tool_version": importlib.metadata.version("yt-dlp"),
                }
                return segments, meta
    raise SocialFetchError(f"no captions available for {url}")


def _parse_json3(payload: dict[str, Any]) -> CaptionSegments:
    segments: CaptionSegments = []
    for event in payload.get("events") or []:
        text = "".join(seg.get("utf8", "") for seg in event.get("segs") or []).strip()
        if not text:
            continue
        start = float(event.get("tStartMs", 0)) / 1000.0
        duration = float(event.get("dDurationMs", 0)) / 1000.0
        segments.append((start, start + duration, " ".join(text.split())))
    return segments


_VTT_TIME_RE = re.compile(
    r"(?P<sh>\d+):(?P<sm>\d{2}):(?P<ss>\d{2})\.(?P<sms>\d{3})\s*-->\s*"
    r"(?P<eh>\d+):(?P<em>\d{2}):(?P<es>\d{2})\.(?P<ems>\d{3})"
)


def _parse_vtt(payload: str) -> CaptionSegments:
    segments: CaptionSegments = []
    current: tuple[float, float] | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal current, buffer
        if current is not None and buffer:
            text = " ".join(" ".join(buffer).split())
            text = re.sub(r"<[^>]+>", "", text).strip()
            if text:
                segments.append((current[0], current[1], text))
        current, buffer = None, []

    for line in payload.splitlines():
        match = _VTT_TIME_RE.search(line)
        if match:
            flush()
            start = (
                int(match["sh"]) * 3600 + int(match["sm"]) * 60 + int(match["ss"])
            ) + int(match["sms"]) / 1000.0
            end = (
                int(match["eh"]) * 3600 + int(match["em"]) * 60 + int(match["es"])
            ) + int(match["ems"]) / 1000.0
            current = (start, end)
        elif not line.strip():
            flush()
        elif current is not None and not line.strip().isdigit():
            buffer.append(line.strip())
    flush()
    return segments


class YoutubeNotesProcessor:
    """Watch-and-note source page from oEmbed citation metadata (D8 default)."""

    def __init__(self, meta: YouTubeMetadata) -> None:
        self._meta = meta

    def process(self, request: Any) -> list[Any]:
        from hermes_wiki.models import WikiPage
        from hermes_wiki.pipeline import GeneratedPage

        meta = self._meta
        lines = [
            f"# {meta.title}",
            "",
            f"YouTube video by [{meta.channel}]({meta.channel_url or meta.url}).",
            "",
            f"- Origin: [{meta.url}]({meta.url})",
            f"- Evidence: oEmbed citation metadata at `{request.snapshot_relpath}`",
            "",
            "## Notes",
            "",
            "*(watch-and-note: extend this section with timestamped notes — your",
            "interpretation, never bulk transcript content. Cite moments against",
            f"YouTube itself: `([source @ 12:34]({meta.url}&t=754s))`.)*",
        ]
        page = WikiPage(
            id=request.source_page_id,
            title=meta.title,
            type="source",
            body="\n".join(lines),
            tags=("ingest", "youtube"),
            sources=(request.snapshot_relpath,),
            confidence=request.label.confidence,
        )
        return [GeneratedPage(page)]


class YoutubeCaptionsProcessor:
    """Opt-in captions mode: derived transcript with retrieval provenance."""

    def __init__(
        self,
        meta: YouTubeMetadata,
        segments: CaptionSegments,
        caption_meta: dict[str, Any],
    ) -> None:
        self._meta = meta
        self._segments = segments
        self._caption_meta = caption_meta

    def process(self, request: Any) -> list[Any]:
        from hermes_wiki.media_processors import _render_transcript, _timestamp
        from hermes_wiki.models import WikiPage
        from hermes_wiki.pipeline import DerivedArtifact, GeneratedPage

        meta, segments = self._meta, self._segments
        base = request.manifest_relpath.rsplit("/", 1)[0] if request.manifest_relpath else ""
        transcript_rel = f"{base}/transcript.md" if base else "transcript.md"
        duration = segments[-1][1] if segments else 0.0
        lines = [
            f"# {meta.title}",
            "",
            f"YouTube video by [{meta.channel}]({meta.channel_url or meta.url}); "
            f"captions fetched to [transcript.md](../{transcript_rel}) "
            f"({len(segments)} segments, ~{_timestamp(duration)}).",
            "",
            f"- Origin: [{meta.url}]({meta.url})",
            f"- Provenance: [Derived Manifest](../{request.manifest_relpath})"
            if request.manifest_relpath
            else f"- Evidence: `{request.snapshot_relpath}`",
            "- Captions mode is operator-enabled (see the youtube protocol); "
            "verify load-bearing quotes against the moment on YouTube.",
        ]
        page = WikiPage(
            id=request.source_page_id,
            title=meta.title,
            type="source",
            body="\n".join(lines),
            tags=("ingest", "youtube"),
            sources=(request.manifest_relpath or request.snapshot_relpath,),
            confidence=request.label.confidence,
        )
        caption_meta = dict(self._caption_meta)
        version = str(caption_meta.pop("tool_version", "unknown"))
        return [
            DerivedArtifact(
                relpath="transcript.md",
                content=_render_transcript(meta.title, "youtube-captions", segments),
                tool="yt-dlp",
                version=version,
                details={"segments": len(segments), **caption_meta},
            ),
            GeneratedPage(page),
        ]


__all__ = [
    "CaptionSegments",
    "YouTubeMetadata",
    "YoutubeCaptionsProcessor",
    "YoutubeNotesProcessor",
    "default_caption_fetcher_or_none",
    "fetch_metadata",
    "match_youtube_url",
]
