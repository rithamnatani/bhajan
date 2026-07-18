"""Pipeline orchestrator -- ties all stages together.

This is the single entry point for the end-to-end karaoke generation
workflow.  Each stage is independent so that users can re-run from an
intermediate point if needed (not yet exposed in the CLI, but the
structure is ready).
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from bhajan import subprocess_utils
from bhajan.config import (
    DEFAULT_DEMUCS_MODEL,
    DEFAULT_DEVICE,
    DEFAULT_WHISPER_MODEL,
    FFMPEG_BIN,
    SUBDIRS,
)
from bhajan.romanize import romanize_transcript
from bhajan.logger import StageLogger, console
from bhajan.stages.download import download as stage_download
from bhajan.stages.normalize import normalize_audio as stage_normalize
from bhajan.stages.separator import run_separation as stage_separate
from bhajan.stages.transcription import (
    run_transcription as stage_transcribe,
    save_transcript as stage_save_transcript,
)
from bhajan.stages.transcription_base import Segment, Transcript, WordStamp
from bhajan.stages.subtitles import generate_ass, generate_lrc
from bhajan.stages.render import render_video as stage_render
from bhajan.utils import ensure_dirs, safe_filename, clean_youtube_url

log = logging.getLogger("bhajan")


class KaraokePipeline:
    """Configures and runs the full karaoke-generation pipeline."""

    def __init__(
        self,
        url: str,
        *,
        output_dir: Path | None = None,
        whisper_model: str = DEFAULT_WHISPER_MODEL,
        transcription_backend: str = "whisper",
        separation_backend: str = "demucs",
        demucs_model: str = DEFAULT_DEMUCS_MODEL,
        separator_model: str = "UVR-MDX-NET_Voc_FT.onnx",
        device: str = DEFAULT_DEVICE,
        language: str | None = None,
        romanize: bool = True,
        fetch_lyrics: bool = False,
        keep_intermediate: bool = False,
        skip_download: bool = False,
        skip_normalize: bool = False,
        skip_separate: bool = False,
        skip_transcribe: bool = False,
        skip_render: bool = False,
        gui: bool = False,
    ) -> None:
        self.url = url
        self.output_root = output_dir or Path("output")
        self.whisper_model = whisper_model
        self.transcription_backend = transcription_backend
        self.separation_backend = separation_backend
        self.demucs_model = demucs_model
        self.separator_model = separator_model
        self.device = device
        self.language = language
        self.romanize = romanize
        self.fetch_lyrics = fetch_lyrics
        self.keep_intermediate = keep_intermediate
        self.gui = gui

        # Skip flags for debugging / resuming
        self._skip = {
            "download": skip_download,
            "normalize": skip_normalize,
            "separate": skip_separate,
            "transcribe": skip_transcribe,
            "render": skip_render,
        }

        # Resolved paths (set during the run)
        self.song_dir: Path | None = None
        self.source_dir: Path | None = None
        self.stems_dir: Path | None = None
        self.transcript_dir: Path | None = None
        self.subtitles_dir: Path | None = None
        self.final_dir: Path | None = None

        self.stage_logger = StageLogger(log, "pipeline")

    def run(self) -> Path:
        """Execute the pipeline and return the path to the final video."""
        # Clean URL first
        self.url = clean_youtube_url(self.url)

        self.stage_logger.info("Starting karaoke pipeline")
        self.stage_logger.debug("URL: %s", self.url)
        self.stage_logger.debug("Device: %s", self.device)
        self.stage_logger.debug("Skip flags: %s", self._skip)
        
        # ---- Determine safe song name and layout directories ----
        if not self._skip["download"]:
            # We need metadata to name the output folder, so we peek at it
            from yt_dlp import YoutubeDL  # noqa: PLC0415
            with YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
                info = ydl.extract_info(self.url, download=False)
                title = info.get("title") or "unnamed"
        else:
            title = "resumed_session"

        safe_name = safe_filename(title, max_len=60)
        self.song_dir = self.output_root / safe_name
        ensure_dirs(self.song_dir, SUBDIRS)

        self.source_dir = self.song_dir / "source"
        self.stems_dir = self.song_dir / "stems"
        self.transcript_dir = self.song_dir / "transcript"
        self.subtitles_dir = self.song_dir / "subtitles"
        self.final_dir = self.song_dir / "final"

        console.print(f"\n[bold cyan]Song:[/] {title}")
        console.print(f"[bold cyan]Output:[/] {self.song_dir}\n")
        
        self.stage_logger.debug("Song directory: %s", self.song_dir)

        # ---- Stage 1: Download ----
        if self._skip["download"]:
            self.stage_logger.info("Skipping download (user requested)")
            candidates = sorted(self.source_dir.glob("*.*"), key=lambda p: p.stat().st_mtime)
            if not candidates:
                raise FileNotFoundError(
                    f"No source files found in {self.source_dir}. "
                    "Cannot skip download without existing files."
                )
            audio_path = candidates[-1]
        else:
            result = stage_download(self.url, self.source_dir)
            audio_path = result.audio_path

        # ---- Stage 2: Normalize ----
        if self._skip["normalize"]:
            self.stage_logger.info("Skipping normalization (user requested)")
            normalized = sorted(self.source_dir.glob("normalized.wav"))
            if not normalized:
                raise FileNotFoundError("No normalized.wav found; cannot skip normalization.")
            norm_path = normalized[0]
        else:
            norm_path = stage_normalize(audio_path, self.source_dir, name="normalized")

        # ---- Stage 3: Separate ----
        if self._skip["separate"]:
            self.stage_logger.info("Skipping separation (user requested)")
            vocals_path = self.stems_dir / "vocals.wav"
            instrumental_path = self.stems_dir / "instrumental.wav"
            if not vocals_path.exists() or not instrumental_path.exists():
                raise FileNotFoundError("Stem files not found; cannot skip separation.")
        else:
            # Determine model based on backend
            model_name = (
                self.separator_model
                if self.separation_backend == "audio-separator"
                else self.demucs_model
            )
            sep_result = stage_separate(
                norm_path,
                self.stems_dir,
                backend_name=self.separation_backend,
                model=model_name,
                device=self.device,
            )
            vocals_path = sep_result.vocals_path
            instrumental_path = sep_result.instrumental_path

        # ---- Stage 4: Transcribe ----
        if self._skip["transcribe"]:
            self.stage_logger.info("Skipping transcription (user requested)")
            t_path = self.transcript_dir / "transcript.json"
            if not t_path.exists():
                raise FileNotFoundError("No transcript.json found; cannot skip transcription.")
            transcript_data = json.loads(t_path.read_text(encoding="utf-8"))
            transcript = Transcript()
            for seg_d in transcript_data.get("segments", []):
                words = [WordStamp(**w) for w in seg_d.get("words", [])]
                transcript.segments.append(Segment(words=words))
        else:
            if self.fetch_lyrics:
                # Try to fetch lyrics from LRCLib
                from bhajan.stages.lyrics_fetch import fetch_lyrics_from_youtube_title  # noqa: PLC0415

                # Get metadata for lyrics search
                from yt_dlp import YoutubeDL  # noqa: PLC0415
                with YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
                    info = ydl.extract_info(self.url, download=False)
                    raw_title = info.get("title") or "unnamed"
                    artist_meta = info.get("artist") or info.get("creator")
                    duration = info.get("duration")
                    album_name = info.get("album")

                transcript = fetch_lyrics_from_youtube_title(
                    title=raw_title,
                    artist_meta=artist_meta,
                    duration=float(duration) if duration is not None else None,
                    album_youtube=album_name,
                )
                
                if transcript is None:
                    self.stage_logger.warning(
                        "Could not fetch lyrics from LRCLib, falling back to transcription"
                    )
                    transcript = stage_transcribe(
                        vocals_path,
                        backend_name=self.transcription_backend,
                        model_size=self.whisper_model,
                        device=self.device,
                        language=self.language,
                    )
            else:
                transcript = stage_transcribe(
                    vocals_path,
                    backend_name=self.transcription_backend,
                    model_size=self.whisper_model,
                    device=self.device,
                    language=self.language,
                )

        if self.romanize:
            transcript = romanize_transcript(transcript, self.language)

        if (not self._skip["transcribe"]) or self.romanize:
            stage_save_transcript(transcript, self.transcript_dir)

        # ---- Stage 5: Subtitles ----
        ass_path = generate_ass(transcript, self.subtitles_dir)
        generate_lrc(transcript, self.subtitles_dir)

        # ---- Stage 6: Final outputs (instrumental + lyrics), optional video / GUI ----
        lyrics_path = self._export_simple_final(instrumental_path, transcript)

        if self.gui:
            # Launch GUI player instead of rendering video
            self.stage_logger.info("Launching GUI karaoke player ...")
            from bhajan.gui_player import play_karaoke  # noqa: PLC0415

            # Get title for window
            title = self.song_dir.name.replace("_", " ") if self.song_dir else "Karaoke"
            play_karaoke(
                audio_path=instrumental_path,
                transcript=transcript,
                title=title,
            )
            (self.final_dir / "gui_session.txt").write_text("GUI karaoke session completed.\n")
            final_path = lyrics_path
        elif not self._skip["render"]:
            final_path = stage_render(
                instrumental_path=instrumental_path,
                ass_path=ass_path,
                output_path=self.final_dir / "final_karaoke.mp4",
            )
        else:
            final_path = lyrics_path

        # ---- Cleanup (optional) ----
        if not self.keep_intermediate:
            self._cleanup_intermediate()

        if self.gui:
            console.print("\n[bold green]Done![/]  Karaoke session complete.")
        else:
            console.print(f"\n[bold green]Done![/]  Primary output -> {final_path}")
        return final_path

    def _export_simple_final(self, instrumental_path: Path, transcript: Transcript) -> Path:
        """Encode GUI-safe audio in ``final/`` and write the lyric artifacts."""
        self.final_dir.mkdir(parents=True, exist_ok=True)
        audio_ogg = self.final_dir / "instrumental.ogg"
        try:
            subprocess_utils.check_call(
                [
                    FFMPEG_BIN,
                    "-y",
                    "-i",
                    str(instrumental_path),
                    "-c:a",
                    "libvorbis",
                    "-q:a",
                    "5",
                    str(audio_ogg),
                ],
                timeout=600,
            )
            self.stage_logger.info("Wrote instrumental audio -> %s", audio_ogg)
        except Exception as exc:
            self.stage_logger.warning(
                "Could not encode instrumental to OGG (%s); copying WAV instead.",
                exc,
            )
            if audio_ogg.exists():
                try:
                    audio_ogg.unlink()
                except OSError:
                    pass
            audio_wav = self.final_dir / "instrumental.wav"
            shutil.copy2(instrumental_path, audio_wav)
            self.stage_logger.info("Wrote instrumental audio -> %s", audio_wav)

        lyrics_path = self.final_dir / "lyrics.txt"
        lines = [seg.text.strip() for seg in transcript.segments if seg.text.strip()]
        lyrics_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        self.stage_logger.info("Wrote lyrics -> %s", lyrics_path)

        transcript_path = self.final_dir / "transcript.json"
        transcript_path.write_text(
            json.dumps(transcript.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self.stage_logger.info("Wrote word timings for replay -> %s", transcript_path)

        return lyrics_path

    def _cleanup_intermediate(self) -> None:
        """Remove large intermediate files after a successful run."""
        self.stage_logger.info("Cleaning up intermediate files ...")
        # Keep only the final directory; remove the rest
        for subdir in ["source", "stems", "transcript", "subtitles"]:
            d = self.song_dir / subdir
            if d.exists():

                def _onerror(func: object, p: str, exc_info: tuple) -> None:
                    err = exc_info[1]
                    self.stage_logger.warning(
                        "Cleanup: could not remove %s (%s). "
                        "Close Explorer or apps using files in that folder, then delete it manually.",
                        p,
                        err,
                    )

                shutil.rmtree(d, onerror=_onerror)
        self.stage_logger.info("Cleanup complete.")
