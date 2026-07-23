"""Configuration constants for bhajan."""

from __future__ import annotations

import shutil
from pathlib import Path

# ---------------------------------------------------------------------------
# External binary discovery
# ---------------------------------------------------------------------------

FFMPEG_BIN: str = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE_BIN: str = shutil.which("ffprobe") or "ffprobe"

# ---------------------------------------------------------------------------
# Default model / backend settings
# ---------------------------------------------------------------------------

# Whisper model size. Options: tiny, base, small, medium, large-v3
DEFAULT_WHISPER_MODEL: str = "medium"

# Demucs model. htdemucs is one model; htdemucs_ft is a four-model bag that is
# somewhat higher quality but roughly four times slower on CPU.
DEFAULT_DEMUCS_MODEL: str = "htdemucs"

# Device for inference: "auto", "cpu", or "cuda"
DEFAULT_DEVICE: str = "auto"


def resolve_device(device: str = DEFAULT_DEVICE) -> str:
    """Resolve 'auto' to 'cuda' or 'cpu' based on availability."""
    if device != "auto":
        return device
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"

# ---------------------------------------------------------------------------
# Subtitle / video styling defaults - LARGE karaoke style
# ---------------------------------------------------------------------------

# ASS subtitle styling - Karaoke style (VERY large, center screen)
DEFAULT_FONT: str = "Arial"
DEFAULT_FONT_SIZE: int = 96  # VERY large for karaoke - increased for visibility
DEFAULT_FONT_COLOR: str = "&H00FFFFFF"       # white
DEFAULT_HIGHLIGHT_COLOR: str = "&H0000FFFF"   # yellow
DEFAULT_OUTLINE_COLOR: str = "&H00000000"     # black
DEFAULT_OUTLINE_WIDTH: int = 4  # Thick outline for readability
DEFAULT_SHADOW_ALPHA: int = 100                # 0-255
DEFAULT_SHADOW_COLOR: str = "&H00000000"      # black

# Video defaults (when no source video stream is used)
DEFAULT_VIDEO_WIDTH: int = 1280
DEFAULT_VIDEO_HEIGHT: int = 720
DEFAULT_VIDEO_FPS: int = 30
DEFAULT_BG_COLOR: str = "0c0c1e"              # dark navy

# ---------------------------------------------------------------------------
# Output layout
# ---------------------------------------------------------------------------

SUBDIRS = ["source", "stems", "transcript", "subtitles", "final"]
