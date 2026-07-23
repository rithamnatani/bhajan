"""Tests for YouTube title → LRCLib metadata heuristics."""

from __future__ import annotations

import pytest

from bhajan.stages import lyrics_fetch
from bhajan.stages.lyrics_fetch import _search_ranked, _short_track_aliases
from bhajan.utils import metadata_for_lrclib


def test_gallan_goodiyaan_t_series() -> None:
    title = "'Gallan Goodiyaan' Full VIDEO Song | Dil Dhadakne Do | T-Series"
    track, artist, album = metadata_for_lrclib(title, None)
    assert track == "Gallan Goodiyaan"
    assert artist == ""
    assert album == "Dil Dhadakne Do"


def test_quoted_title_trailing_label() -> None:
    title = "'Test Song' Audio | Some Movie | Sony Music"
    track, _, album = metadata_for_lrclib(title, None)
    assert track == "Test Song"
    assert "Some Movie" in album or album == "Some Movie"


def test_noisy_quoted_bollywood_title_gets_short_search_aliases() -> None:
    title = '"Senorita Zindagi Na Milegi Dobara" Full HD Video Song | Farhan Akhtar'
    track, _, _ = metadata_for_lrclib(title, None)

    assert track == "Senorita Zindagi Na Milegi Dobara"
    assert _short_track_aliases(track) == [
        "Senorita Zindagi Na",
        "Senorita Zindagi",
        "Senorita",
    ]


def test_movie_song_feat_cast_title() -> None:
    title = (
        "Bang Bang - Tu Meri feat Hrithik Roshan & Katrina Kaif | "
        "Vishal Shekhar | HD"
    )

    track, artist, album = metadata_for_lrclib(title, None)

    assert track == "Tu Meri"
    assert artist == "Vishal Shekhar"
    assert album == "Bang Bang"


def test_broad_alias_cannot_accept_unrelated_exact_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrong_record = {
        "id": 1,
        "trackName": "Bang Bang",
        "artistName": "Wrong Artist",
        "albumName": "Unrelated Album",
        "duration": 114.0,
        "syncedLyrics": "[00:01.00]No one gets in my way",
    }

    class Response:
        status_code = 200

        def __init__(self, payload: list[dict]) -> None:
            self._payload = payload

        def json(self) -> list[dict]:
            return self._payload

    def fake_get(_url: str, *, params: dict, timeout: int) -> Response:
        del timeout
        query = str(params.get("q", ""))
        return Response([wrong_record] if query in {"Bang Bang", "Bang"} else [])

    monkeypatch.setattr(lyrics_fetch._SESSION, "get", fake_get)

    match = _search_ranked(
        "Bang Bang - Tu Meri feat Hrithik Roshan Katrina Kaif",
        "",
        "Vishal Shekhar",
        114.0,
    )

    assert match is None
