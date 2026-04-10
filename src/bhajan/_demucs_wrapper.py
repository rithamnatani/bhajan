"""Thin wrapper that patches torchaudio.save for demucs on Windows.

torchaudio >= 2.9 delegates save() to torchcodec, which requires
FFmpeg *shared* libraries (.dll).  On many Windows installs only the
static ffmpeg binary is present.  This module replaces save() with a
soundfile-based writer so demucs can export WAV stems without torchcodec.

Usage:  python -m bhajan._demucs_wrapper [demucs args...]
"""

import sys


def _patch_torchaudio_save():
    import torch  # noqa: F811
    import torchaudio
    import soundfile as sf

    def _sf_save(uri, src, sample_rate, channels_first=True, **_kw):
        if not isinstance(src, torch.Tensor):
            raise TypeError(f"Expected torch.Tensor, got {type(src)}")
        if channels_first and src.dim() == 2:
            src = src.T
        sf.write(str(uri), src.cpu().numpy(), sample_rate)

    torchaudio.save = _sf_save


if __name__ == "__main__":
    _patch_torchaudio_save()
    from demucs.separate import main

    main()
