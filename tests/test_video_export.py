"""Tests for GUI-style video frames and karaoke audio modes."""

from __future__ import annotations

from bhajan.config import DEFAULT_DEMUCS_MODEL
from bhajan.karaoke_visuals import ACTIVE_COLOR, line_color, line_index_at_time
from bhajan.stages.audio_modes import _first_line_cue_end
from bhajan.stages.render import _frame_events, render_lyrics_frame
from bhajan.stages.transcription_base import Segment, Transcript, WordStamp


def _transcript() -> Transcript:
    return Transcript(
        segments=[
            Segment(words=[WordStamp("First", 1.0, 2.0), WordStamp("line", 2.0, 3.0)]),
            Segment(words=[WordStamp("Second", 5.0, 6.0), WordStamp("line", 6.0, 7.0)]),
            Segment(words=[WordStamp("Third", 9.0, 10.0), WordStamp("line", 10.0, 11.0)]),
        ]
    )


def test_shared_line_timing_matches_gui_behavior() -> None:
    segments = _transcript().segments

    assert line_index_at_time(segments, 0.0) == 0
    assert line_index_at_time(segments, 5.1) == 1
    assert line_index_at_time(segments, 20.0) == 2
    assert line_color(1, 1) == ACTIVE_COLOR


def test_frame_events_cover_the_audio_duration() -> None:
    events = _frame_events(_transcript().segments, 12.0)

    assert [index for index, _duration in events] == [0, 1, 2]
    assert abs(sum(duration for _index, duration in events) - 12.0) < 0.001


def test_rendered_frame_uses_active_cyan_and_expected_size() -> None:
    transcript = _transcript()

    image = render_lyrics_frame(
        title="Example Song",
        segments=transcript.segments,
        active_index=1,
        width=640,
        height=360,
    )

    assert image.size == (640, 360)
    colors = image.getcolors(maxcolors=640 * 360)
    assert colors is not None
    assert any(color == (0, 255, 255) for _count, color in colors)


def test_guided_mode_covers_first_line_then_fades() -> None:
    assert _first_line_cue_end(_transcript()) == 3.35


def test_fast_single_model_demucs_is_default() -> None:
    assert DEFAULT_DEMUCS_MODEL == "htdemucs"
