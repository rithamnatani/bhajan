"""Tests for :func:`bhajan.utils.looks_like_stream_url`."""

from __future__ import annotations

import pytest

from bhajan.utils import looks_like_stream_url


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://www.youtube.com/watch?v=abc", True),
        ("http://youtu.be/xyz", True),
        ("youtu.be/abc123", True),
        ("www.youtube.com/watch?v=1", True),
        ("m.youtube.com/watch?v=1", True),
        ("music.youtube.com/watch?v=1", True),
        ("https://example.com/video", True),
        ("shoota playboi carti", False),
        ("my youtube mashup remix", False),
        ("", False),
        ("   ", False),
    ],
)
def test_looks_like_stream_url(text: str, expected: bool) -> None:
    assert looks_like_stream_url(text) is expected
