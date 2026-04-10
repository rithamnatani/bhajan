"""Registry / factory for separator backends.

Add new backends by registering them here.  The active backend is chosen
at pipeline construction time.
"""

from __future__ import annotations

import logging
from pathlib import Path

# Config imports not needed at registry level
from bhajan.logger import StageLogger
from bhajan.stages.separator_base import SeparationResult, SeparatorBackend

log = logging.getLogger("bhajan")
stage = StageLogger(log, "separate")

_REGISTRY: dict[str, type[SeparatorBackend]] = {}


def register(cls: type[SeparatorBackend], alias: str) -> None:
    """Register *cls* under *alias* (e.g. ``"demucs"``)."""
    _REGISTRY[alias] = cls


def create_backend(name: str, **kwargs) -> SeparatorBackend:
    """Instantiate the separator identified by *name*."""
    if name not in _REGISTRY:
        available = ", ".join(_REGISTRY.keys()) or "(none registered)"
        raise ValueError(f"Unknown separator backend '{name}'. Available: {available}")
    return _REGISTRY[name](**kwargs)


def run_separation(
    audio_path: Path,
    output_dir: Path,
    backend_name: str = "demucs",
    **backend_kwargs,
) -> SeparationResult:
    """Convenience: create + run a separator in one call."""
    backend = create_backend(backend_name, **backend_kwargs)

    if not backend.available():
        raise RuntimeError(
            f"Separator backend '{backend.name()}' is not available.\n"
            "See the README for installation instructions."
        )

    return backend.separate(audio_path, output_dir)


# ---- Auto-register built-in backends ----
# (Import deferred to avoid circular dependency at module load time.)
def _register_defaults() -> None:
    from bhajan.stages.separator_demucs import DemucsSeparator  # noqa: PLC0415

    register(DemucsSeparator, "demucs")

    # Register audio-separator if available
    try:
        from bhajan.stages.separator_audio_separator import (  # noqa: PLC0415
            AudioSeparatorBackend,
        )

        register(AudioSeparatorBackend, "audio-separator")
    except ImportError:
        pass  # audio-separator not installed, skip registration


_register_defaults()
