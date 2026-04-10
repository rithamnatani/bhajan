"""faster-whisper transcription backend.

Uses the ``faster-whisper`` Python package (CTranslate2-based Whisper
runtime).  This is the default because it works well on Windows, macOS,
and Linux with minimal setup.

Supports:
- Auto language detection
- Multiple languages (Hindi, French, Spanish, etc.)
- Romanization for non-Latin scripts (optional)
"""

from __future__ import annotations

import logging
from pathlib import Path

from bhajan.config import DEFAULT_DEVICE, DEFAULT_WHISPER_MODEL
from bhajan.logger import StageLogger
from bhajan.stages.transcription_base import (
    Segment,
    Transcript,
    TranscriptionBackend,
    WordStamp,
)

log = logging.getLogger("bhajan")
stage = StageLogger(log, "transcribe")

# Language codes supported by Whisper
def _looks_like_cuda_load_failure(exc: BaseException) -> bool:
    """True if *exc* is likely missing CUDA/cuBLAS DLLs (Windows) or broken GPU runtime."""
    parts: list[str] = [str(exc).lower()]
    cause = exc.__cause__
    if cause is not None:
        parts.append(str(cause).lower())
    if isinstance(exc, OSError) and exc.filename is not None:
        parts.append(str(exc.filename).lower())
    blob = " ".join(parts)
    keys = (
        "cublas",
        "cudnn",
        "libcudart",
        "cudart",
        "nvrtc",
        ".dll",
        "cannot load",
        "cannot find",
    )
    return any(k in blob for k in keys)


_cuda_dlls_registered = False


def _ensure_cuda_dlls() -> None:
    """On Windows, register PyTorch's bundled CUDA DLLs so ctranslate2 can load cuBLAS etc."""
    global _cuda_dlls_registered
    if _cuda_dlls_registered:
        return
    _cuda_dlls_registered = True

    import sys
    if sys.platform != "win32":
        return
    try:
        import os
        import torch
        lib_dir = os.path.join(os.path.dirname(torch.__file__), "lib")
        if os.path.isdir(lib_dir):
            os.add_dll_directory(lib_dir)
            stage.debug("Registered PyTorch DLL directory: %s", lib_dir)
    except (ImportError, OSError):
        pass


SUPPORTED_LANGUAGES = {
    "en": "English",
    "hi": "Hindi",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "pt": "Portuguese",
    "ru": "Russian",
    "ar": "Arabic",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "ta": "Tamil",
    "te": "Telugu",
    "bn": "Bengali",
    "mr": "Marathi",
}


class FasterWhisperBackend(TranscriptionBackend):
    """Wraps ``faster-whisper`` for ASR with word-level timestamps."""

    def __init__(
        self,
        model_size: str = DEFAULT_WHISPER_MODEL,
        device: str = DEFAULT_DEVICE,
        language: str | None = None,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.language = language  # None = auto-detect
        self._model = None

    def name(self) -> str:
        return "faster-whisper"

    def available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401
            return True
        except ImportError:
            return False

    def transcribe(self, audio_path: Path) -> Transcript:
        if not self.available():
            raise RuntimeError(
                "faster-whisper is not installed.\n"
                "Install it with:  pip install faster-whisper"
            )

        stage.info(
            "Transcribing audio with %s (model=%s, device=%s, language=%s) ...",
            self.name(),
            self.model_size,
            self.device,
            self.language or "auto",
        )
        stage.debug("Audio file: %s", audio_path)
        stage.debug("Audio file size: %.2f MB", audio_path.stat().st_size / 1_048_576)

        try:
            return self._transcribe_with_loaded_model(audio_path)
        except Exception as e:
            if self.device != "cuda" or not _looks_like_cuda_load_failure(e):
                raise
            stage.warning("CUDA transcription failed (%s), falling back to CPU...", e)
            self._model = None
            self.device = "cpu"
            stage.info(
                "Transcribing audio with %s (model=%s, device=%s, language=%s) ...",
                self.name(),
                self.model_size,
                self.device,
                self.language or "auto",
            )
            return self._transcribe_with_loaded_model(audio_path)

    def _transcribe_with_loaded_model(self, audio_path: Path) -> Transcript:
        model = self._get_model()

        segments_iter, info = model.transcribe(
            str(audio_path),
            beam_size=5,
            word_timestamps=True,
            vad_filter=True,
            language=self.language,
        )

        detected_lang = info.language if info else "unknown"
        lang_name = SUPPORTED_LANGUAGES.get(detected_lang, detected_lang)
        stage.info("Detected language: %s (%s)", detected_lang, lang_name)

        transcript = Transcript()
        seg_count = 0

        for seg_data in segments_iter:
            words: list[WordStamp] = []
            if seg_data.words:
                for wd in seg_data.words:
                    word_text = wd.word.strip()

                    words.append(
                        WordStamp(
                            word=word_text,
                            start=round(wd.start, 3),
                            end=round(wd.end, 3),
                        )
                    )
            else:
                word_text = seg_data.text.strip()

                words = [
                    WordStamp(
                        word=word_text,
                        start=round(seg_data.start, 3),
                        end=round(seg_data.end, 3),
                    )
                ]
            if words:
                transcript.segments.append(Segment(words=words))
                seg_count += 1
                stage.debug("Processed segment %d (%d words)", seg_count, len(words))

        total_words = len(transcript.to_word_list())
        stage.info(
            "Transcription complete: %d segments, %d words",
            len(transcript.segments),
            total_words,
        )
        return transcript

    def _get_model(self):
        if self._model is None:
            _ensure_cuda_dlls()
            from faster_whisper import WhisperModel  # noqa: PLC0415

            compute_type = "int8" if self.device == "cpu" else "float16"

            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=compute_type,
                download_root=Path.home() / ".cache" / "bhajan" / "models",
            )
        return self._model

