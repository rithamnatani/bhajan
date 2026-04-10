"""Logging and structured output utilities."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

console = Console(theme=Theme({"info": "bold cyan", "warn": "bold yellow", "error": "bold red", "success": "bold green"}))

LOG_FORMAT = "%(message)s"


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure the root logger for bhajan."""
    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=console,
                rich_tracebacks=True,
                show_time=False,
                markup=True,
            )
        ],
    )
    return logging.getLogger("bhajan")


class StageLogger:
    """Convenience wrapper that prefixes log messages with a stage name.

    Supports printf-style formatting: ``stage.info("Got %d items", n)``.
    """

    def __init__(self, logger: logging.Logger, stage: str) -> None:
        self._logger = logger
        self._prefix = f"[{stage}]"

    def _log(self, method: str, msg: str, *args, **kwargs) -> None:
        prefixed = f"{self._prefix} {msg}"
        log_func = getattr(self._logger, method)
        log_func(prefixed, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs) -> None:
        self._log("info", msg, *args, **kwargs)

    def debug(self, msg: str, *args, **kwargs) -> None:
        self._log("debug", msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs) -> None:
        self._log("warning", msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs) -> None:
        self._log("error", msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs) -> None:
        self._log("critical", msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs) -> None:
        self._log("exception", msg, *args, **kwargs)
