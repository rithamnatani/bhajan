"""Tests for interactive online-lyrics review."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from bhajan.stages import lyrics_fetch
from bhajan.stages.lyrics_fetch import LyricsMatch, review_online_lyrics
from bhajan.stages.transcription_base import Segment, Transcript, WordStamp


def _match(track: str, artist: str = "", album: str = "") -> LyricsMatch:
    transcript = Transcript(
        segments=[Segment(words=[WordStamp(word=f"lyrics-{track}", start=0, end=1)])]
    )
    return LyricsMatch(
        transcript=transcript,
        track_name=track,
        artist_name=artist,
        album_name=album,
        duration=120,
    )


def _inputs(*values: str):
    iterator = iter(values)
    return lambda _prompt: next(iterator)


def test_review_accepts_initial_match() -> None:
    initial = _match("Tu Meri", "Vishal-Shekhar", "Bang Bang")

    selected = review_online_lyrics(
        initial,
        search_query="Tu Meri",
        duration=114,
        input_func=_inputs("y"),
    )

    assert selected is initial


def test_review_can_fall_back_to_whisper() -> None:
    selected = review_online_lyrics(
        _match("Wrong Song"),
        search_query="Wanted Song",
        duration=114,
        input_func=_inputs("w"),
    )

    assert selected is None


def test_review_can_type_title_and_choose_result(monkeypatch: pytest.MonkeyPatch) -> None:
    correct = _match("Tu Meri", "Vishal-Shekhar", "Bang Bang")
    queries: list[str] = []

    def fake_search(query: str, _duration: float | None):
        queries.append(query)
        return [correct]

    monkeypatch.setattr(lyrics_fetch, "search_lyrics_matches", fake_search)

    selected = review_online_lyrics(
        _match("Bang Bang", "Wrong Artist"),
        search_query="Bang Bang",
        duration=114,
        input_func=_inputs("t", "Tu Meri Vishal Shekhar", "1", "y"),
    )

    assert selected is correct
    assert queries == ["Tu Meri Vishal Shekhar"]


@dataclass
class _FakeResponse:
    text: str
    content_type: str = "text/plain; charset=utf-8"

    @property
    def headers(self) -> dict[str, str]:
        return {"Content-Type": self.content_type}

    def raise_for_status(self) -> None:
        return None


def test_direct_lrc_url(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse("[00:01.00]Line one\n[00:04.00]Line two\n")
    monkeypatch.setattr(lyrics_fetch._SESSION, "get", lambda *_a, **_kw: response)

    match = lyrics_fetch.fetch_lyrics_match_from_url("https://example.com/tu-meri.lrc")

    assert match.track_name == "tu-meri.lrc"
    assert [segment.text for segment in match.transcript.segments] == [
        "Line one",
        "Line two",
    ]


def test_generic_html_lyrics_url_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse("<html>not structured lyrics</html>", "text/html")
    monkeypatch.setattr(lyrics_fetch._SESSION, "get", lambda *_a, **_kw: response)

    with pytest.raises(ValueError, match="Webpage links are not supported"):
        lyrics_fetch.fetch_lyrics_match_from_url("https://example.com/song")
