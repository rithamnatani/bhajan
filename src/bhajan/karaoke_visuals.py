"""Shared visual rules for the GUI player and saved karaoke videos."""

from __future__ import annotations

from bhajan.stages.transcription_base import Segment

WINDOW_BG = "#0c0c1e"
LYRICS_BG = "#12122a"
LYRICS_BORDER = "#2a2a44"
TITLE_COLOR = "#ffffff"
ACTIVE_COLOR = "#00ffff"
PAST_COLOR = "#7a7a8e"
FUTURE_COLOR = "#5a5a72"


def line_index_at_time(segments: list[Segment], seconds: float) -> int:
    """Return the GUI-compatible active lyric index for *seconds*."""
    if not segments:
        return -1
    index = 0
    for candidate, segment in enumerate(segments):
        if segment.start <= seconds:
            index = candidate
    return index


def line_color(index: int, active_index: int) -> str:
    """Return the GUI-compatible color for one lyric line."""
    if index == active_index:
        return ACTIVE_COLOR
    if active_index >= 0 and index < active_index:
        return PAST_COLOR
    return FUTURE_COLOR
