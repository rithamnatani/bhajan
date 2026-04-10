"""Subprocess helpers for calling external binaries."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Sequence

log = logging.getLogger("bhajan.subprocess")


def check_call(
    cmd: list[str | Path],
    *,
    cwd: Path | None = None,
    extra_env: dict[str, str] | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess:
    """Run *cmd* and raise on non-zero exit.

    Works reliably on both Windows and POSIX.  All paths are resolved /
    converted to strings automatically.
    """
    str_cmd = [str(p) for p in cmd]

    env: dict[str, str] | None = None
    if extra_env:
        env = dict(__import__("os").environ)
        env.update(extra_env)

    log.debug("Running: %s", " ".join(str_cmd))

    try:
        result = subprocess.run(
            str_cmd,
            capture_output=True,
            text=True,
            check=True,
            cwd=str(cwd) if cwd else None,
            env=env,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Executable not found: {str_cmd[0]!r}.  "
            "Make sure it is installed and on your PATH."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"Command timed out after {timeout}s: {str_cmd[0]}") from exc

    if result.stderr:
        log.debug("stderr:\n%s", result.stderr)
    if result.stdout:
        log.debug("stdout:\n%s", result.stdout)

    return result


def check_binary(binary: str) -> bool:
    """Return True if *binary* is discoverable via shutil.which."""
    import shutil

    return shutil.which(binary) is not None
