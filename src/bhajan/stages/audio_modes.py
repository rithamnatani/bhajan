"""Create the three local karaoke audio modes."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from bhajan import subprocess_utils
from bhajan.config import FFMPEG_BIN
from bhajan.logger import StageLogger
from bhajan.stages.transcription_base import Transcript

log = logging.getLogger("bhajan")
stage = StageLogger(log, "audio-modes")


def export_audio_modes(
    *,
    original_path: Path,
    vocals_path: Path,
    instrumental_path: Path,
    transcript: Transcript,
    output_dir: Path,
) -> dict[str, Path]:
    """Write practice, guided, and instrumental audio into ``output_dir``.

    - ``practice`` keeps the original vocals for the whole song.
    - ``guided`` mixes in the vocal stem through the first lyric line, then
      fades it out.
    - ``instrumental`` contains no intentional vocals.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}
    outputs["practice"] = _encode_ogg_or_copy(
        original_path,
        output_dir / "practice.ogg",
    )
    outputs["instrumental"] = _encode_ogg_or_copy(
        instrumental_path,
        output_dir / "instrumental.ogg",
    )

    cue_end = _first_line_cue_end(transcript)
    guided_path = output_dir / "guided.ogg"
    fade_duration = min(0.8, max(0.2, cue_end / 4))
    fade_start = max(0.0, cue_end - fade_duration)
    filter_graph = (
        f"[1:a]atrim=start=0:end={cue_end:.3f},"
        f"afade=t=out:st={fade_start:.3f}:d={fade_duration:.3f}[cue];"
        "[0:a][cue]amix=inputs=2:duration=first:"
        "dropout_transition=0:normalize=0,alimiter=limit=0.95[out]"
    )
    try:
        subprocess_utils.check_call(
            [
                FFMPEG_BIN,
                "-y",
                "-i",
                str(instrumental_path),
                "-i",
                str(vocals_path),
                "-filter_complex",
                filter_graph,
                "-map",
                "[out]",
                "-c:a",
                "libvorbis",
                "-q:a",
                "5",
                guided_path,
            ],
            timeout=900,
        )
        outputs["guided"] = guided_path
    except Exception as exc:
        stage.warning(
            "Could not create the first-line vocal cue (%s); guided mode will "
            "use the instrumental track.",
            exc,
        )
        guided_wav = output_dir / "guided.wav"
        shutil.copy2(instrumental_path, guided_wav)
        outputs["guided"] = guided_wav

    stage.info("Practice audio     -> %s", outputs["practice"])
    stage.info("Guided audio       -> %s (vocals through %.1fs)", outputs["guided"], cue_end)
    stage.info("Instrumental audio -> %s", outputs["instrumental"])
    return outputs


def _encode_ogg_or_copy(source: Path, destination: Path) -> Path:
    try:
        subprocess_utils.check_call(
            [
                FFMPEG_BIN,
                "-y",
                "-i",
                str(source),
                "-c:a",
                "libvorbis",
                "-q:a",
                "5",
                str(destination),
            ],
            timeout=900,
        )
        return destination
    except Exception as exc:
        stage.warning("Could not encode %s to OGG (%s); retaining WAV.", source, exc)
        fallback = destination.with_suffix(".wav")
        shutil.copy2(source, fallback)
        return fallback


def _first_line_cue_end(transcript: Transcript) -> float:
    for segment in transcript.segments:
        if segment.words:
            end = max(float(segment.end), float(segment.start) + 1.0)
            return max(1.0, end + 0.35)
    return 5.0
