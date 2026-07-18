"""Tests for lyric romanization."""

from bhajan.romanize import romanize_token, romanize_transcript
from bhajan.stages.transcription_base import Segment, Transcript, WordStamp


def test_romanize_token_hindi_is_casual_lowercase() -> None:
    assert romanize_token("मैं", language="hi") == "maim"


def test_romanize_token_gurmukhi_by_script() -> None:
    assert romanize_token("ਦਿਲ") == "dila"


def test_romanization_removes_notation_but_preserves_real_punctuation() -> None:
    assert romanize_token("भंगड़ा.", language="hi") == "bhamgada."
    assert romanize_token("(डालूँ),", language="hi") == "(dalun),"
    assert romanize_token("ख़्वाब?", language="hi") == "khvaba?"


def test_romanization_preserves_existing_latin_text() -> None:
    assert romanize_token("AI", language="hi") == "AI"
    assert romanize_token("don't", language="hi") == "don't"


def test_romanize_transcript_uses_sentence_case_and_preserves_timing() -> None:
    transcript = Transcript(
        segments=[
            Segment(
                words=[
                    WordStamp(word="मैं", start=0.0, end=0.5),
                    WordStamp(word="डालूँ", start=0.5, end=1.0),
                    WordStamp(word="AI", start=1.0, end=1.5),
                ]
            ),
            Segment(words=[WordStamp(word="चाँद", start=1.5, end=2.0)]),
        ]
    )

    result = romanize_transcript(transcript, language="hi")

    assert [segment.text for segment in result.segments] == ["Maim dalun AI", "Chanda"]
    assert result.segments[0].words[0].start == 0.0
    assert result.segments[0].words[0].end == 0.5
    assert result.segments[1].words[0].start == 1.5
    assert result.segments[1].words[0].end == 2.0


def test_sentence_case_restarts_after_source_punctuation() -> None:
    transcript = Transcript(
        segments=[
            Segment(
                words=[
                    WordStamp(word="हाँ।", start=0.0, end=0.5),
                    WordStamp(word="मैं", start=0.5, end=1.0),
                ]
            )
        ]
    )

    result = romanize_transcript(transcript, language="hi")

    assert result.segments[0].text == "Han. Maim"
