"""Tests for local library discovery and fuzzy matching."""

from __future__ import annotations

from pathlib import Path

import pytest

from bhajan.local_library import (
    discover_playable_songs,
    fuzzy_match_songs,
    prepare_gui_audio,
    transcript_from_lyrics_txt,
)
from bhajan.stages.transcription import Transcript, save_transcript
from bhajan.stages.transcription_base import Segment, WordStamp


def _minimal_transcript() -> Transcript:
    t = Transcript()
    t.segments.append(
        Segment(
            words=[
                WordStamp(word="hi", start=0.0, end=0.5),
            ]
        )
    )
    return t


def test_discover_playable_songs_requires_final_bundle(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()

    incomplete = root / "no_audio"
    incomplete.mkdir()
    (incomplete / "final").mkdir()
    (incomplete / "final" / "transcript.json").write_text("{}", encoding="utf-8")

    assert discover_playable_songs(root) == []

    song = root / "Test_Song_Here"
    song.mkdir()
    final = song / "final"
    final.mkdir()
    (final / "instrumental.m4a").write_bytes(b"")
    save_transcript(_minimal_transcript(), song / "transcript")

    found = discover_playable_songs(root)
    assert found == [song]


def test_discover_playable_songs_lyrics_only(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    song = root / "Some_Track"
    song.mkdir()
    final = song / "final"
    final.mkdir()
    (final / "instrumental.m4a").write_bytes(b"")
    (final / "lyrics.txt").write_text("line one\nline two\n", encoding="utf-8")

    assert discover_playable_songs(root) == [song]


def test_transcript_from_lyrics_txt_slices(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "bhajan.local_library._probe_audio_duration",
        lambda _p: 10.0,
    )
    root = tmp_path / "x"
    root.mkdir()
    lyrics = root / "lyrics.txt"
    lyrics.write_text("a\nb\nc\n", encoding="utf-8")
    audio = root / "fake.m4a"
    audio.write_bytes(b"")

    tr = transcript_from_lyrics_txt(lyrics, audio)
    assert len(tr.segments) == 3
    assert tr.segments[0].words[0].word == "a"
    assert tr.segments[0].words[0].start == 0.0
    assert abs(tr.segments[2].words[0].end - 10.0) < 1e-6


def test_fuzzy_match_short_query_carti(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    song = root / "Playboi_Carti_-_Shoota"
    song.mkdir()
    (song / "final").mkdir()
    (song / "final" / "instrumental.m4a").write_bytes(b"")
    (song / "final" / "lyrics.txt").write_text("x\n", encoding="utf-8")

    dirs = discover_playable_songs(root)
    matches = fuzzy_match_songs("carti", dirs, limit=5, score_cutoff=55)
    assert matches[0][0] == song


def test_fuzzy_match_typo_with_processor(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    song = root / "Playboi_Carti_-_Shoota_Audio"
    song.mkdir()
    (song / "final").mkdir()
    (song / "final" / "instrumental.m4a").write_bytes(b"")
    save_transcript(_minimal_transcript(), song / "final")

    dirs = discover_playable_songs(root)
    matches = fuzzy_match_songs("shorda", dirs, limit=5, score_cutoff=50)
    assert len(matches) == 1
    assert matches[0][0] == song


def test_prepare_gui_audio_prefers_ogg(tmp_path: Path) -> None:
    song = tmp_path / "song"
    final = song / "final"
    final.mkdir(parents=True)
    (final / "instrumental.m4a").write_bytes(b"legacy")
    ogg = final / "instrumental.ogg"
    ogg.write_bytes(b"playable")

    assert prepare_gui_audio(song) == ogg


def test_prepare_gui_audio_uses_requested_mode(tmp_path: Path) -> None:
    song = tmp_path / "song"
    final = song / "final"
    final.mkdir(parents=True)
    (final / "instrumental.ogg").write_bytes(b"instrumental")
    guided = final / "guided.ogg"
    guided.write_bytes(b"guided")

    assert prepare_gui_audio(song, "guided") == guided


def test_prepare_gui_audio_converts_legacy_m4a(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    song = tmp_path / "song"
    final = song / "final"
    final.mkdir(parents=True)
    m4a = final / "instrumental.m4a"
    m4a.write_bytes(b"legacy")

    def fake_ffmpeg(cmd: list[str], timeout: int) -> object:
        assert cmd[0] == "ffmpeg"
        assert timeout == 600
        Path(cmd[-1]).write_bytes(b"ogg")
        return object()

    monkeypatch.setattr("bhajan.local_library.subprocess_utils.check_call", fake_ffmpeg)

    converted = prepare_gui_audio(song)

    assert converted == final / "instrumental.ogg"
    assert converted.read_bytes() == b"ogg"
