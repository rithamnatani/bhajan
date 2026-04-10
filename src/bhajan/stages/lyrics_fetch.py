"""Fetch synced lyrics from LRCLib API.

LRCLib is a free, open-source synchronized lyrics database.
API docs: https://lrclib.net/docs
"""

from __future__ import annotations

import difflib
import logging
import re
from pathlib import Path

import requests

from bhajan.logger import StageLogger
from bhajan.stages.transcription_base import Segment, Transcript, WordStamp

log = logging.getLogger("bhajan")
stage = StageLogger(log, "lyrics-fetch")

LRCLIB_API_BASE = "https://lrclib.net/api"
USER_AGENT = "bhajan/0.1.0 (https://github.com/)"

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": USER_AGENT})


def fetch_lyrics_from_youtube_title(
    title: str,
    artist_meta: str | None,
    duration: float | None,
    album_youtube: str | None = None,
) -> Transcript | None:
    """Resolve LRCLib lyrics using heuristics tuned for YouTube music video titles."""
    from bhajan.utils import metadata_for_lrclib  # noqa: PLC0415

    track, artist, album = metadata_for_lrclib(title, artist_meta)
    if album_youtube and str(album_youtube).strip():
        album = album or str(album_youtube).strip()

    stage.info(
        "LRCLib title parse: track=%r  artist=%r  album=%r  duration=%s",
        track,
        artist,
        album,
        f"{duration:.0f}s" if duration else "n/a",
    )

    return _fetch_lrclib_strategies(track, artist, album, duration)


def fetch_lyrics_by_metadata(
    track_name: str,
    artist_name: str,
    duration: float | None = None,
    album_name: str | None = None,
) -> Transcript | None:
    """Fetch synced lyrics using explicit track / artist / album (legacy helper)."""
    return _fetch_lrclib_strategies(
        track_name.strip() or "Unknown",
        artist_name.strip() if artist_name else "",
        album_name.strip() if album_name else "",
        duration,
    )


def _fetch_lrclib_strategies(
    track: str,
    artist: str,
    album: str,
    duration: float | None,
) -> Transcript | None:
    """Try /get with several signatures, then ranked /search."""
    dur_int = int(round(duration)) if duration is not None else None

    # --- Exact GET (requires track, artist, album, duration per API) ---
    if dur_int is not None:
        seen_triples: set[tuple[str, str, str]] = set()
        attempts: list[tuple[str, str, str]] = []

        def add(t: str, ar: str, al: str) -> None:
            key = (t, ar, al)
            if key not in seen_triples:
                seen_triples.add(key)
                attempts.append(key)

        # Prefer real artist/album when we have them; fall back to Unknown.
        if artist and album:
            add(track, artist, album)
        add(track, artist or "Unknown", album or "Unknown")
        if album:
            add(track, "Unknown", album)
        if artist:
            add(track, artist, "Unknown")
        add(track, "Unknown", "Unknown")

        for t, ar, al in attempts:
            tr = _try_get_cached(t, ar, al, dur_int)
            if tr is not None:
                return tr
            tr = _try_get(t, ar, al, dur_int)
            if tr is not None:
                return tr

    # --- Search fallbacks (no strict duration on API side for search) ---
    tr = _search_ranked(track, artist, album, duration)
    if tr is not None:
        return tr

    stage.info("No LRCLib match after search strategies")
    return None


def _try_get(track: str, artist: str, album: str, duration: int) -> Transcript | None:
    """GET /api/get (may hit external sources; slower)."""
    return _get_endpoint(f"{LRCLIB_API_BASE}/get", track, artist, album, duration)


def _try_get_cached(track: str, artist: str, album: str, duration: int) -> Transcript | None:
    """GET /api/get-cached (internal DB only)."""
    return _get_endpoint(f"{LRCLIB_API_BASE}/get-cached", track, artist, album, duration)


def _get_endpoint(
    url: str,
    track: str,
    artist: str,
    album: str,
    duration: int,
) -> Transcript | None:
    params = {
        "track_name": track,
        "artist_name": artist,
        "album_name": album,
        "duration": duration,
    }
    try:
        r = _SESSION.get(url, params=params, timeout=20)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        return _transcript_from_lrclib_payload(data)
    except requests.RequestException as e:
        stage.debug("GET %s failed: %s", url, e)
        return None


def _transcript_from_lrclib_payload(data: dict) -> Transcript | None:
    if data.get("instrumental"):
        stage.info("Track is instrumental, no lyrics available")
        return None
    synced = data.get("syncedLyrics")
    if synced:
        stage.info(
            "Found synced lyrics (LRCLib): %r by %r",
            data.get("trackName"),
            data.get("artistName"),
        )
        return _parse_lrc(synced)
    plain = data.get("plainLyrics")
    if plain:
        stage.warning("Only plain lyrics available (no timestamps)")
        return _parse_plain_lyrics(plain)
    return None


def _search_ranked(
    track: str,
    artist: str,
    album: str,
    duration: float | None,
) -> Transcript | None:
    """Run several /api/search queries and pick the best synced match."""
    queries: list[dict[str, str]] = []

    q_plain = f"{track} {artist}".strip() if artist else track
    queries.append({"q": q_plain})
    queries.append({"q": track})
    if album:
        queries.append({"q": f"{track} {album}"})
        queries.append({"track_name": track, "album_name": album})
    if artist:
        queries.append({"track_name": track, "artist_name": artist})

    seen_urls: set[str] = set()
    best: tuple[float, dict] | None = None

    for params in queries:
        try:
            r = _SESSION.get(f"{LRCLIB_API_BASE}/search", params={**params, "limit": "20"}, timeout=15)
            if r.status_code != 200:
                continue
            results = r.json()
            if not isinstance(results, list):
                continue
        except requests.RequestException as e:
            stage.debug("Search failed for %s: %s", params, e)
            continue

        url_key = str(sorted(params.items()))
        if url_key in seen_urls:
            continue
        seen_urls.add(url_key)

        for rec in results:
            if not rec.get("syncedLyrics"):
                continue
            score = _score_record(rec, track, album, artist, duration)
            if best is None or score > best[0]:
                best = (score, rec)

    if best is None:
        return None

    rec = best[1]
    stage.info(
        "Found lyrics via search (score=%.1f): %r by %r (%r)",
        best[0],
        rec.get("trackName"),
        rec.get("artistName"),
        rec.get("albumName"),
    )
    return _parse_lrc(rec["syncedLyrics"])


def _score_record(
    rec: dict,
    track_guess: str,
    album_guess: str,
    artist_guess: str,
    duration: float | None,
) -> float:
    """Higher is better."""
    score = 0.0
    tn = (rec.get("trackName") or "").strip()
    an = (rec.get("artistName") or "").strip()
    aln = (rec.get("albumName") or "").strip()

    if tn:
        score += 100.0 * difflib.SequenceMatcher(
            None, tn.lower(), track_guess.lower()
        ).ratio()

    if album_guess and aln:
        if album_guess.lower() in aln.lower() or aln.lower() in album_guess.lower():
            score += 40.0
        else:
            score += 15.0 * difflib.SequenceMatcher(
                None, aln.lower(), album_guess.lower()
            ).ratio()

    if artist_guess and an:
        score += 20.0 * difflib.SequenceMatcher(
            None, an.lower(), artist_guess.lower()
        ).ratio()

    rd = rec.get("duration")
    if duration is not None and isinstance(rd, (int, float)):
        delta = abs(float(rd) - float(duration))
        if delta <= 2.0:
            score += 60.0
        elif delta <= 8.0:
            score += 25.0
        elif delta <= 20.0:
            score += 10.0

    return score


def _parse_lrc(lrc_text: str) -> Transcript:
    """Parse LRC format ([mm:ss.xx]text) into a Transcript.

    Uses the gap between consecutive LRC timestamps to distribute
    word-level timing within each line for smooth karaoke highlighting.
    """
    parsed_lines: list[tuple[float, str, list[str]]] = []
    for line in lrc_text.strip().split("\n"):
        match = re.match(r"\[(\d{2}):(\d{2})\.(\d{2})\](.*)", line)
        if not match:
            continue
        minutes, seconds, centiseconds, text = match.groups()
        start_time = int(minutes) * 60 + int(seconds) + int(centiseconds) / 100
        text = text.strip()
        if not text:
            continue
        words = text.split()
        if words:
            parsed_lines.append((start_time, text, words))

    transcript = Transcript()
    for idx, (start, _text, words) in enumerate(parsed_lines):
        if idx + 1 < len(parsed_lines):
            end = parsed_lines[idx + 1][0]
        else:
            end = start + len(words) * 0.35

        word_dur = max((end - start) / len(words), 0.05)

        word_stamps = []
        for i, word in enumerate(words):
            ws = start + i * word_dur
            we = ws + word_dur
            word_stamps.append(
                WordStamp(
                    word=word,
                    start=round(ws, 3),
                    end=round(min(we, end), 3),
                )
            )
        transcript.segments.append(Segment(words=word_stamps))

    stage.info("Parsed %d segments from LRC", len(transcript.segments))
    return transcript


def _parse_plain_lyrics(text: str) -> Transcript:
    """Parse plain lyrics into a Transcript without timestamps.

    Creates dummy timestamps based on line position.
    """
    transcript = Transcript()
    lines = text.strip().split("\n")

    # Assume ~3 seconds per line as a rough estimate
    base_time = 0.0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        words = line.split()
        word_stamps = []
        for i, word in enumerate(words):
            word_start = base_time + (i * 0.3)
            word_end = word_start + 0.3
            word_stamps.append(
                WordStamp(
                    word=word,
                    start=round(word_start, 3),
                    end=round(word_end, 3),
                )
            )

        if word_stamps:
            transcript.segments.append(Segment(words=word_stamps))
            base_time += 3.0  # Move to next line

    stage.warning("Created transcript from plain lyrics (estimated timing)")
    return transcript
