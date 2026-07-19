"""Tests for YouTube title → LRCLib metadata heuristics."""

from bhajan.stages.lyrics_fetch import _short_track_aliases
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
