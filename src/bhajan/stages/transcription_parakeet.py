"""Parakeet transcription backend (NVIDIA NeMo).

Uses NVIDIA's Parakeet ASR models via the NeMo toolkit. Parakeet provides
superior word-level timestamps compared to Whisper and is optimized for
English speech recognition.

Requirements:
    pip install nemo_toolkit['asr']
    # Requires CUDA-capable GPU

Models available:
    - parakeet-tdt-1.1b (1.1B params, fast, accurate)
    - parakeet-rnnt-1.1b (streaming capable)
    - parakeet-ctc-1.1b

See: https://github.com/NVIDIA/NeMo/tree/main/examples/asr
"""

from __future__ import annotations

import logging
from pathlib import Path

from bhajan.config import DEFAULT_DEVICE
from bhajan.logger import StageLogger
from bhajan.stages.transcription_base import (
    Segment,
    Transcript,
    TranscriptionBackend,
    WordStamp,
)

log = logging.getLogger("bhajan")
stage = StageLogger(log, "transcribe")

# Default Parakeet model - 1.1B parameters, excellent word timestamps
DEFAULT_PARAKEET_MODEL = "nvidia/parakeet-tdt-1.1b"


class ParakeetBackend(TranscriptionBackend):
    """Wraps NVIDIA NeMo Parakeet models for ASR with word-level timestamps."""

    def __init__(
        self,
        model_name: str = DEFAULT_PARAKEET_MODEL,
        device: str = DEFAULT_DEVICE,
        language: str | None = "en",  # Parakeet is English-only
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.language = language or "en"  # Default to English
        self._model = None
        self._decoder = None

    def name(self) -> str:
        return "parakeet"

    def available(self) -> bool:
        """Check if NeMo ASR is available with CUDA support."""
        try:
            import nemo.collections.asr as nemo_asr  # noqa: F401

            # Also check for torch and CUDA if device is cuda
            if self.device == "cuda":
                import torch

                if not torch.cuda.is_available():
                    stage.warning("Parakeet requested with cuda but CUDA not available")
                    return False
            return True
        except ImportError:
            return False
        except Exception:
            return False

    def transcribe(self, audio_path: Path) -> Transcript:
        if not self.available():
            raise RuntimeError(
                "NeMo ASR is not installed or CUDA is not available.\n"
                "Install it with: pip install nemo_toolkit['asr']\n"
                "Note: Parakeet requires an NVIDIA GPU."
            )

        model = self._get_model()

        stage.info(
            "Transcribing audio with %s (model=%s, device=%s) ...",
            self.name(),
            self.model_name,
            self.device,
        )
        stage.debug("Audio file: %s", audio_path)
        stage.debug("Audio file size: %.2f MB", audio_path.stat().st_size / 1_048_576)

        import nemo.collections.asr as nemo_asr
        import torch

        # Transcribe with word-level timestamps
        # NeMo's Parakeet models support word timestamps natively
        with torch.cuda.amp.autocast(enabled=self.device == "cuda"):
            # Run transcription
            transcript_result = model.transcribe(
                paths2audio_files=[str(audio_path)],
                batch_size=1,
                return_hypotheses=True,  # Get detailed output with timestamps
            )[0]  # Single file result

        # Extract word-level timestamps from the hypothesis
        transcript = Transcript()

        if hasattr(transcript_result, 'timestep') and transcript_result.timestep:
            # Process word-level timestamps if available
            words_with_ts = self._extract_word_timestamps(
                transcript_result.text,
                transcript_result.timestep
            )

            # Group words into segments (lines) - roughly 5-8 words per line
            segment_size = 6
            for i in range(0, len(words_with_ts), segment_size):
                segment_words = words_with_ts[i:i + segment_size]
                if segment_words:
                    transcript.segments.append(Segment(words=segment_words))
        else:
            # Fallback: segment-level timestamps only
            words = [
                WordStamp(
                    word=transcript_result.text.strip(),
                    start=0.0,
                    end=0.0,
                )
            ]
            transcript.segments.append(Segment(words=words))

        total_words = len(transcript.to_word_list())
        stage.info(
            "Transcription complete: %d segments, %d words",
            len(transcript.segments),
            total_words,
        )
        return transcript

    def _extract_word_timestamps(self, text: str, timestep) -> list[WordStamp]:
        """Extract word timestamps from NeMo timestep data."""
        words = text.strip().split()
        word_stamps: list[WordStamp] = []

        # NeMo timestep format varies by model - handle common formats
        if hasattr(timestep, 'word_timestamps') and timestep.word_timestamps:
            # Direct word timestamps available
            for i, wt in enumerate(timestep.word_timestamps):
                if i < len(words):
                    word_stamps.append(
                        WordStamp(
                            word=words[i],
                            start=round(float(wt.get('start', 0)), 3),
                            end=round(float(wt.get('end', 0)), 3),
                        )
                    )
        elif hasattr(timestep, 'alignments') and timestep.alignments:
            # Character-level alignments - convert to word timestamps
            alignments = timestep.alignments
            char_idx = 0
            for word in words:
                word_len = len(word)
                # Find start and end time for this word
                word_start = None
                word_end = None

                for j in range(char_idx, min(char_idx + word_len, len(alignments))):
                    if word_start is None:
                        word_start = alignments[j].get('start')
                    word_end = alignments[j].get('end')

                char_idx += word_len + 1  # +1 for space

                word_stamps.append(
                    WordStamp(
                        word=word,
                        start=round(float(word_start or 0), 3),
                        end=round(float(word_end or 0), 3),
                    )
                )
        else:
            # No timestamps available - estimate from text
            # Use average speech rate of ~0.3s per word
            base_time = 0.0
            for word in words:
                word_stamps.append(
                    WordStamp(
                        word=word,
                        start=round(base_time, 3),
                        end=round(base_time + 0.3, 3),
                    )
                )
                base_time += 0.3

        return word_stamps

    def _get_model(self):
        if self._model is None:
            import nemo.collections.asr as nemo_asr

            stage.info("Loading Parakeet model: %s", self.model_name)

            # Download and cache model
            model_path = self.model_name

            # Load the ASR model
            self._model = nemo_asr.models.ASRModel.from_pretrained(
                model_name=model_path,
                map_location=self.device,
            )

            if self.device == "cuda":
                self._model = self._model.cuda()
                self._model.eval()

        return self._model
