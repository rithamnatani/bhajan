"""Render control-free MP4s that visually match the GUI lyric panel."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from bhajan import subprocess_utils
from bhajan.config import (
    DEFAULT_BG_COLOR,
    DEFAULT_VIDEO_FPS,
    DEFAULT_VIDEO_HEIGHT,
    DEFAULT_VIDEO_WIDTH,
    FFMPEG_BIN,
    FFPROBE_BIN,
)
from bhajan.karaoke_visuals import (
    ACTIVE_COLOR,
    LYRICS_BG,
    LYRICS_BORDER,
    TITLE_COLOR,
    WINDOW_BG,
    line_color,
)
from bhajan.logger import StageLogger
from bhajan.stages.transcription_base import Segment, Transcript

log = logging.getLogger("bhajan")
stage = StageLogger(log, "render")


def render_video(
    *,
    instrumental_path: Path,
    ass_path: Path,
    output_path: Path,
    width: int = DEFAULT_VIDEO_WIDTH,
    height: int = DEFAULT_VIDEO_HEIGHT,
    fps: int = DEFAULT_VIDEO_FPS,
    bg_color: str = DEFAULT_BG_COLOR,
) -> Path:
    """Legacy single-video ASS renderer retained for API compatibility.

    New pipeline runs use :func:`render_video_suite`, whose visuals match the
    GUI. Third-party callers using the original function still receive the
    historical ASS-based output.
    """
    duration = _probe_duration(instrumental_path)
    ass_path_str = str(ass_path.resolve()).replace("\\", "/")
    subtitles_filter = (
        f"subtitles='{ass_path_str}':force_style='PlayResX={width},"
        f"PlayResY={height},Alignment=5'"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess_utils.check_call(
        [
            FFMPEG_BIN,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={bg_color}:s={width}x{height}:r={fps},format=yuv420p",
            "-i",
            str(instrumental_path),
            "-vf",
            subtitles_filter,
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(output_path),
        ],
        timeout=7200,
    )
    return output_path


def render_video_suite(
    *,
    title: str,
    transcript: Transcript,
    audio_tracks: dict[str, Path],
    output_dir: Path,
    width: int = DEFAULT_VIDEO_WIDTH,
    height: int = DEFAULT_VIDEO_HEIGHT,
) -> dict[str, Path]:
    """Render one GUI-style visual stream and mux it with each audio mode.

    ``audio_tracks`` normally contains ``practice``, ``guided``, and
    ``instrumental``.  The expensive H.264 visual encoding happens only once;
    each final MP4 copies that video stream and adds a different AAC track.
    """
    if not audio_tracks:
        raise ValueError("At least one audio track is required for video rendering.")

    output_dir.mkdir(parents=True, exist_ok=True)
    duration = max(_probe_duration(path) for path in audio_tracks.values())
    segments = [segment for segment in transcript.segments if segment.words]
    stage.info(
        "Rendering GUI-style lyric video once (%dx%d, %.1fs) ...",
        width,
        height,
        duration,
    )

    outputs: dict[str, Path] = {}
    with tempfile.TemporaryDirectory(prefix="bhajan-video-", dir=str(output_dir)) as tmp:
        temp_dir = Path(tmp)
        visual_path = temp_dir / "lyrics_visual.mp4"
        _render_visual_track(
            title=title,
            segments=segments,
            duration=duration,
            output_path=visual_path,
            temp_dir=temp_dir,
            width=width,
            height=height,
        )

        for mode, audio_path in audio_tracks.items():
            output_path = output_dir / f"{mode}.mp4"
            _mux_audio(
                visual_path=visual_path,
                audio_path=audio_path,
                output_path=output_path,
                title=title,
                mode=mode,
            )
            outputs[mode] = output_path

    stage.info("Saved %d local karaoke videos -> %s", len(outputs), output_dir)
    return outputs


def _render_visual_track(
    *,
    title: str,
    segments: list[Segment],
    duration: float,
    output_path: Path,
    temp_dir: Path,
    width: int,
    height: int,
) -> None:
    events = _frame_events(segments, duration)
    concat_lines: list[str] = []
    frame_paths: list[Path] = []

    for frame_number, (active_index, frame_duration) in enumerate(events):
        frame_path = temp_dir / f"frame_{frame_number:05d}.png"
        image = render_lyrics_frame(
            title=title,
            segments=segments,
            active_index=active_index,
            width=width,
            height=height,
        )
        image.save(frame_path, format="PNG", optimize=True)
        frame_paths.append(frame_path)
        concat_lines.append(f"file '{_concat_escape(frame_path)}'")
        concat_lines.append(f"duration {frame_duration:.6f}")

    # The concat demuxer applies the last duration only when the final image is
    # repeated without another duration entry.
    concat_lines.append(f"file '{_concat_escape(frame_paths[-1])}'")
    concat_path = temp_dir / "frames.txt"
    concat_path.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")

    subprocess_utils.check_call(
        [
            FFMPEG_BIN,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-t",
            f"{duration:.6f}",
            "-fps_mode",
            "vfr",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-an",
            str(output_path),
        ],
        timeout=7200,
    )


def render_lyrics_frame(
    *,
    title: str,
    segments: list[Segment],
    active_index: int,
    width: int = DEFAULT_VIDEO_WIDTH,
    height: int = DEFAULT_VIDEO_HEIGHT,
) -> Image.Image:
    """Create one control-free frame using the GUI's layout and colors."""
    image = Image.new("RGB", (width, height), WINDOW_BG)
    draw = ImageDraw.Draw(image)
    scale = min(width / 720.0, height / 640.0)

    title_font = _load_font(max(20, round(22 * scale)), bold=True)
    line_font = _load_font(max(18, round(17 * scale)))
    active_font = _load_font(max(20, round(19 * scale)), bold=True)

    margin_x = max(24, round(24 * scale))
    title_top = max(14, round(16 * scale))
    title_max_width = width - 2 * margin_x
    title_lines = _wrap_text(draw, title, title_font, title_max_width)
    title_line_height = _font_line_height(draw, title_font)
    for index, line in enumerate(title_lines[:2]):
        bbox = draw.textbbox((0, 0), line, font=title_font)
        text_width = bbox[2] - bbox[0]
        draw.text(
            ((width - text_width) / 2, title_top + index * title_line_height),
            line,
            font=title_font,
            fill=TITLE_COLOR,
        )

    title_height = min(2, len(title_lines)) * title_line_height
    panel_left = margin_x
    panel_right = width - margin_x
    panel_top = title_top + title_height + max(14, round(16 * scale))
    panel_bottom = height - max(22, round(22 * scale))
    draw.rectangle(
        (panel_left, panel_top, panel_right, panel_bottom),
        fill=LYRICS_BG,
        outline=LYRICS_BORDER,
        width=max(1, round(scale)),
    )

    panel_pad_x = max(24, round(28 * scale))
    panel_pad_y = max(14, round(16 * scale))
    viewport_left = panel_left + panel_pad_x
    viewport_right = panel_right - panel_pad_x
    viewport_top = panel_top + panel_pad_y
    viewport_bottom = panel_bottom - panel_pad_y
    max_text_width = viewport_right - viewport_left

    blocks: list[tuple[list[str], ImageFont.FreeTypeFont, int]] = []
    line_gap = max(8, round(9 * scale))
    for index, segment in enumerate(segments):
        font = active_font if index == active_index else line_font
        wrapped = _wrap_text(draw, segment.text.strip() or "·", font, max_text_width)
        block_height = len(wrapped) * _font_line_height(draw, font) + line_gap
        blocks.append((wrapped, font, block_height))

    total_height = sum(block[2] for block in blocks)
    viewport_height = viewport_bottom - viewport_top
    active_center = 0.0
    cursor = 0
    for index, (_lines, _font, block_height) in enumerate(blocks):
        if index == active_index:
            active_center = cursor + block_height / 2
            break
        cursor += block_height

    max_scroll = max(0.0, total_height - viewport_height)
    scroll = max(0.0, min(active_center - viewport_height / 2, max_scroll))
    y = viewport_top - scroll

    for index, (wrapped, font, block_height) in enumerate(blocks):
        line_height = _font_line_height(draw, font)
        text_height = len(wrapped) * line_height
        text_top = y + (block_height - line_gap - text_height) / 2
        if y + block_height >= viewport_top and y <= viewport_bottom:
            for line_number, line in enumerate(wrapped):
                line_y = text_top + line_number * line_height
                if line_y + line_height < viewport_top or line_y > viewport_bottom:
                    continue
                bbox = draw.textbbox((0, 0), line, font=font)
                text_width = bbox[2] - bbox[0]
                draw.text(
                    ((width - text_width) / 2, line_y),
                    line,
                    font=font,
                    fill=line_color(index, active_index),
                )
        y += block_height

    return image


def _frame_events(segments: list[Segment], duration: float) -> list[tuple[int, float]]:
    """Return ``(active_index, duration)`` frames for line-change events."""
    duration = max(0.1, float(duration))
    if not segments:
        return [(-1, duration)]

    activations: list[tuple[float, int]] = [(0.0, 0)]
    for index, segment in enumerate(segments[1:], start=1):
        start = max(0.0, min(float(segment.start), duration))
        if start <= activations[-1][0] + 0.001:
            activations[-1] = (activations[-1][0], index)
        elif start < duration:
            activations.append((start, index))

    events: list[tuple[int, float]] = []
    for index, (start, active_index) in enumerate(activations):
        end = activations[index + 1][0] if index + 1 < len(activations) else duration
        events.append((active_index, max(0.001, end - start)))
    return events


def _mux_audio(
    *,
    visual_path: Path,
    audio_path: Path,
    output_path: Path,
    title: str,
    mode: str,
) -> None:
    subprocess_utils.check_call(
        [
            FFMPEG_BIN,
            "-y",
            "-i",
            str(visual_path),
            "-i",
            str(audio_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-metadata",
            f"title={title} ({mode.title()})",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        timeout=1200,
    )
    stage.info("%s video -> %s", mode.title(), output_path)


def _load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        [
            Path("C:/Windows/Fonts/seguisb.ttf"),
            Path("C:/Windows/Fonts/segoeuib.ttf"),
        ]
        if bold
        else [Path("C:/Windows/Fonts/segoeui.ttf")]
    )
    candidates.extend(
        [
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
            if bold
            else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")
            if bold
            else Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default(size=size)


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    words = text.split()
    if not words:
        return ["·"]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _font_line_height(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont) -> int:
    bbox = draw.textbbox((0, 0), "Ag", font=font)
    return max(1, bbox[3] - bbox[1] + 5)


def _concat_escape(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", r"'\''")


def _probe_duration(audio_path: Path) -> float:
    """Use ffprobe to get the duration in seconds."""
    cmd = [
        FFPROBE_BIN,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    result = subprocess_utils.check_call(cmd)
    try:
        return float(result.stdout.strip())
    except (ValueError, TypeError):
        stage.warning("Could not probe duration; defaulting to 300 s")
        return 300.0
