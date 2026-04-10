"""Pipeline stage: download audio from YouTube."""

from __future__ import annotations

import logging
from pathlib import Path

import yt_dlp

from bhajan.config import FFMPEG_BIN
from bhajan.logger import StageLogger
from bhajan.utils import safe_filename

log = logging.getLogger("bhajan")
stage = StageLogger(log, "download")


class DownloadResult:
    """Holds paths and metadata after a successful download."""

    def __init__(self, audio_path: Path, title: str, video_id: str) -> None:
        self.audio_path = audio_path
        self.title = title
        self.video_id = video_id


def download(url: str, source_dir: Path) -> DownloadResult:
    """Download the best audio stream from *url* into *source_dir*.

    Returns a :class:`DownloadResult` with the path to the downloaded file.
    """
    stage.info("Fetching metadata for %s", url)
    stage.debug("Source directory: %s", source_dir)

    # ---- metadata pass (no download) ----
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl_meta:
        info = ydl_meta.extract_info(url, download=False)
        title: str = info.get("title") or "unnamed"
        video_id: str = info.get("id") or "unknown"
    
    stage.info("Video title: %s", title)
    stage.debug("Video ID: %s", video_id)

    safe_name = safe_filename(title)
    # Prefer m4a/aac from yt-dlp since it's already compressed well
    out_tmpl = str(source_dir / f"{safe_name}.%(ext)s")

    ydl_opts: dict = {
        "format": "bestaudio/best",
        "outtmpl": out_tmpl,
        "quiet": False,
        "no_warnings": False,
        "noplaylist": True,
        "ffmpeg_location": FFMPEG_BIN,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
                "preferredquality": "192",
            }
        ],
    }

    stage.info("Downloading audio (this may take a while) ...")
    stage.debug("Download options: format=bestaudio/best, codec=m4a")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(url, download=True)
        # yt-dlp returns the processed filename after postprocessing
        requested = result.get("requested_downloads") or [result]
        # Find the audio file yt-dlp wrote
        for entry in requested:
            fp = entry.get("filepath") or entry.get("_filename")
            if fp:
                downloaded_path = Path(fp)
                if downloaded_path.exists():
                    file_size_mb = downloaded_path.stat().st_size / 1_048_576
                    stage.info("Downloaded -> %s", downloaded_path)
                    stage.debug("File size: %.2f MB", file_size_mb)
                    return DownloadResult(downloaded_path, title, video_id)

    # Fallback: glob the source dir for the most recent file
    candidates = sorted(source_dir.glob(f"{safe_name}.*"), key=lambda p: p.stat().st_mtime)
    if candidates:
        stage.info("Downloaded -> %s", candidates[-1])
        return DownloadResult(candidates[-1], title, video_id)

    raise FileNotFoundError(
        f"yt-dlp did not produce an output file in {source_dir}. "
        "Check the URL and your network connection."
    )
