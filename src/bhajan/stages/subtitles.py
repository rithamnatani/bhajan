"""Generate ASS subtitle files for karaoke rendering.

Produces both an ASS file (for ffmpeg burn-in with karaoke-style
highlighting) and an LRC file (simple, widely-compatible timing).
"""

from __future__ import annotations

import logging
from pathlib import Path

from bhajan.config import (
    DEFAULT_FONT,
    DEFAULT_FONT_COLOR,
    DEFAULT_FONT_SIZE,
    DEFAULT_HIGHLIGHT_COLOR,
    DEFAULT_OUTLINE_COLOR,
    DEFAULT_OUTLINE_WIDTH,
    DEFAULT_SHADOW_ALPHA,
    DEFAULT_SHADOW_COLOR,
)
from bhajan.logger import StageLogger
from bhajan.stages.transcription_base import Transcript, WordStamp

log = logging.getLogger("bhajan")
stage = StageLogger(log, "subtitles")


def generate_ass(transcript: Transcript, subtitles_dir: Path) -> Path:
    """Create a karaoke-style ASS subtitle file with word-level highlighting.

    The strategy:
    - Each line/segment becomes one ASS event.
    - Within each event, words are rendered in grey (inactive) using \\c tags.
    - The currently-sung word is shown in the highlight color via \\1c tag.
    - We emit one ASS dialogue line per word, staggered in time, so that
      at any given moment only the active word is highlighted while the
      rest of the segment remains dim.

    Returns the path to the .ass file.
    """
    out_path = subtitles_dir / "karaoke.ass"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # ASS Style - properly formatted
    # Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
    # ASS Alignment: 5 = center-middle (perfect for karaoke)
    style_default = (
        f"Style: Default,{DEFAULT_FONT},{DEFAULT_FONT_SIZE},"
        f"{DEFAULT_FONT_COLOR},&H000000FF,{DEFAULT_OUTLINE_COLOR},&H00000000,"
        f"-1,0,0,0,100,100,0,0,1,{DEFAULT_OUTLINE_WIDTH},0,5,10,10,50,1"
    )

    style_highlight = (
        f"Style: Highlight,{DEFAULT_FONT},{DEFAULT_FONT_SIZE},"
        f"{DEFAULT_HIGHLIGHT_COLOR},{DEFAULT_OUTLINE_COLOR},{DEFAULT_OUTLINE_COLOR},&H00000000,"
        f"-1,0,0,0,100,100,0,0,1,{DEFAULT_OUTLINE_WIDTH},0,5,10,10,50,1"
    )

    events: list[str] = []

    for seg in transcript.segments:
        if not seg.words:
            continue

        # Build a single line of text for this segment
        full_text = " ".join(w.word for w in seg.words)

        # For each word, emit a dialogue event that spans the word's duration.
        # We use ASS inline tags to color the active word.
        for i, word in enumerate(seg.words):
            # Build the display text: all words, but only the active one colored
            display_parts: list[str] = []
            for j, w in enumerate(seg.words):
                escaped = _ass_escape(w.word)
                if j == i:
                    # Active word in highlight color
                    display_parts.append(
                        f"{{\\c{DEFAULT_HIGHLIGHT_COLOR}}}{escaped}{{\\c{DEFAULT_FONT_COLOR}}}"
                    )
                else:
                    # Inactive word in default color
                    display_parts.append(escaped)

            display = " ".join(display_parts)

            start_ts = _seconds_to_ass_time(word.start)
            end_ts = _seconds_to_ass_time(word.end)

            events.append(
                f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{display}"
            )

    content = _ass_header() + f"{style_default}\n{style_highlight}\n" + "\n".join(events) + "\n"
    out_path.write_text(content, encoding="utf-8-sig")
    stage.info("ASS subtitles saved -> %s", out_path)
    return out_path


def generate_lrc(transcript: Transcript, subtitles_dir: Path) -> Path:
    """Generate a simple .lrc file (line-level timestamps).

    LRC is [mm:ss.xx]text per line -- good for fallback players.
    """
    out_path = subtitles_dir / "lyrics.lrc"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for seg in transcript.segments:
        if not seg.words:
            continue
        ts = _seconds_to_lrc(seg.start)
        lines.append(f"[{ts}]{seg.text}")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    stage.info("LRC subtitles saved -> %s", out_path)
    return out_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ass_header() -> str:
    return (
        "[Script Info]\n"
        "Title: Karaoke Lyrics (bhajan)\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 2\n"
        "PlayResX: 1280\n"
        "PlayResY: 720\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def _seconds_to_ass_time(seconds: float) -> str:
    """Convert seconds to ASS timestamp  H:MM:SS.cc."""
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    s = int(seconds) % 60
    cs = int(round((seconds - int(seconds)) * 100))
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _seconds_to_lrc(seconds: float) -> str:
    """Convert seconds to LRC timestamp mm:ss.xx."""
    total_cs = round(seconds * 100)
    m = total_cs // 6000
    s = (total_cs % 6000) // 100
    cs = total_cs % 100
    return f"{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    """Escape ASS-special characters (currently none need escaping beyond braces)."""
    return text.replace("{", r"\{").replace("}", r"\}")
