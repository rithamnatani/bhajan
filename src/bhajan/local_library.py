"""Fuzzy search over previously generated songs under the output directory."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from rapidfuzz import fuzz, process
from rapidfuzz.utils import default_process

from bhajan.config import FFPROBE_BIN
from bhajan import subprocess_utils
from bhajan.logger import console
from bhajan.stages.transcription import load_transcript
from bhajan.stages.transcription_base import Segment, Transcript, WordStamp

log = logging.getLogger("bhajan")

# Combined scorer uses partial_ratio so short queries like "carti" still hit long titles.
_DEFAULT_SCORE_CUTOFF = 55
_AUDIO_FILENAMES = ("instrumental.ogg", "instrumental.wav", "instrumental.m4a")

_TOKEN_SPLIT = re.compile(r"[\s_\-|]+")


def _library_choice_scorer(query: str, choice: str, **kwargs: object) -> float:
    q = default_process(query)
    c = default_process(choice)
    whole = float(fuzz.WRatio(q, c))
    partial = float(fuzz.partial_ratio(q, c))
    tokens = [t for t in _TOKEN_SPLIT.split(c) if len(t) > 1]
    best_tok = max((float(fuzz.WRatio(q, t)) for t in tokens), default=0.0)
    return max(whole, partial, best_tok)


def _probe_audio_duration(audio_path: Path) -> float:
    """Return duration in seconds via ffprobe (same idea as video render)."""
    cmd = [
        FFPROBE_BIN,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    result = subprocess_utils.check_call(cmd, timeout=60)
    try:
        return float(result.stdout.strip())
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"Could not read duration from ffprobe for {audio_path}") from exc


def transcript_from_lyrics_txt(lyrics_path: Path, audio_path: Path) -> Transcript:
    """Build a line-level transcript when ``transcript.json`` was never written.

    Each non-empty line becomes one "word" spanning an equal slice of the track.
    Timing is approximate but enough for the GUI to scroll and highlight lines.
    """
    text = lyrics_path.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        lines = ["·"]

    duration = _probe_audio_duration(audio_path)
    if duration <= 0:
        duration = 1.0

    n = len(lines)
    step = duration / n
    transcript = Transcript()
    for i, line in enumerate(lines):
        start = i * step
        end = duration if i == n - 1 else (i + 1) * step
        transcript.segments.append(
            Segment(words=[WordStamp(word=line, start=start, end=end)])
        )
    return transcript


def discover_playable_songs(output_root: Path) -> list[Path]:
    """Return song dirs that have instrumental audio and lyrics or word timings."""
    root = output_root.resolve()
    if not root.is_dir():
        return []

    playable: list[Path] = []
    for d in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not d.is_dir():
            continue
        final = d / "final"
        if not final.is_dir():
            continue

        if not any((final / name).exists() for name in _AUDIO_FILENAMES):
            continue

        if (final / "transcript.json").exists():
            playable.append(d)
            continue
        if (d / "transcript" / "transcript.json").exists():
            playable.append(d)
            continue
        if (final / "lyrics.txt").exists():
            playable.append(d)

    return playable


def _display_name(song_dir: Path) -> str:
    return song_dir.name.replace("_", " ")


def _audio_path(song_dir: Path, karaoke_mode: str = "instrumental") -> Path:
    final = song_dir / "final"
    preferred = tuple(
        f"{karaoke_mode}.{extension}" for extension in ("ogg", "wav", "m4a")
    )
    for name in preferred + _AUDIO_FILENAMES:
        candidate = final / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No instrumental audio found in {final}")


def prepare_gui_audio(
    song_dir: Path,
    karaoke_mode: str = "instrumental",
) -> Path:
    """Return pygame-compatible audio, converting legacy M4A output once."""
    audio = _audio_path(song_dir, karaoke_mode)
    if audio.suffix.lower() != ".m4a":
        return audio

    converted = audio.with_suffix(".ogg")
    try:
        subprocess_utils.check_call(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(audio),
                "-vn",
                "-c:a",
                "libvorbis",
                "-q:a",
                "5",
                str(converted),
            ],
            timeout=600,
        )
    except Exception as exc:
        if converted.exists():
            converted.unlink()
        raise RuntimeError(
            "This older song uses M4A audio, which pygame cannot play on this system, "
            f"and ffmpeg could not convert it to OGG: {exc}"
        ) from exc

    if not converted.exists():
        raise RuntimeError(f"ffmpeg did not create the expected audio file: {converted}")
    log.info("Converted legacy M4A for GUI replay: %s", converted)
    return converted


def load_playable_transcript(song_dir: Path) -> Transcript:
    """Load ``transcript.json`` or synthesize timing from ``lyrics.txt`` + audio length."""
    fin = song_dir / "final"
    t_fin = fin / "transcript.json"
    if t_fin.exists():
        return load_transcript(t_fin)
    t_stem = song_dir / "transcript" / "transcript.json"
    if t_stem.exists():
        return load_transcript(t_stem)
    lyrics = fin / "lyrics.txt"
    if lyrics.exists():
        return transcript_from_lyrics_txt(lyrics, _audio_path(song_dir))
    raise FileNotFoundError(f"No transcript or lyrics for {song_dir}")


def fuzzy_match_songs(
    query: str,
    song_dirs: list[Path],
    *,
    limit: int = 5,
    score_cutoff: int = _DEFAULT_SCORE_CUTOFF,
) -> list[tuple[Path, float]]:
    """Return up to *limit* ``(song_dir, score)`` pairs best matching *query*."""
    if not song_dirs or not query.strip():
        return []

    labels = [_display_name(d) for d in song_dirs]
    extracted = process.extract(
        query.strip(),
        labels,
        scorer=_library_choice_scorer,
        limit=limit,
        score_cutoff=score_cutoff,
    )
    return [(song_dirs[idx], float(score)) for _choice, score, idx in extracted]


def run_local_fuzzy_gui(
    query: str,
    output_root: Path,
    *,
    score_cutoff: int = _DEFAULT_SCORE_CUTOFF,
    karaoke_mode: str = "instrumental",
) -> None:
    """Prompt for a song match and open the GUI player, or exit with a message."""
    songs = discover_playable_songs(output_root)
    if not songs:
        console.print(
            f"[yellow]No playable songs in[/] {output_root.resolve()}[yellow].[/]\n"
            "Each folder needs [bold]final/instrumental.ogg[/] (or .wav/.m4a) plus either "
            "[bold]final/transcript.json[/] or [bold]final/lyrics.txt[/]."
        )
        raise SystemExit(1)

    matches = fuzzy_match_songs(query, songs, limit=5, score_cutoff=score_cutoff)
    if not matches:
        console.print(
            f"[yellow]No close matches for[/] {query!r} [yellow](cutoff {score_cutoff}).[/]\n"
            f"[dim]Known titles:[/] {', '.join(_display_name(s) for s in songs[:12])}"
            + (" …" if len(songs) > 12 else "")
        )
        raise SystemExit(1)

    console.print(f"\n[bold cyan]Matches for[/] {query!r}[cyan]:[/]\n")
    for i, (song_dir, score) in enumerate(matches, start=1):
        console.print(f"  [bold]{i}.[/] {_display_name(song_dir)}  [dim]({score:.0f})[/]")
    console.print()

    choice = _read_choice(len(matches))
    song_dir = matches[choice - 1][0]

    try:
        transcript = load_playable_transcript(song_dir)
    except (FileNotFoundError, RuntimeError) as exc:
        console.print(f"[bold red]Could not load lyrics/timing:[/] {exc}")
        raise SystemExit(1) from exc

    try:
        audio = prepare_gui_audio(song_dir, karaoke_mode)
    except RuntimeError as exc:
        console.print(f"[bold red]Could not prepare audio for playback:[/] {exc}")
        raise SystemExit(1) from exc
    title = _display_name(song_dir)
    log.info("Opening local karaoke: %s", song_dir)
    from bhajan.gui_player import play_karaoke  # noqa: PLC0415

    play_karaoke(audio_path=audio, transcript=transcript, title=title)


def _read_choice(n: int) -> int:
    for attempt in range(4):
        raw = input(f"Enter 1-{n} (then Enter) to open in the GUI: ").strip()
        if raw.isdigit():
            k = int(raw)
            if 1 <= k <= n:
                return k
        console.print(f"[red]Please type a number from 1 to {n}.[/]")
    raise SystemExit(1)
