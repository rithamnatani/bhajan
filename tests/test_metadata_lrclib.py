"""Tests for YouTube title → LRCLib metadata heuristics."""

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
