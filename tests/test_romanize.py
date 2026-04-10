"""Tests for lyric romanization."""

from bhajan.romanize import romanize_token, romanize_transcript
from bhajan.stages.transcription_base import Segment, Transcript, WordStamp


def test_romanize_token_hindi() -> None:
    out = romanize_token("मैं", language="hi")
    assert out.strip()
    assert "मैं" not in out


def test_romanize_token_gurmukhi_by_script() -> None:
    out = romanize_token("ਦਿਲ")
    assert out.strip()
    assert "ਦ" not in out


def test_romanize_transcript_preserves_timing() -> None:
    t = Transcript(
        segments=[
            Segment(
                words=[
                    WordStamp(word="मैं", start=0.0, end=0.5),
                ]
            )
        ]
    )
    r = romanize_transcript(t, language="hi")
    w = r.segments[0].words[0]
    assert w.start == 0.0 and w.end == 0.5
    assert "मैं" not in w.word
