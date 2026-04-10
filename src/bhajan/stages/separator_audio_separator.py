"""Audio Separator backend using the audio-separator package.

This backend uses the ``audio-separator`` Python package which provides
access to multiple state-of-the-art vocal separation models:
- Roformer models (UVR-MDX-NET models)
- MDX-NET models  
- VR architecture models

The audio-separator package often provides better quality than Demucs
and includes models specifically trained for vocal/instrumental separation.

Installation:
    pip install audio-separator[gpu]  # For GPU support
    pip install audio-separator       # For CPU only

Models will be automatically downloaded on first use.
"""

from __future__ import annotations

import logging
from pathlib import Path

from bhajan.config import DEFAULT_DEVICE
from bhajan.logger import StageLogger
from bhajan.stages.separator_base import SeparationResult, SeparatorBackend

log = logging.getLogger("bhajan")
stage = StageLogger(log, "separate")

# Default model - UVR-MDX-NET Voc FT is excellent for vocals
DEFAULT_SEPARATOR_MODEL = "UVR-MDX-NET_Voc_FT.onnx"


class AudioSeparatorBackend(SeparatorBackend):
    """Wraps audio-separator package for vocal/instrumental separation."""

    def __init__(
        self,
        model: str = DEFAULT_SEPARATOR_MODEL,
        device: str = DEFAULT_DEVICE,
    ) -> None:
        self.model_name = model
        self.device = device
        self._separator = None

    def name(self) -> str:
        return "audio-separator"

    def available(self) -> bool:
        """Check if audio-separator package is installed."""
        try:
            import audio_separator  # noqa: F401
            return True
        except ImportError:
            return False

    def separate(self, audio_path: Path, output_dir: Path) -> SeparationResult:
        """Separate audio into vocals and instrumental stems.

        Args:
            audio_path: Path to input audio file
            output_dir: Directory to save output stems

        Returns:
            SeparationResult with paths to vocals and instrumental files
        """
        if not self.available():
            raise RuntimeError(
                "audio-separator is not installed.\n"
                "Install it with: pip install audio-separator\n"
                "For GPU support: pip install audio-separator[gpu]"
            )

        from audio_separator.separator import Separator

        stage.info(
            "Separating stems with %s (model=%s, device=%s) ...",
            self.name(),
            self.model_name,
            self.device,
        )
        stage.debug("Input: %s", audio_path)

        output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize separator with specified model
        # audio-separator automatically downloads models from HuggingFace
        separator = Separator(
            model_file_name=self.model_name,
            output_dir=str(output_dir),
            # Use GPU if available and requested
            use_cuda=self.device == "cuda",
            # Don't normalize to avoid double-normalization
            normalize=False,
        )

        # Process the audio file
        # audio-separator returns list of output files
        output_files = separator.separate(str(audio_path))

        # audio-separator typically outputs files in this order:
        # 1. Vocals (or primary stem)
        # 2. Instrumental/Other (secondary stem)
        #
        # The exact naming depends on the model used
        vocals_path: Path | None = None
        instrumental_path: Path | None = None

        for output_file in output_files:
            output_path = Path(output_file)
            file_name = output_path.name.lower()

            # Try to identify which file is which
            if "vocal" in file_name or "(Vocals)" in output_path.name:
                vocals_path = output_path
            elif "instru" in file_name or "(Instrumental)" in output_path.name:
                instrumental_path = output_path
            elif "other" in file_name or "(Other)" in output_path.name:
                # Some models output "Other" instead of "Instrumental"
                instrumental_path = output_path

        # Fallback: if we couldn't identify by name, assume order
        if vocals_path is None and len(output_files) >= 1:
            vocals_path = Path(output_files[0])
        if instrumental_path is None and len(output_files) >= 2:
            instrumental_path = Path(output_files[1])

        # Ensure files exist
        if vocals_path is None or not vocals_path.exists():
            raise FileNotFoundError(
                f"Vocals file not created by audio-separator. "
                f"Output files: {output_files}"
            )
        if instrumental_path is None or not instrumental_path.exists():
            raise FileNotFoundError(
                f"Instrumental file not created by audio-separator. "
                f"Output files: {output_files}"
            )

        # Rename to consistent naming convention
        final_vocals = output_dir / "vocals.wav"
        final_instrumental = output_dir / "instrumental.wav"

        # If the files aren't already in the right place with the right name, rename them
        if vocals_path != final_vocals:
            vocals_path.rename(final_vocals)
        if instrumental_path != final_instrumental:
            instrumental_path.rename(final_instrumental)

        vocals_size_mb = final_vocals.stat().st_size / 1_048_576
        instrumental_size_mb = final_instrumental.stat().st_size / 1_048_576

        stage.info("Vocals       -> %s (%.1f MB)", final_vocals, vocals_size_mb)
        stage.info(
            "Instrumental -> %s (%.1f MB)", final_instrumental, instrumental_size_mb
        )

        return SeparationResult(
            vocals_path=final_vocals,
            instrumental_path=final_instrumental,
        )
