"""Demucs-based source separation backend."""

from __future__ import annotations

import importlib.util
import logging
import os
import shutil
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path

from bhajan import subprocess_utils
from bhajan.config import DEFAULT_DEMUCS_MODEL, DEFAULT_DEVICE, FFMPEG_BIN
from bhajan.logger import StageLogger
from bhajan.stages.separator_base import SeparationResult, SeparatorBackend

log = logging.getLogger("bhajan")
stage = StageLogger(log, "separate")


def _unlink_for_overwrite(path: Path) -> None:
    """Remove *path* if it exists so ffmpeg can recreate it (avoids WinError 5 / Permission denied)."""
    if not path.exists():
        return
    for attempt in range(12):
        try:
            if sys.platform == "win32":
                try:
                    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
                except OSError:
                    pass
            path.unlink()
            return
        except OSError:
            time.sleep(0.06 * (attempt + 1))
    raise RuntimeError(
        f"Cannot remove or overwrite {path}. Close programs using this file "
        "(Explorer preview, media players, DAWs), then retry."
    )


def _install_mixed_output(tmp_path: Path, dest: Path) -> Path:
    """Move *tmp_path* to *dest*. If *dest* is locked, keep *tmp_path* and return it."""
    try:
        _unlink_for_overwrite(dest)
    except RuntimeError:
        pass
    try:
        tmp_path.replace(dest)
        return dest
    except OSError:
        pass
    try:
        shutil.copy2(tmp_path, dest)
        try:
            tmp_path.unlink()
        except OSError:
            pass
        return dest
    except OSError:
        pass
    stage.warning(
        "Could not write %s (file may be open in Explorer or another app). "
        "Using mixed stem at %s for this run — delete or unlock %s and re-run to normalize paths.",
        dest,
        tmp_path,
        dest,
    )
    return tmp_path


class DemucsSeparator(SeparatorBackend):
    """Wraps the ``demucs`` CLI for two-stem (vocals + no-vocals) separation."""

    def __init__(self, model: str = DEFAULT_DEMUCS_MODEL, device: str = DEFAULT_DEVICE) -> None:
        self.model = model
        self.device = device

    def name(self) -> str:
        return "demucs"

    def available(self) -> bool:
        # Separation uses ``python -m bhajan._demucs_wrapper``, not the ``demucs``
        # console script.  ``uv tool`` / pip often put ``bhajan`` on PATH but not
        # the venv's ``Scripts/demucs`` entry point — check the package instead.
        return importlib.util.find_spec("demucs") is not None

    def separate(self, audio_path: Path, output_dir: Path) -> SeparationResult:
        if not self.available():
            raise RuntimeError(
                "Demucs CLI is not installed or not on PATH.\n"
                "Install it with:  pip install demucs\n"
                "Or install the full bhajan[dev] extras."
            )

        stage.info("Separating stems with Demucs (model=%s, device=%s) ...", self.model, self.device)
        stage.debug("Input audio: %s", audio_path)
        stage.debug("Output directory: %s", output_dir)

        # Demucs outputs into <output_dir>/<model>/<song_name>/
        # We invoke it via the Python module for reliability across platforms
        def command(model: str, device: str) -> list[str]:
            return [
                sys.executable,
                "-m",
                "bhajan._demucs_wrapper",
                "--name",
                model,
                "--out",
                str(output_dir),
                "--device",
                device,
                str(audio_path),
            ]

        cmd = command(self.model, self.device)
        stage.debug("Running command: %s", " ".join(cmd))

        # demucs can spawn heavy GPU processes; give generous timeout
        used_model = self.model
        try:
            subprocess_utils.check_call(cmd, timeout=3600)
        except subprocess.CalledProcessError as initial_error:
            attempts: list[tuple[str, str]] = []
            if self.device == "cuda":
                attempts.append((self.model, "cpu"))
            if self.model != "htdemucs":
                attempts.append(("htdemucs", "cpu"))

            last_error = initial_error
            for fallback_model, fallback_device in dict.fromkeys(attempts):
                stage.warning(
                    "Demucs failed; retrying with model=%s on %s...",
                    fallback_model,
                    fallback_device,
                )
                try:
                    subprocess_utils.check_call(
                        command(fallback_model, fallback_device),
                        timeout=3600,
                    )
                    used_model = fallback_model
                    break
                except subprocess.CalledProcessError as exc:
                    last_error = exc
            else:
                raise last_error

        # Demucs creates: <output_dir>/<model>/<filename_no_ext>/vocals.wav  etc.
        # We need to locate them regardless of exact nesting
        src_name = audio_path.stem
        search_root = output_dir / used_model / src_name
        stage.debug("Looking for Demucs output in: %s", search_root)

        if not search_root.exists():
            # Sometimes demucs uses the original filename including extension
            search_root = output_dir / used_model / audio_path.name
            if not search_root.exists():
                # Glob as fallback
                candidates = list((output_dir / used_model).glob(f"**/{src_name}"))
                if candidates:
                    search_root = candidates[0]
                    stage.debug("Found output via glob at: %s", search_root)

        vocals = _find_stem(search_root, "vocals")
        instrumental = _find_stem(search_root, "no_vocals") or _find_stem(search_root, "accompaniment")
        
        # If no instrumental stem found, create it by combining drums + other + bass (if available)
        if instrumental is None and vocals is not None:
            stage.debug("No instrumental stem found, creating from drums + other + bass")
            drums = _find_stem(search_root, "drums")
            other = _find_stem(search_root, "other")
            bass = _find_stem(search_root, "bass")
            
            # Combine available stems into instrumental
            instrumental_stems = [s for s in [drums, other, bass] if s is not None]
            if instrumental_stems:
                instrumental = _mix_instrumental(instrumental_stems, output_dir)
        
        stage.debug("Found vocals: %s", vocals)
        stage.debug("Found instrumental: %s", instrumental)

        if vocals is None or instrumental is None:
            raise FileNotFoundError(
                f"Demucs output not found in {search_root}. "
                "Expected vocals.wav and no_vocals.wav (or accompaniment.wav)."
            )

        # Move / rename stems to predictable names directly in output_dir
        dest_vocals = output_dir / "vocals.wav"
        dest_instrumental = output_dir / "instrumental.wav"

        if vocals.resolve() != dest_vocals.resolve():
            vocals.replace(dest_vocals)
        if instrumental.resolve() != dest_instrumental.resolve():
            try:
                instrumental = instrumental.replace(dest_instrumental)
            except OSError:
                stage.warning(
                    "Instrumental stem left at %s (could not move to instrumental.wav).",
                    instrumental,
                )

        stage.info("Vocals       -> %s (%.1f MB)", dest_vocals, dest_vocals.stat().st_size / 1_048_576)
        stage.info("Instrumental -> %s (%.1f MB)", instrumental, instrumental.stat().st_size / 1_048_576)

        return SeparationResult(vocals_path=dest_vocals, instrumental_path=instrumental)


def _find_stem(directory: Path, stem_name: str) -> Path | None:
    """Search *directory* recursively for a wav named like *stem_name*."""
    for candidate in directory.rglob(f"{stem_name}*.wav"):
        return candidate
    return None


def _mix_instrumental(stems: list[Path], output_dir: Path) -> Path:
    """Mix multiple stem files into a single instrumental file using ffmpeg."""
    output_path = output_dir / "instrumental.wav"
    stage.debug("Mixing instrumental from: %s", stems)
    n = len(stems)
    if n == 0:
        raise ValueError("No stems to mix")

    # Resolve paths for ffmpeg on Windows (avoids odd failures with long/relative paths).
    resolved = [p.resolve() for p in stems]
    out_abs = output_path.resolve()
    # Never write ffmpeg output directly to instrumental.wav: an existing file may be
    # locked (Explorer, AV), which yields Permission denied. Write a unique .wav, then install.
    tmp_out = (output_dir / f"instrumental_mix_{uuid.uuid4().hex}.wav").resolve()
    legacy_mix = out_abs.with_name(f"{out_abs.stem}_mixing{out_abs.suffix}")
    _unlink_for_overwrite(legacy_mix)

    if n == 1:
        cmd = [
            FFMPEG_BIN, "-y",
            "-i", str(resolved[0]),
            "-acodec", "pcm_s16le",
            "-f", "wav",
            str(tmp_out),
        ]
    else:
        inputs: list[str] = []
        for stem in resolved:
            inputs.extend(["-i", str(stem)])
        labels = "".join(f"[{i}:a]" for i in range(n))
        filter_complex = f"{labels}amix=inputs={n}:duration=longest[aout]"
        cmd = [
            FFMPEG_BIN, "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[aout]",
            "-f", "wav",
            str(tmp_out),
        ]

    try:
        subprocess_utils.check_call(cmd)
    except subprocess.CalledProcessError as exc:
        if tmp_out.exists():
            try:
                tmp_out.unlink()
            except OSError:
                pass
        detail = (exc.stderr or "").strip() or (exc.stdout or "").strip() or "(no ffmpeg output)"
        raise RuntimeError(
            f"ffmpeg failed while mixing instrumental stems (exit {exc.returncode}). {detail}"
        ) from exc

    final_path = _install_mixed_output(tmp_out, out_abs)
    stage.debug("Created instrumental: %s", final_path)
    return final_path
