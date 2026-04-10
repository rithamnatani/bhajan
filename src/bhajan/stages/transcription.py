"""Registry / factory for transcription backends.

Add new backends (e.g. Parakeet) by registering them here.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from bhajan.config import DEFAULT_DEVICE, DEFAULT_WHISPER_MODEL
from bhajan.logger import StageLogger
from bhajan.stages.transcription_base import Transcript, TranscriptionBackend

log = logging.getLogger("bhajan")
stage = StageLogger(log, "transcribe")

_REGISTRY: dict[str, type[TranscriptionBackend]] = {}


def register(cls: type[TranscriptionBackend], alias: str) -> None:
    """Register *cls* under *alias* (e.g. ``"whisper"``)."""
    _REGISTRY[alias] = cls


def create_backend(name: str, **kwargs) -> TranscriptionBackend:
    """Instantiate the transcription backend identified by *name*."""
    if name not in _REGISTRY:
        available = ", ".join(_REGISTRY.keys()) or "(none registered)"
        raise ValueError(f"Unknown transcription backend '{name}'. Available: {available}")
    return _REGISTRY[name](**kwargs)


def run_transcription(
    audio_path: Path,
    backend_name: str = "whisper",
    **backend_kwargs,
) -> Transcript:
    """Convenience: create + run a transcription backend in one call."""
    backend = create_backend(backend_name, **backend_kwargs)

    if not backend.available():
        raise RuntimeError(
            f"Transcription backend '{backend.name()}' is not available.\n"
            "See the README for installation instructions."
        )

    return backend.transcribe(audio_path)


def save_transcript(transcript: Transcript, transcript_dir: Path) -> Path:
    """Save the transcript as JSON and return the file path."""
    out_path = transcript_dir / "transcript.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(transcript.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    stage.info("Transcript saved -> %s", out_path)
    return out_path


# ---- Auto-register built-in backends ----
def _register_defaults() -> None:
    from bhajan.stages.transcription_whisper import FasterWhisperBackend  # noqa: PLC0415

    register(FasterWhisperBackend, "whisper")

    # Register Parakeet if available
    try:
        from bhajan.stages.transcription_parakeet import ParakeetBackend  # noqa: PLC0415

        register(ParakeetBackend, "parakeet")
    except ImportError:
        pass  # NeMo not installed, skip registration


_register_defaults()
