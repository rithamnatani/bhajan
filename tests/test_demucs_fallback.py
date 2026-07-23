"""Tests for the lightweight Demucs recovery path."""

from __future__ import annotations

import subprocess
from pathlib import Path

from bhajan.stages.separator_demucs import DemucsSeparator


def test_heavy_model_failure_retries_with_htdemucs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    audio = tmp_path / "normalized.wav"
    audio.write_bytes(b"audio")
    output = tmp_path / "stems"
    output.mkdir()
    calls: list[list[str]] = []

    separator = DemucsSeparator(model="htdemucs_ft", device="cpu")
    monkeypatch.setattr(separator, "available", lambda: True)

    def fake_check_call(cmd: list[str], timeout: int):
        calls.append(cmd)
        assert timeout == 3600
        model = cmd[cmd.index("--name") + 1]
        if model == "htdemucs_ft":
            raise subprocess.CalledProcessError(3221225477, cmd)

        generated = output / "htdemucs" / "normalized"
        generated.mkdir(parents=True)
        (generated / "vocals.wav").write_bytes(b"vocals")
        (generated / "no_vocals.wav").write_bytes(b"music")
        return object()

    monkeypatch.setattr(
        "bhajan.stages.separator_demucs.subprocess_utils.check_call",
        fake_check_call,
    )

    result = separator.separate(audio, output)

    assert [cmd[cmd.index("--name") + 1] for cmd in calls] == [
        "htdemucs_ft",
        "htdemucs",
    ]
    assert result.vocals_path == output / "vocals.wav"
    assert result.instrumental_path == output / "instrumental.wav"
