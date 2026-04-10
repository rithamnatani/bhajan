"""Pluggable interface for source separation (vocals / instrumental)."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("bhajan")


@dataclass(frozen=True)
class SeparationResult:
    """Output of a separation run."""
    vocals_path: Path
    instrumental_path: Path


class SeparatorBackend(ABC):
    """Abstract interface every separator must implement."""

    @abstractmethod
    def name(self) -> str:
        """Human-readable name, e.g. ``"demucs"``."""
        ...

    @abstractmethod
    def available(self) -> bool:
        """Return True if the backend's dependencies are installed."""
        ...

    @abstractmethod
    def separate(self, audio_path: Path, output_dir: Path) -> SeparationResult:
        """Separate *audio_path* into vocals and instrumental stems.

        Both stems must be saved into *output_dir* with sensible names.
        """
        ...
