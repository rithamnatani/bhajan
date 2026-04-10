"""Pipeline stage: normalize audio with ffmpeg."""

from __future__ import annotations

import logging
from pathlib import Path

from bhajan.config import FFMPEG_BIN
from bhajan.logger import StageLogger
from bhajan import subprocess_utils

log = logging.getLogger("bhajan")
stage = StageLogger(log, "normalize")


def normalize_audio(input_path: Path, output_dir: Path, name: str = "normalized") -> Path:
    """Loudness-normalize *input_path* to a 48 kHz 16-bit WAV file.

    Uses ffmpeg's EBU R128 two-pass loudnorm filter.
    Returns the path to the output WAV.
    """
    output_wav = output_dir / f"{name}.wav"

    stage.info("Normalizing audio -> %s", output_wav)
    stage.debug("Input file size: %.2f MB", input_path.stat().st_size / 1_048_576)

    # Two-pass loudnorm for consistent perceived volume
    # ---- pass 1: measure ----
    stage.debug("Running loudnorm measurement pass...")
    meas_cmd = [
        FFMPEG_BIN, "-y", "-i", str(input_path),
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ]
    result = subprocess_utils.check_call(meas_cmd)
    # Parse the measured values from stderr
    meas_json = _extract_loudnorm_json(result.stderr)
    
    if meas_json:
        stage.debug("Loudnorm measurements: %s", meas_json)

    # ---- pass 2: apply ----
    if meas_json:
        af = (
            f"loudnorm=I=-16:TP=-1.5:LRA=11:"
            f"measured_I={meas_json.get('input_i', '-24')}:"
            f"measured_TP={meas_json.get('input_tp', '-30')}:"
            f"measured_LRA={meas_json.get('input_lra', '10')}:"
            f"measured_thresh={meas_json.get('input_thresh', '-35')}"
        )
        stage.debug("Using measured loudnorm values for normalization")
    else:
        # Fallback to single-pass if parsing failed
        af = "loudnorm=I=-16:TP=-1.5:LRA=11"
        stage.warning("Could not parse loudnorm measurements; using single-pass normalization.")

    stage.debug("Applying loudnorm normalization...")
    norm_cmd = [
        FFMPEG_BIN, "-y", "-i", str(input_path),
        "-af", af,
        "-ar", "48000",
        "-ac", "2",
        "-sample_fmt", "s16",
        str(output_wav),
    ]
    subprocess_utils.check_call(norm_cmd)
    
    output_size_mb = output_wav.stat().st_size / 1_048_576
    stage.info("Normalized audio saved (%.1f MB)", output_size_mb)
    return output_wav


def _extract_loudnorm_json(stderr_text: str) -> dict | None:
    """Pull the JSON block printed by loudnorm from ffmpeg stderr."""
    import json
    import re

    # The JSON is wrapped between {...} in the last lines of stderr
    match = re.search(r"(\{[^{}]+\})", stderr_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
    return None
