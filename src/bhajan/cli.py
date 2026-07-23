"""CLI entry point for the ``bhajan`` command.

Usage::

    bhajan "<youtube_url>" [OPTIONS]
    bhajan playboi carti   # fuzzy local library → GUI (words need not be quoted)
"""

from __future__ import annotations

from pathlib import Path

import click

from bhajan import __version__
from bhajan.config import (
    DEFAULT_DEMUCS_MODEL,
    DEFAULT_WHISPER_MODEL,
    resolve_device,
)
from bhajan.logger import console, setup_logging
from bhajan import subprocess_utils
from bhajan.utils import looks_like_stream_url


@click.command(
    epilog=(
        "PowerShell: quote URLs that contain &. Otherwise & splits the command.\n"
        '  Example: bhajan "https://www.youtube.com/watch?v=ID&list=..." --video'
    ),
)
@click.argument(
    "url_or_query",
    nargs=-1,
    type=str,
    required=True,
    metavar="URL_OR_SEARCH",
)
@click.option(
    "--output-dir", "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Root output directory.  Defaults to ./output.",
)
@click.option(
    "--whisper-model",
    type=click.Choice(["tiny", "base", "small", "medium", "large-v3"]),
    default=DEFAULT_WHISPER_MODEL,
    show_default=True,
    help="faster-whisper model size.  Larger = more accurate but slower.",
)
@click.option(
    "--device",
    type=click.Choice(["auto", "cpu", "cuda"]),
    default="auto",
    show_default=True,
    help="Device for AI inference. 'auto' uses GPU if available.",
)
@click.option(
    "--language",
    type=str,
    default=None,
    help="Language code for transcription (e.g., en, hi, fr). Auto-detect if not specified.",
)
@click.option(
    "--romanize/--no-romanize",
    default=True,
    show_default=True,
    help="Transliterate non-Latin lyrics to Latin (default: on). Use --no-romanize for native script.",
)
@click.option(
    "--no-fetch-lyrics",
    is_flag=True,
    help="Skip LRCLib lookup and always transcribe with Whisper.",
)
@click.option(
    "--confirm-lyrics/--no-confirm-lyrics",
    default=True,
    show_default=True,
    help="Review online lyrics before use; disable for unattended runs.",
)
@click.option(
    "--separation-backend",
    type=click.Choice(["demucs", "audio-separator"]),
    default="demucs",
    show_default=True,
    help="Source separation backend. audio-separator requires the package to be installed.",
)
@click.option(
    "--transcription-backend",
    type=click.Choice(["whisper", "parakeet"]),
    default="whisper",
    show_default=True,
    help="Transcription backend. Parakeet requires NVIDIA GPU and NeMo (Linux only).",
)
@click.option(
    "--demucs-model",
    type=str,
    default=DEFAULT_DEMUCS_MODEL,
    show_default=True,
    help="Demucs model name (only used with demucs backend).",
)
@click.option(
    "--separator-model",
    type=str,
    default="UVR-MDX-NET_Voc_FT.onnx",
    show_default=True,
    help="Model for audio-separator backend (e.g., UVR-MDX-NET models).",
)
@click.option(
    "--keep-intermediate/--no-keep-intermediate",
    default=False,
    show_default=True,
    help="Keep intermediate files (source audio, stems, etc.). Default: cleanup enabled.",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Enable debug-level logging.",
)
@click.option(
    "--skip-download", is_flag=True, help="Resume from after download stage."
)
@click.option(
    "--skip-normalize", is_flag=True, help="Resume from after normalization."
)
@click.option(
    "--skip-separate", is_flag=True, help="Resume from after separation."
)
@click.option(
    "--skip-transcribe", is_flag=True, help="Resume from after transcription."
)
@click.option(
    "--gui",
    is_flag=True,
    help="Launch the GUI karaoke player after processing (default: export files only).",
)
@click.option(
    "--video",
    is_flag=True,
    help="Also render an MP4 karaoke video in final/ (default: off).",
)
@click.version_option(version=__version__, prog_name="bhajan")
def main(
    url_or_query: tuple[str, ...],
    output_dir: Path | None,
    whisper_model: str,
    device: str,
    language: str | None,
    romanize: bool,
    no_fetch_lyrics: bool,
    confirm_lyrics: bool,
    separation_backend: str,
    transcription_backend: str,
    demucs_model: str,
    separator_model: str,
    keep_intermediate: bool,
    verbose: bool,
    skip_download: bool,
    skip_normalize: bool,
    skip_separate: bool,
    skip_transcribe: bool,
    gui: bool,
    video: bool,
) -> None:
    """Generate karaoke from a stream URL, or fuzzy-open a song already under ``--output-dir``.

    **URLs:** Any ``http(s)://`` link, or a YouTube host without a scheme
    (``youtu.be/...``, ``youtube.com/...``), runs the download pipeline.

    **Local search:** Any other text (one or more words) fuzzy-matches folder names
    under the output directory (up to five picks); choose a number to open the GUI.

    By default writes ``final/instrumental.ogg``, ``final/lyrics.txt``, and
    ``final/transcript.json``. Use ``--video`` for an MP4 render, or ``--gui``
    for the interactive player after processing a URL.
    """
    setup_logging(verbose)

    qraw = " ".join(url_or_query).strip()
    if not qraw:
        raise click.UsageError("Missing URL or search text.")

    out = output_dir or Path("output")

    if not looks_like_stream_url(qraw):
        if video:
            console.print(
                "[bold red]Error:[/] --video requires a stream URL, not a local search string."
            )
            raise SystemExit(1)
        if gui:
            console.print(
                "[dim]Note:[/] --gui is only used after processing a URL; "
                "local search always opens the player."
            )
        from bhajan.local_library import run_local_fuzzy_gui  # noqa: PLC0415

        run_local_fuzzy_gui(qraw, out)
        return

    # ---- pre-flight checks (download pipeline) ----
    _preflight()

    resolved_device = resolve_device(device)
    if device == "auto":
        console.print(
            f"[dim]Device:[/] {resolved_device}"
            f"{'  (CUDA auto-detected)' if resolved_device == 'cuda' else ''}"
        )

    from bhajan.pipeline import KaraokePipeline  # noqa: PLC0415

    pipeline = KaraokePipeline(
        url=qraw,
        output_dir=output_dir,
        whisper_model=whisper_model,
        transcription_backend=transcription_backend,
        separation_backend=separation_backend,
        demucs_model=demucs_model,
        separator_model=separator_model,
        device=resolved_device,
        language=language,
        romanize=romanize,
        fetch_lyrics=not no_fetch_lyrics,
        confirm_lyrics=confirm_lyrics,
        keep_intermediate=keep_intermediate,
        skip_download=skip_download,
        skip_normalize=skip_normalize,
        skip_separate=skip_separate,
        skip_transcribe=skip_transcribe,
        skip_render=not video,
        gui=gui and not video,
    )

    try:
        pipeline.run()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/]")
        raise SystemExit(1)
    except Exception as exc:
        console.print(f"\n[bold red]Error:[/] {exc}")
        if verbose:
            console.print_exception()
        raise SystemExit(1)


def _preflight() -> None:
    """Check that all required external binaries / packages are available."""
    issues: list[str] = []

    if not subprocess_utils.check_binary("ffmpeg"):
        issues.append(
            "ffmpeg is not on your PATH.\n"
            "  Install: https://ffmpeg.org/download.html\n"
            "  Windows: download static build and add the bin\\ folder to PATH."
        )

    if not subprocess_utils.check_binary("ffprobe"):
        issues.append(
            "ffprobe is not on your PATH.\n"
            "  It ships with ffmpeg -- same install instructions apply."
        )

    if issues:
        console.print("[bold red]Pre-flight check failed:[/]")
        for issue in issues:
            console.print(f"  - {issue}")
        raise SystemExit(1)

    console.print("[green]Pre-flight check passed.[/] ffmpeg, ffprobe found on PATH.")
