"""Pluggable interface for speech-to-text (ASR) transcription."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("bhajan")


@dataclass
class WordStamp:
    """A single word with its start / end time in seconds."""
    word: str
    start: float
    end: float


@dataclass
class Segment:
    """A line / sentence composed of word-level stamps."""
    words: list[WordStamp] = field(default_factory=list)

    @property
    def start(self) -> float:
        return self.words[0].start if self.words else 0.0

    @property
    def end(self) -> float:
        return self.words[-1].end if self.words else 0.0

    @property
    def text(self) -> str:
        return " ".join(w.word for w in self.words)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "words": [{"word": w.word, "start": w.start, "end": w.end} for w in self.words],
        }


@dataclass
class Transcript:
    """Full transcript with word-level timestamps."""
    segments: list[Segment] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"segments": [s.to_dict() for s in self.segments]}

    def to_word_list(self) -> list[WordStamp]:
        """Flatten all segments into a single word list."""
        result: list[WordStamp] = []
        for seg in self.segments:
            result.extend(seg.words)
        return result


class TranscriptionBackend(ABC):
    """Abstract interface every ASR backend must implement."""

    @abstractmethod
    def name(self) -> str:
        """Human-readable name, e.g. ``"faster-whisper"``."""
        ...

    @abstractmethod
    def available(self) -> bool:
        """Return True if the backend's dependencies are installed."""
        ...

    @abstractmethod
    def transcribe(self, audio_path: Path) -> Transcript:
        """Transcribe *audio_path* and return a :class:`Transcript`."""
        ...
