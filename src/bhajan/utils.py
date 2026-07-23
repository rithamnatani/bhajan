"""Utility helpers (safe names, path helpers, etc.)."""

from __future__ import annotations

import re
from pathlib import Path


# Common prefixes/suffixes to strip from YouTube titles for cleaner metadata
YT_TITLE_PREFIXES = [
    r"^Mix\s*-\s*",
    r"^Playlist\s*-\s*",
    r"^Compilation\s*-\s*",
    r"^Best of\s*-\s*",
    r"^Top\s*\d+\s*-\s*",
]

YT_TITLE_SUFFIXES = [
    r"\s*\|\s*Official\s*(Video|Audio|Music\s*Video)",
    r"\s*\|\s*Lyrics?\s*(Video)?",
    r"\s*\|\s*Visualizer",
    r"\s*-\s*Official\s*(Video|Audio|Music\s*Video)",
    r"\s*-\s*Lyrics?\s*(Video)?",
    r"\s*\(Official\s*(Video|Audio|Music\s*Video)\)",
    r"\s*\(Lyrics?\s*(Video)?\)",
    r"\s*\[Official\s*(Video|Audio|Music\s*Video)\]",
    r"\s*\[Lyrics?\s*(Video)?\]",
    r"\s*\(\s*\d{4}\s*\)",  # (year)
    r"\s*\|\s*\d{4}\s*$",  # | year at end
    r"\s*\(?\s*(?:ft|feat)\.?\s+[^)]+\)?\s*$",  # ft./feat. credits
    r"\s*\(Visualiser\)",
    r"\s*\(Visualizer\)",
]


def clean_track_name(title: str) -> str:
    """Clean YouTube title to extract actual track name.

    Removes common prefixes like 'Mix - ' and suffixes like ' | Official Video'.
    """
    cleaned = title.strip()

    # Remove prefixes
    for pattern in YT_TITLE_PREFIXES:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    # Remove suffixes
    for pattern in YT_TITLE_SUFFIXES:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    return cleaned.strip()


# YouTube channel / label segments (often last in "Title | Movie | Label")
_YT_LABEL_SEGMENT = re.compile(
    r"(?i)^(T-Series|T-Series\s*Films|Sony Music|Sony Music India|Zee Music Company|"
    r"YRF Music|YRF\s*-\s*Films|Tips Official|Speed Records|"
    r"Saregama GenY|Universal Music India|Times Music|"
    r".*\bVEVO\s*$|.*\sOfficial\s*Channel\s*$|.*\sMusic\s*Official\s*$)$",
)

# Strip from individual title segments (not full clean_track_name pass)
_TITLE_SEGMENT_NOISE = re.compile(
    r"(?i)(\s*['\"]|['\"]\s*)|"
    r"\bFull\s+VIDEO\s+Song\b|"
    r"\bOfficial\s+(Music\s+)?Video\b|"
    r"\bOfficial\s+Audio\b|"
    r"\bLyrics?\s*(Video)?\b|"
    r"\bAUDIO\s+Song\b|"
    r"\b4K\b|\bHD\b|\bHDR\b"
)


def extract_quoted_phrase(title: str) -> str | None:
    """Return text inside first single- or double-quoted span, if any."""
    m = re.search(r"['\"]([^'\"]{2,120})['\"]", title)
    return m.group(1).strip() if m else None


def strip_segment_noise(segment: str) -> str:
    """Remove trailer noise from one ``|``-separated segment."""
    s = segment.strip()
    s = _TITLE_SEGMENT_NOISE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip(" '\"-")


def is_label_segment(segment: str) -> bool:
    """True if *segment* looks like a channel/label, not song or movie."""
    s = segment.strip()
    if len(s) < 2:
        return True
    if _YT_LABEL_SEGMENT.match(s):
        return True
    if re.match(r"(?i)^[\w\s]+Music$", s) and len(s) < 50:
        return True
    return False


def metadata_for_lrclib(title: str, artist_meta: str | None) -> tuple[str, str, str]:
    """Extract (track_name, artist_name, album_name) for LRCLib from a YouTube title.

    Handles common Indian film promo patterns such as
    ``'Song' Full VIDEO Song | Movie | T-Series`` where the song title is quoted
    and the movie name is a middle ``|`` segment (not "artist - title").
    """
    raw = title.strip()
    quoted = extract_quoted_phrase(raw)

    segments = [s.strip() for s in re.split(r"\s*\|\s*", raw) if s.strip()]
    while segments and (
        is_label_segment(segments[-1]) or not strip_segment_noise(segments[-1])
    ):
        segments.pop()

    track = ""
    album = ""
    inferred_artist = ""

    # Indian film uploads commonly use:
    #   Movie - Song feat Actor & Actor | Composer
    # Here ``feat`` names the people in the video, not musical collaborators.
    # Treat the left side as the film/album, the right side as the song, and the
    # next pipe segment as the musical artist.  Without this rule, a broad
    # fallback for "Bang Bang" can select an unrelated English song.
    movie_song = None
    if not quoted and segments:
        movie_song = re.match(
            r"(?i)^(.+?)\s+-\s+(.+?)\s+(?:ft|feat)\.?\s+.+$",
            strip_segment_noise(segments[0]),
        )
    if movie_song and len(segments) >= 2:
        album = movie_song.group(1).strip()
        track = movie_song.group(2).strip()
        inferred_artist = strip_segment_noise(segments[1])

    if quoted:
        track = quoted
    elif not track and segments:
        track = strip_segment_noise(segments[0])

    # Album / film: typically the next non-label segment after the title segment
    if not album and len(segments) >= 2:
        for seg in segments[1:]:
            if is_label_segment(seg):
                continue
            cand = strip_segment_noise(seg)
            if cand and cand.lower() != (track or "").lower():
                album = cand
                break

    if not track and segments:
        track = strip_segment_noise(segments[0])

    track = track.strip() or "Unknown"

    artist = ""
    if artist_meta and str(artist_meta).strip().lower() not in ("unknown", "none", ""):
        am = str(artist_meta).strip()
        if len(am) < 100 and "|" not in am and "VIDEO" not in am.upper():
            artist = am
    elif inferred_artist:
        artist = inferred_artist

    return track, artist, album


def parse_artist_and_title(title: str, artist_meta: str | None = None) -> tuple[str, str]:
    """Parse artist and title from YouTube metadata.

    Args:
        title: YouTube video title
        artist_meta: Artist from YouTube metadata if available

    Returns:
        Tuple of (artist_name, track_name)
    """
    # If artist is provided in metadata, use it
    if artist_meta and artist_meta != "unknown":
        track = clean_track_name(title)
        return artist_meta, track

    # Try to parse "Artist - Title" format
    cleaned = clean_track_name(title)

    # Look for common separator patterns
    separators = [" - ", " | ", " ~ ", " – ", " — " ]
    for sep in separators:
        if sep in cleaned:
            parts = cleaned.split(sep, 1)
            if len(parts) == 2:
                artist = parts[0].strip()
                track = parts[1].strip()
                # Validate: artist should be reasonably short, track longer
                if 2 < len(artist) < 100 and len(track) > 1:
                    return artist, track

    # Fallback: return unknown artist and cleaned title
    return "unknown", cleaned


def clean_youtube_url(url: str) -> str:
    """Clean YouTube URL by removing tracking parameters.

    Strips everything after the first & to remove list, index, etc.
    Keeps only the core video ID.

    Examples:
        https://youtube.com/watch?v=ABC123&list=... → https://youtube.com/watch?v=ABC123
        https://youtu.be/ABC123?t=30 → https://youtu.be/ABC123
    """
    # Strip everything after first & (query params)
    if "&" in url:
        url = url.split("&")[0]
    # Strip hash fragments
    if "#" in url:
        url = url.split("#")[0]
    return url.strip()


# Treat as a stream URL (YouTube or any http(s) link) so the pipeline / yt-dlp runs.
# Everything else is handled as a fuzzy local library search against ./output.
_YT_HOST = re.compile(
    r"(?i)(?:^|[/\s@])(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)\b",
)


def looks_like_stream_url(text: str) -> bool:
    """Return True if *text* should be passed to the download pipeline.

    Heuristic (intentionally simple):

    - Any string starting with ``http://`` or ``https://`` is treated as a URL
      (YouTube or otherwise — yt-dlp may still reject non-YouTube hosts).
    - A **scheme-less** YouTube host (``youtube.com/...``, ``youtu.be/...``,
      optional ``www.``, ``m.``, ``music.``) is treated as a URL so shortened
      links pasted without ``https://`` still work.

    Song titles that happen to contain the substring ``youtube`` but not as a
    host (e.g. "youtube mashup mix") are still treated as **local search**;
    host detection requires a slash or start-anchored host pattern.

    Examples:
        ``https://youtu.be/abc`` → True
        ``youtu.be/abc`` → True
        ``shoota playboi`` → False
    """
    q = text.strip()
    if not q:
        return False
    if re.match(r"https?://", q, re.I):
        return True
    if _YT_HOST.search(q):
        return True
    return False


def safe_filename(name: str, max_len: int = 80) -> str:
    """Return a filesystem-safe version of *name*.

    Strips characters that are problematic on Windows / POSIX and truncates
    to *max_len*.
    """
    # Replace anything not alphanumeric, dash, underscore, or space with _
    safe = re.sub(r"[^\w\-_ ]", "_", name)
    # Collapse multiple underscores / spaces
    safe = re.sub(r"[_ ]{2,}", "_", safe).strip("_ ")
    # Truncate and strip again in case truncation left trailing space
    safe = safe[:max_len].rstrip("_ ")
    return safe or "unnamed"


def ensure_dirs(root: Path, subdirs: list[str]) -> None:
    """Create *root* and each sub-directory if missing."""
    root.mkdir(parents=True, exist_ok=True)
    for d in subdirs:
        (root / d).mkdir(parents=True, exist_ok=True)


def first_file(paths: list[Path], *, must_exist: bool = True) -> Path | None:
    """Return the first path that exists, or None."""
    for p in paths:
        if not must_exist or p.exists():
            return p
    return None
