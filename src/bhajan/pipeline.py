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
import sys
from pathlib import Path

from bhajan.config import (
    DEFAULT_DEMUCS_MODEL,
    DEFAULT_DEVICE,
    DEFAULT_WHISPER_MODEL,
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
from bhajan.stages.audio_modes import export_audio_modes
from bhajan.stages.render import render_video_suite
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
        confirm_lyrics: bool = True,
        karaoke_mode: str = "instrumental",
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
        self.confirm_lyrics = confirm_lyrics
        self.karaoke_mode = karaoke_mode
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
        video_info: dict | None = None
        if not self._skip["download"]:
            # We need metadata to name the output folder, so we peek at it
            from yt_dlp import YoutubeDL  # noqa: PLC0415
            with YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
                video_info = ydl.extract_info(self.url, download=False)
                title = video_info.get("title") or "unnamed"
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
                from bhajan.stages.lyrics_fetch import (  # noqa: PLC0415
                    fetch_lyrics_match_from_youtube_title,
                    review_online_lyrics,
                )

                # Get metadata for lyrics search
                if video_info is None:
                    from yt_dlp import YoutubeDL  # noqa: PLC0415

                    with YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
                        video_info = ydl.extract_info(self.url, download=False)
                raw_title = video_info.get("title") or "unnamed"
                artist_meta = video_info.get("artist") or video_info.get("creator")
                duration = video_info.get("duration")
                album_name = video_info.get("album")

                lyrics_match, parsed_track = fetch_lyrics_match_from_youtube_title(
                    title=raw_title,
                    artist_meta=artist_meta,
                    duration=float(duration) if duration is not None else None,
                    album_youtube=album_name,
                )

                if (
                    lyrics_match is not None
                    and self.confirm_lyrics
                    and sys.stdin.isatty()
                ):
                    lyrics_match = review_online_lyrics(
                        lyrics_match,
                        search_query=parsed_track,
                        duration=float(duration) if duration is not None else None,
                    )

                transcript = lyrics_match.transcript if lyrics_match is not None else None
                
                if transcript is None:
                    self.stage_logger.warning(
                        "Online lyrics unavailable or declined; falling back to transcription"
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
        generate_ass(transcript, self.subtitles_dir)
        generate_lrc(transcript, self.subtitles_dir)

        # ---- Stage 6: Final outputs (instrumental + lyrics), optional video / GUI ----
        lyrics_path, audio_modes = self._export_simple_final(
            original_path=norm_path,
            vocals_path=vocals_path,
            instrumental_path=instrumental_path,
            transcript=transcript,
        )

        if self.gui:
            # Launch GUI player instead of rendering video
            self.stage_logger.info("Launching GUI karaoke player ...")
            from bhajan.gui_player import play_karaoke  # noqa: PLC0415

            # Get title for window
            title = self.song_dir.name.replace("_", " ") if self.song_dir else "Karaoke"
            play_karaoke(
                audio_path=audio_modes[self.karaoke_mode],
                transcript=transcript,
                title=title,
            )
            (self.final_dir / "gui_session.txt").write_text("GUI karaoke session completed.\n")
            final_path = lyrics_path
        elif not self._skip["render"]:
            videos = render_video_suite(
                title=self.song_dir.name.replace("_", " "),
                transcript=transcript,
                audio_tracks=audio_modes,
                output_dir=self.final_dir,
            )
            final_path = videos["instrumental"]
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

    def _export_simple_final(
        self,
        *,
        original_path: Path,
        vocals_path: Path,
        instrumental_path: Path,
        transcript: Transcript,
    ) -> tuple[Path, dict[str, Path]]:
        """Write the three GUI-safe audio modes and lyric artifacts."""
        self.final_dir.mkdir(parents=True, exist_ok=True)
        audio_modes = export_audio_modes(
            original_path=original_path,
            vocals_path=vocals_path,
            instrumental_path=instrumental_path,
            transcript=transcript,
            output_dir=self.final_dir,
        )

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

        return lyrics_path, audio_modes

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
