"""Fetch synced lyrics from LRCLib API.

LRCLib is a free, open-source synchronized lyrics database.
API docs: https://lrclib.net/docs
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import requests

from bhajan.logger import StageLogger, console
from bhajan.stages.transcription_base import Segment, Transcript, WordStamp

log = logging.getLogger("bhajan")
stage = StageLogger(log, "lyrics-fetch")

LRCLIB_API_BASE = "https://lrclib.net/api"
USER_AGENT = "bhajan/0.1.0 (https://github.com/)"

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": USER_AGENT})


@dataclass(frozen=True)
class LyricsMatch:
    """One reviewable online-lyrics result."""

    transcript: Transcript
    track_name: str
    artist_name: str = ""
    album_name: str = ""
    duration: float | None = None
    record_id: int | None = None
    source: str = "LRCLib"


def fetch_lyrics_match_from_youtube_title(
    title: str,
    artist_meta: str | None,
    duration: float | None,
    album_youtube: str | None = None,
) -> tuple[LyricsMatch | None, str]:
    """Resolve a reviewable lyrics match and return its parsed track query."""
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
    return _fetch_lrclib_strategies(track, artist, album, duration), track


def fetch_lyrics_from_youtube_title(
    title: str,
    artist_meta: str | None,
    duration: float | None,
    album_youtube: str | None = None,
) -> Transcript | None:
    """Resolve LRCLib lyrics using heuristics tuned for YouTube music video titles."""
    match, _track = fetch_lyrics_match_from_youtube_title(
        title,
        artist_meta,
        duration,
        album_youtube,
    )
    return match.transcript if match is not None else None


def fetch_lyrics_by_metadata(
    track_name: str,
    artist_name: str,
    duration: float | None = None,
    album_name: str | None = None,
) -> Transcript | None:
    """Fetch synced lyrics using explicit track / artist / album (legacy helper)."""
    match = _fetch_lrclib_strategies(
        track_name.strip() or "Unknown",
        artist_name.strip() if artist_name else "",
        album_name.strip() if album_name else "",
        duration,
    )
    return match.transcript if match is not None else None


def _fetch_lrclib_strategies(
    track: str,
    artist: str,
    album: str,
    duration: float | None,
) -> LyricsMatch | None:
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


def _try_get(track: str, artist: str, album: str, duration: int) -> LyricsMatch | None:
    """GET /api/get (may hit external sources; slower)."""
    return _get_endpoint(f"{LRCLIB_API_BASE}/get", track, artist, album, duration)


def _try_get_cached(track: str, artist: str, album: str, duration: int) -> LyricsMatch | None:
    """GET /api/get-cached (internal DB only)."""
    return _get_endpoint(f"{LRCLIB_API_BASE}/get-cached", track, artist, album, duration)


def _get_endpoint(
    url: str,
    track: str,
    artist: str,
    album: str,
    duration: int,
) -> LyricsMatch | None:
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
        return _match_from_lrclib_payload(data)
    except requests.RequestException as e:
        stage.debug("GET %s failed: %s", url, e)
        return None


def _match_from_lrclib_payload(
    data: dict,
    *,
    source: str = "LRCLib",
    announce: bool = True,
) -> LyricsMatch | None:
    if data.get("instrumental"):
        stage.info("Track is instrumental, no lyrics available")
        return None
    synced = data.get("syncedLyrics")
    if synced:
        if announce:
            stage.info(
                "Found synced lyrics (LRCLib): %r by %r",
                data.get("trackName"),
                data.get("artistName"),
            )
        transcript = _parse_lrc(synced, announce=announce)
        return LyricsMatch(
            transcript=transcript,
            track_name=str(data.get("trackName") or data.get("name") or "Unknown"),
            artist_name=str(data.get("artistName") or ""),
            album_name=str(data.get("albumName") or ""),
            duration=float(data["duration"]) if isinstance(data.get("duration"), (int, float)) else None,
            record_id=data.get("id") if isinstance(data.get("id"), int) else None,
            source=source,
        )
    plain = data.get("plainLyrics")
    if plain:
        if announce:
            stage.warning("Only plain lyrics available (no timestamps)")
        transcript = _parse_plain_lyrics(plain)
        return LyricsMatch(
            transcript=transcript,
            track_name=str(data.get("trackName") or data.get("name") or "Unknown"),
            artist_name=str(data.get("artistName") or ""),
            album_name=str(data.get("albumName") or ""),
            duration=float(data["duration"]) if isinstance(data.get("duration"), (int, float)) else None,
            record_id=data.get("id") if isinstance(data.get("id"), int) else None,
            source=source,
        )
    return None


def _transcript_from_lrclib_payload(data: dict) -> Transcript | None:
    """Compatibility helper for callers that only need the transcript."""
    match = _match_from_lrclib_payload(data)
    return match.transcript if match is not None else None


def _search_ranked(
    track: str,
    artist: str,
    album: str,
    duration: float | None,
) -> LyricsMatch | None:
    """Run several /api/search queries and pick the best synced match."""
    queries: list[tuple[dict[str, str], str, float]] = []

    q_plain = f"{track} {artist}".strip() if artist else track
    queries.append(({"q": q_plain}, track, 0.0))
    queries.append(({"q": track}, track, 0.0))
    if album:
        queries.append(({"q": f"{track} {album}"}, track, 0.0))
        queries.append(({"track_name": track, "album_name": album}, track, 0.0))
    if artist:
        queries.append(({"track_name": track, "artist_name": artist}, track, 0.0))

    seen_urls: set[str] = set()
    best: tuple[float, dict] | None = None

    def run_queries(items: list[tuple[dict[str, str], str, float]]) -> None:
        nonlocal best
        for params, track_guess, penalty in items:
            try:
                r = _SESSION.get(
                    f"{LRCLIB_API_BASE}/search",
                    params={**params, "limit": "20"},
                    timeout=15,
                )
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
                score = _score_record(rec, track_guess, album, artist, duration) - penalty
                if best is None or score > best[0]:
                    best = (score, rec)

    run_queries(queries)

    # Some Indian-label uploads quote the song and film as one title, e.g.
    # "Senorita Zindagi Na Milegi Dobara" Full HD Video Song. If the precise
    # search misses, progressively shorten that phrase and let duration/album
    # ranking disambiguate the result.
    if best is None:
        aliases = _short_track_aliases(track)
        original_words = len(re.findall(r"[\wÀ-ž]+", track, flags=re.UNICODE))
        run_queries(
            [
                (
                    {"q": alias},
                    alias,
                    15.0
                    * max(
                        0,
                        original_words
                        - len(re.findall(r"[\wÀ-ž]+", alias, flags=re.UNICODE)),
                    ),
                )
                for alias in aliases
            ]
        )

    if best is None or best[0] < 75.0:
        if best is not None:
            stage.info("Rejected weak LRCLib search match (score=%.1f)", best[0])
        return None

    rec = best[1]
    stage.info(
        "Found lyrics via search (score=%.1f): %r by %r (%r)",
        best[0],
        rec.get("trackName"),
        rec.get("artistName"),
        rec.get("albumName"),
    )
    return _match_from_lrclib_payload(rec)


def _short_track_aliases(track: str) -> list[str]:
    """Return conservative prefix searches for noisy quoted video titles."""
    words = re.findall(r"[\wÀ-ž]+", track, flags=re.UNICODE)
    if len(words) < 4:
        return []

    max_words = min(3, len(words) - 1)
    aliases: list[str] = []
    for count in range(max_words, 0, -1):
        alias = " ".join(words[:count]).strip()
        if alias and alias.casefold() != track.casefold():
            aliases.append(alias)
    return aliases


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


def search_lyrics_matches(
    query: str,
    duration: float | None = None,
    *,
    limit: int = 8,
) -> list[LyricsMatch]:
    """Return reviewable synced LRCLib candidates for a user-entered query."""
    query = query.strip()
    if not query:
        return []

    try:
        response = _SESSION.get(
            f"{LRCLIB_API_BASE}/search",
            params={"q": query, "limit": str(max(limit * 3, 20))},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        stage.warning("Could not search LRCLib: %s", exc)
        return []

    if not isinstance(payload, list):
        return []

    ranked: list[tuple[float, LyricsMatch]] = []
    seen: set[int | str] = set()
    for record in payload:
        if not isinstance(record, dict) or not record.get("syncedLyrics"):
            continue
        key: int | str = record.get("id") or (
            f"{record.get('trackName')}|{record.get('artistName')}|{record.get('albumName')}"
        )
        if key in seen:
            continue
        seen.add(key)
        match = _match_from_lrclib_payload(record, announce=False)
        if match is None:
            continue
        score = _score_record(record, query, "", "", duration)
        ranked.append((score, match))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [match for _score, match in ranked[:limit]]


def fetch_lyrics_match_from_url(url: str) -> LyricsMatch:
    """Load lyrics from an LRCLib API URL or a direct UTF-8 LRC/text URL.

    Generic lyrics webpages are deliberately rejected: their HTML is not a
    stable or trustworthy lyrics format.  A direct ``.lrc``/``.txt``/raw text
    URL is supported, as is ``https://lrclib.net/api/get/<id>``.
    """
    value = url.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Lyrics URL must start with http:// or https://.")

    is_lrclib = parsed.netloc.casefold() in {"lrclib.net", "www.lrclib.net"}
    if is_lrclib and re.fullmatch(r"/api/get/\d+/?", parsed.path):
        try:
            response = _SESSION.get(value, timeout=20)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ValueError(f"Could not load that LRCLib URL: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("LRCLib returned an unexpected response.")
        match = _match_from_lrclib_payload(payload)
        if match is None:
            raise ValueError("That LRCLib record has no usable lyrics.")
        return match

    try:
        response = _SESSION.get(value, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ValueError(f"Could not download that lyrics URL: {exc}") from exc

    content_type = response.headers.get("Content-Type", "").casefold()
    if "html" in content_type:
        raise ValueError(
            "Webpage links are not supported. Paste a direct .lrc/.txt URL "
            "or an LRCLib /api/get/<id> URL."
        )

    text = response.text.strip()
    if not text:
        raise ValueError("The lyrics URL returned an empty file.")
    if len(text) > 2_000_000:
        raise ValueError("The lyrics file is unexpectedly large.")

    if re.search(r"(?m)^\[\d{2}:\d{2}\.\d{2}\]", text):
        transcript = _parse_lrc(text)
        if not transcript.segments:
            raise ValueError("No timestamped lyric lines were found in the LRC file.")
    else:
        transcript = _parse_plain_lyrics(text)

    name = Path(parsed.path).name or "Linked lyrics"
    return LyricsMatch(transcript=transcript, track_name=name, source=parsed.netloc)


def review_online_lyrics(
    initial: LyricsMatch,
    *,
    search_query: str,
    duration: float | None,
    input_func: Callable[[str], str] = input,
) -> LyricsMatch | None:
    """Interactively confirm or replace an online lyrics match.

    Returning ``None`` means the caller should transcribe the vocals instead.
    ``input_func`` is injectable so the terminal flow can be unit-tested.
    """
    current = initial
    while True:
        _print_match_preview(current)
        answer = input_func(
            "Use these online lyrics? "
            "[Y]es / [L]ist alternatives / [T]ype title / lyrics [U]RL / [W]hisper: "
        ).strip().casefold()

        if answer in {"", "y", "yes"}:
            return current
        if answer in {"w", "whisper", "n", "no"}:
            return None
        if answer in {"l", "list"}:
            contextual_query = " ".join(
                part
                for part in (
                    search_query,
                    current.artist_name,
                    current.album_name,
                )
                if part
            )
            selected = _prompt_for_candidate(
                search_lyrics_matches(contextual_query, duration),
                input_func=input_func,
            )
            if selected is not None:
                current = selected
            continue
        if answer in {"t", "title"}:
            corrected = input_func("Enter the song title (artist optional): ").strip()
            if not corrected:
                console.print("[yellow]No title entered.[/]")
                continue
            selected = _prompt_for_candidate(
                search_lyrics_matches(corrected, duration),
                input_func=input_func,
            )
            if selected is not None:
                current = selected
                search_query = corrected
            continue
        if answer in {"u", "url", "link"}:
            url = input_func(
                "Paste a direct .lrc/.txt URL or LRCLib /api/get/<id> URL: "
            ).strip()
            try:
                current = fetch_lyrics_match_from_url(url)
            except ValueError as exc:
                console.print(f"[yellow]{exc}[/]")
            continue

        console.print("[yellow]Please choose Y, L, T, U, or W.[/]")


def _print_match_preview(match: LyricsMatch) -> None:
    artist = f" — {match.artist_name}" if match.artist_name else ""
    album = f" ({match.album_name})" if match.album_name else ""
    console.print("\n[bold cyan]Online lyrics found:[/]")
    console.print(f"  [bold]{match.track_name}[/]{artist}{album}")
    console.print(f"  [dim]Source: {match.source}[/]")
    preview = [segment.text.strip() for segment in match.transcript.segments if segment.text.strip()]
    for line in preview[:3]:
        shown = line if len(line) <= 100 else f"{line[:97]}..."
        console.print(f"    {shown}")
    console.print()


def _prompt_for_candidate(
    matches: list[LyricsMatch],
    *,
    input_func: Callable[[str], str],
) -> LyricsMatch | None:
    if not matches:
        console.print("[yellow]No synchronized LRCLib results found.[/]")
        return None

    console.print("\n[bold cyan]Possible lyric matches:[/]")
    for index, match in enumerate(matches, start=1):
        artist = f" — {match.artist_name}" if match.artist_name else ""
        album = f" ({match.album_name})" if match.album_name else ""
        duration = f" [{_format_duration(match.duration)}]" if match.duration else ""
        console.print(f"  {index}. {match.track_name}{artist}{album}{duration}")
    console.print("  0. Go back")

    while True:
        raw = input_func(f"Choose 0-{len(matches)}: ").strip()
        if raw.isdigit() and 0 <= int(raw) <= len(matches):
            choice = int(raw)
            return None if choice == 0 else matches[choice - 1]
        console.print(f"[yellow]Enter a number from 0 to {len(matches)}.[/]")


def _format_duration(duration: float) -> str:
    total = max(0, int(round(duration)))
    return f"{total // 60}:{total % 60:02d}"


def _parse_lrc(lrc_text: str, *, announce: bool = True) -> Transcript:
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

    if announce:
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
