# bhajan

> Cross-platform CLI tool to generate karaoke videos from YouTube songs.

```
bhajan "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

One command. Out comes a karaoke video with synced, highlighted lyrics.

**New:** Use `--gui` for a fast GUI player (no video rendering needed) with synchronized lyrics!

---

## Table of Contents

- [Overview](#overview)
- [Requirements](#requirements)
- [Installation](#installation)
  - [Windows](#windows)
  - [macOS / Linux](#macos--linux)
- [Usage](#usage)
- [Output Layout](#output-layout)
- [Architecture](#architecture)
  - [Pluggable backends](#pluggable-backends)
- [Known Limitations](#known-limitations)
- [Tradeoffs & Future Improvements](#tradeoffs--future-improvements)

---

## Overview

`bhajan` automates the entire pipeline from a YouTube URL to a ready-to-play
karaoke MP4:

1. **Download** audio via `yt-dlp` (auto-cleans YouTube tracking parameters)
2. **Normalize** audio with `ffmpeg` (EBU R128 loudnorm)
3. **Separate** vocals / instrumental stems (Demucs or audio-separator)
4. **Transcribe** lyrics from the vocal stem (faster-whisper or Parakeet, word-level timestamps)
5. **Generate** ASS + LRC subtitle files (large, centered text)
6. **Render** the final karaoke video OR launch **GUI player** with synchronized lyrics

Intermediate artifacts are cleaned up by default (use `--keep-intermediate` to retain them).

---

## Requirements

| Dependency | Purpose | Notes |
|---|---|---|
| **Python ≥ 3.10** | Runtime | |
| **ffmpeg** | Audio/video processing | Must be on `PATH`. See installation below. |
| **ffprobe** | Duration probing | Ships with ffmpeg. |

Optional (installed automatically via `pip`):

| Package | Purpose |
|---|---|
| `yt-dlp` | YouTube download |
| `faster-whisper` | ASR transcription |
| `demucs` | Source separation (vocals vs instrumental) |
| `rich` | Pretty terminal output |
| `click` | CLI framework |
| `pygame` | GUI player audio playback |

Optional backends (install separately if needed):
| Package | Purpose | Install |
|---|---|---|
| `nemo_toolkit['asr']` | Parakeet transcription | `pip install nemo_toolkit['asr']` |
| `audio-separator` | Better vocal separation | `pip install audio-separator[gpu]` |

---

## Installation

### Windows

#### 1. Install ffmpeg

The easiest way on Windows:

```powershell
# Using winget (ships with Windows 10/11)
winget install Gyan.FFmpeg

# Or using scoop
scoop install ffmpeg

# Or manually:
# 1. Download a static build from https://www.gyan.dev/ffmpeg/builds/
# 2. Extract to e.g. C:\ffmpeg
# 3. Add C:\ffmpeg\bin to your PATH:
#    [Environment]::SetEnvironmentVariable("Path", $env:Path + ";C:\ffmpeg\bin", "User")
# 4. Restart your terminal
```

Verify:

```powershell
ffmpeg -version
ffprobe -version
```

#### 2. Install Python

```powershell
winget install Python.Python.3.12
```

#### 3. Install bhajan

```powershell
# Using uv (recommended)
cd C:\Users\Admin\dev\bhajan
uv sync

# Or using pip
pip install -e .
```

> **GPU acceleration (optional):** If you have an NVIDIA GPU and want faster
> inference, install the CUDA-enabled builds of `faster-whisper` and `demucs`.
> See their respective documentation pages for CUDA setup on Windows.

### macOS / Linux

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg

# Arch
sudo pacman -S ffmpeg
```

Then:

```bash
# Using uv (recommended)
uv sync

# Or using pip
pip install -e .
```

---

## Usage

### Basic

```bash
bhajan "https://www.youtube.com/watch?v=VIDEO_ID"
```

### Options

| Flag | Description |
|---|---|
| `-o DIR`, `--output-dir DIR` | Custom output root (default: `./output`) |
| `--whisper-model SIZE` | `tiny`, `base`, `small`, `medium`, `large-v3` (default: `small`) |
| `--device cpu\|cuda` | Inference device (default: `cpu`) |
| `--transcription-backend NAME` | `whisper` (default) or `parakeet` (NVIDIA GPU only) |
| `--separation-backend NAME` | `demucs` (default) or `audio-separator` |
| `--separator-model MODEL` | Model for audio-separator (default: `UVR-MDX-NET_Voc_FT.onnx`) |
| `--gui` | Launch GUI player instead of rendering video |
| `--keep-intermediate` | Retain source/stems/etc (default: cleanup) |
| `-v`, `--verbose` | Debug-level logging |
| `--skip-download` | Resume after download stage |
| `--skip-normalize` | Resume after normalization |
| `--skip-separate` | Resume after separation |
| `--skip-transcribe` | Resume after transcription |
| `--skip-render` | Skip final video rendering |
| `--version` | Show version |

**Note:** YouTube URLs are automatically cleaned - tracking parameters after `&` are stripped.

### Examples

```bash
# Fast GUI mode - no video rendering, just play with synced lyrics
bhajan "https://www.youtube.com/watch?v=VIDEO_ID" --gui

# GPU-accelerated with best quality backends
bhajan "https://www.youtube.com/watch?v=VIDEO_ID" \
  --device cuda \
  --transcription-backend parakeet \
  --separation-backend audio-separator

# Full pipeline with larger whisper model and GPU
bhajan "https://www.youtube.com/watch?v=VIDEO_ID" --whisper-model medium --device cuda

# Resume from after separation (useful if transcription crashed)
bhajan "https://www.youtube.com/watch?v=VIDEO_ID" --skip-download --skip-normalize --skip-separate

# Custom output directory with intermediate files kept
bhajan "https://www.youtube.com/watch?v=VIDEO_ID" -o ~/Karaoke --keep-intermediate
```

---

## Output Layout

```
output/<Safe_Song_Name>/
├── source/
│   ├── Song_Title.m4a          # Downloaded audio
│   └── normalized.wav          # Loudness-normaled WAV
├── stems/
│   ├── vocals.wav              # Vocal-only stem
│   └── instrumental.wav        # Instrumental-only stem
├── transcript/
│   └── transcript.json         # Word-level timestamps
├── subtitles/
│   ├── karaoke.ass             # ASS subtitles (for burn-in)
│   └── lyrics.lrc              # Simple LRC (fallback players)
└── final/
    └── final_karaoke.mp4       # Ready-to-play karaoke video
```

---

## Architecture

```
CLI (cli.py)
  └── Pipeline (pipeline.py)
        ├── Download       → stages/download.py       (yt-dlp)
        ├── Normalize      → stages/normalize.py      (ffmpeg loudnorm)
        ├── Separate       → stages/separator.py      (pluggable)
        │     └── Demucs   → stages/separator_demucs.py
        │     └── Audio-Separator → stages/separator_audio_separator.py
        ├── Transcribe     → stages/transcription.py  (pluggable)
        │     └── Whisper  → stages/transcription_whisper.py
        │     └── Parakeet → stages/transcription_parakeet.py
        ├── Subtitles      → stages/subtitles.py      (ASS + LRC gen)
        ├── Render         → stages/render.py         (ffmpeg + ASS burn-in)
        └── GUI Player     → gui_player.py            (tkinter + pygame)
```

### Pluggable Backends

Both the **separator** and **transcription** stages are designed as pluggable
interfaces:

#### Adding a new separator

1. Create `src/bhajan/stages/separator_your_backend.py`
2. Subclass `SeparatorBackend` from `separator_base.py`
3. Implement `name()`, `available()`, and `separate()`
4. Register it in `stages/separator.py`:

```python
from bhajan.stages.separator_your_backend import YourSeparator
register(YourSeparator, "your_backend")
```

#### Adding a new transcription backend

1. Create `src/bhajan/stages/transcription_your_backend.py`
2. Subclass `TranscriptionBackend` from `transcription_base.py`
3. Implement `name()`, `available()`, and `transcribe()`
4. Register it in `stages/transcription.py`:

```python
from bhajan.stages.transcription_your_backend import YourBackend
register(YourBackend, "your_asr")
```

**Available backends:**
- **Demucs** (default) -- well-maintained, works on CPU/GPU
- **audio-separator** -- wrapper around UVR/Roformer models, better quality
- **faster-whisper** (default) -- good accuracy, cross-platform
- **Parakeet** (NVIDIA only) -- superior word-level timestamps, requires CUDA

---

## Known Limitations

| Area | Limitation | Workaround / Note |
|---|---|---|
| **Transcription accuracy** | Whisper struggles with heavy reverb, overlapping vocals, or non-English lyrics | Use `--whisper-model medium` or larger. Future: swap to Parakeet. |
| **Word timestamps** | Not all Whisper models emit reliable word-level timestamps; the pipeline falls back to segment-level | Check `transcript.json` for quality. |
| **Demucs on CPU** | Separation can be slow on CPU (several minutes per song) | Use `--device cuda` or try `--gui` mode for faster playback. Auto-fallback to CPU if CUDA fails. |
| **Video quality** | MVP uses a solid-color background | Use `--gui` mode for a better experience without video rendering. |
| **ASS rendering** | Large centered text with outlines for readability | Font settings in `config.py` if you need customization. |
| **Parakeet backend** | Requires NVIDIA GPU + Linux/Windows with CUDA | Install `nemo_toolkit['asr']` separately. Falls back if unavailable. |
| **audio-separator** | Better quality but slower than Demucs | Install `audio-separator[gpu]` for GPU acceleration. |
| **YouTube restrictions** | Some videos are age-restricted or region-locked | yt-dlp handles most cases, but not all. |

---

## Tradeoffs & Future Improvements

### Why this approach?

| Decision | Rationale |
|---|---|
| **faster-whisper over Whisper.cpp** | Better Python integration, cross-platform wheels, good enough accuracy |
| **Demucs over custom ML** | Demucs is well-maintained, has a Python API, and works on Windows |
| **ASS subtitles over custom overlay** | ffmpeg bakes them in natively; no Python video compositing needed |
| **ffmpeg for rendering** | Battle-tested, hardware-accelerated encoding, works everywhere |

### Recent Improvements

- ✅ **Parakeet backend** for transcription -- superior word-level timestamps (NVIDIA GPU)
- ✅ **audio-separator backend** -- better vocal separation quality
- ✅ **GUI player** (`--gui`) -- fast playback without video rendering
- ✅ **Auto URL cleaning** -- strips YouTube tracking parameters
- ✅ **CUDA fallback** -- auto-switches to CPU if GPU fails
- ✅ **Better subtitles** -- larger font (96px), centered, better outlines
- ✅ **Default cleanup** -- intermediate files removed by default

### Future improvements

- [ ] **Background images/video** -- instead of solid color
- [ ] **Pitch / key detection** -- display the key of the song
- [ ] **Multi-language support** -- transcription + subtitle translation
- [ ] **Batch processing** -- queue multiple URLs
- [ ] **Web UI** -- Flask/FastAPI frontend for non-CLI users
- [ ] **Caching** -- skip stages when artifacts already exist for a given URL
- [ ] **Progress bars** -- real-time progress for long-running stages
- [ ] **Docker image** -- one-command deployment for servers

---

## License

MIT
