"""Transliterate non-Latin lyric tokens to Latin (ITRANS) for display and export."""

from __future__ import annotations

import logging

from bhajan.stages.transcription_base import Segment, Transcript, WordStamp

log = logging.getLogger("bhajan")

try:
    from indic_transliteration import sanscript as _sanscript
except ImportError:
    _sanscript = None


def _has_range(s: str, lo: int, hi: int) -> bool:
    return any(lo <= ord(c) <= hi for c in s if c.strip())


def _scheme_for_text(text: str) -> str | None:
    """Pick a sanscript scheme from character content (best-effort)."""
    if _sanscript is None:
        return None
    if _has_range(text, 0x0900, 0x097F):
        return _sanscript.DEVANAGARI
    if _has_range(text, 0x0A00, 0x0A7F):
        return _sanscript.GURMUKHI
    if _has_range(text, 0x0980, 0x09FF):
        return _sanscript.BENGALI
    if _has_range(text, 0x0B80, 0x0BFF):
        return _sanscript.TAMIL
    if _has_range(text, 0x0C00, 0x0C7F):
        return _sanscript.TELUGU
    if _has_range(text, 0x0C80, 0x0CFF):
        return _sanscript.KANNADA
    if _has_range(text, 0x0D00, 0x0D7F):
        return _sanscript.MALAYALAM
    return None


def _scheme_from_language_hint(language: str | None) -> str | None:
    if _sanscript is None or not language:
        return None
    lang = language.lower().strip()
    mapping = {
        "hi": _sanscript.DEVANAGARI,
        "mr": _sanscript.DEVANAGARI,
        "ne": _sanscript.DEVANAGARI,
        "sa": _sanscript.DEVANAGARI,
        "pa": _sanscript.GURMUKHI,
        "bn": _sanscript.BENGALI,
        "ta": _sanscript.TAMIL,
        "te": _sanscript.TELUGU,
        "kn": _sanscript.KANNADA,
        "ml": _sanscript.MALAYALAM,
    }
    return mapping.get(lang)


def romanize_token(word: str, language: str | None = None) -> str:
    """Transliterate a single token to Latin when possible."""
    if _sanscript is None or not word:
        return word
    stripped = word.strip()
    if not stripped:
        return word
    scheme = _scheme_from_language_hint(language) or _scheme_for_text(stripped)
    if scheme is None:
        return word
    try:
        out = _sanscript.transliterate(stripped, scheme, _sanscript.ITRANS)
        if not out:
            return word
        lead = word[: len(word) - len(word.lstrip())]
        trail = word[len(word.rstrip()) :]
        return f"{lead}{out}{trail}"
    except Exception:
        log.debug("Transliteration failed for %r", word, exc_info=True)
        return word


def romanize_transcript(transcript: Transcript, language: str | None = None) -> Transcript:
    """Return a new transcript with words transliterated to Latin where applicable."""
    if _sanscript is None:
        log.warning(
            "indic-transliteration is not installed; romanization is a no-op. "
            "Install dependencies (see pyproject.toml)."
        )
        return transcript

    new_segments: list[Segment] = []
    for seg in transcript.segments:
        new_words = [
            WordStamp(word=romanize_token(w.word, language), start=w.start, end=w.end)
            for w in seg.words
        ]
        new_segments.append(Segment(words=new_words))
    return Transcript(segments=new_segments)
