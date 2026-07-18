"""Transliterate non-Latin lyrics into casual, singable Latin text."""

from __future__ import annotations

import logging
import unicodedata

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


_ROMANIZATION_NOTATION = str.maketrans("", "", ".~_^\\{}'`")
_SENTENCE_ENDINGS = frozenset(".!?।॥")


def _is_script_text(char: str, scheme: str) -> bool:
    """Return whether *char* is script content rather than punctuation."""
    return _scheme_for_text(char) == scheme and not unicodedata.category(char).startswith("P")


def _romanize_run(text: str, scheme: str) -> str:
    """Romanize one Indic-script run and remove only generated notation."""
    out = _sanscript.transliterate(text, scheme, _sanscript.OPTITRANS)
    lay_scheme = _sanscript.SCHEMES[_sanscript.OPTITRANS]
    out = lay_scheme.to_lay_indian(out)
    return out.translate(_ROMANIZATION_NOTATION)


def romanize_token(word: str, language: str | None = None) -> str:
    """Romanize Indic text while preserving the token's original punctuation."""
    if _sanscript is None or not word:
        return word

    detected_scheme = _scheme_for_text(word)
    scheme = detected_scheme or _scheme_from_language_hint(language)
    if scheme is None:
        return word

    # Romanize script runs separately. Punctuation never enters the transliterator,
    # so a real period remains while a dot emitted for .D/.N notation is removed.
    parts: list[str] = []
    run: list[str] = []

    def flush_run() -> None:
        if run:
            parts.append(_romanize_run("".join(run), scheme))
            run.clear()

    try:
        for char in word:
            if _is_script_text(char, scheme):
                run.append(char)
            else:
                flush_run()
                if char == "।" or char == "॥":
                    parts.append(".")
                else:
                    parts.append(char)
        flush_run()
        return "".join(parts) or word
    except Exception:
        log.debug("Transliteration failed for %r", word, exc_info=True)
        return word


def _capitalize_first_letter(text: str) -> str:
    for index, char in enumerate(text):
        if char.isalpha():
            return f"{text[:index]}{char.upper()}{text[index + 1:]}"
    return text


def romanize_transcript(transcript: Transcript, language: str | None = None) -> Transcript:
    """Return casual romanized lyrics with sentence-style capitalization."""
    if _sanscript is None:
        log.warning(
            "indic-transliteration is not installed; romanization is a no-op. "
            "Install dependencies (see pyproject.toml)."
        )
        return transcript

    new_segments: list[Segment] = []
    for seg in transcript.segments:
        new_words: list[WordStamp] = []
        sentence_start = True
        for word in seg.words:
            romanized = romanize_token(word.word, language)
            changed = romanized != word.word
            if changed and sentence_start:
                romanized = _capitalize_first_letter(romanized)

            new_words.append(WordStamp(word=romanized, start=word.start, end=word.end))

            if any(char.isalnum() for char in romanized):
                sentence_start = False
            if any(char in _SENTENCE_ENDINGS for char in word.word):
                sentence_start = True

        new_segments.append(Segment(words=new_words))
    return Transcript(segments=new_segments)
