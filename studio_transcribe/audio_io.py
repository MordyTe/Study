"""Audio input: read a multichannel recording and hand each channel to the ASR
engine as 16 kHz mono float32 (Whisper's native format).

Depends on ``soundfile`` (libsndfile) for decoding and, preferably, ``soxr``
for high-quality resampling. Both are imported lazily; a NumPy linear-interp
fallback is used if ``soxr`` is missing (fine for a quick test, not for
production accuracy).

Two input shapes are supported:

* **One multichannel file** (e.g. a 32-channel WAV captured off the X32): each
  configured channel ``index`` (1-based mic number) maps to file channel
  ``index - 1``.
* **A directory of per-channel files**: files are matched by the channel number
  appearing in the name (``ch01.wav``, ``mic_1.wav``, ``track01.wav`` …).
"""

from __future__ import annotations

import glob
import os
import re
from typing import Iterator, List, Tuple


def _load_soundfile():
    try:
        import soundfile as sf  # type: ignore

        return sf
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "soundfile is required to read audio: pip install soundfile"
        ) from exc


def read_audio(path: str):
    """Return ``(data, sample_rate)`` where data is float32 ``[frames, channels]``."""

    sf = _load_soundfile()
    import numpy as np  # type: ignore

    data, sr = sf.read(path, dtype="float32", always_2d=True)
    return np.asarray(data, dtype=np.float32), int(sr)


def resample_mono(signal, orig_sr: int, target_sr: int = 16000):
    """Resample a 1-D float32 signal to ``target_sr``."""

    import numpy as np  # type: ignore

    if orig_sr == target_sr:
        return np.asarray(signal, dtype=np.float32)

    try:
        import soxr  # type: ignore

        return np.asarray(
            soxr.resample(signal, orig_sr, target_sr), dtype=np.float32
        )
    except ImportError:
        # Low-quality fallback: linear interpolation. Install soxr for accuracy.
        duration = len(signal) / orig_sr
        n_out = int(round(duration * target_sr))
        if n_out <= 0:
            return np.zeros(0, dtype=np.float32)
        x_old = np.linspace(0.0, duration, num=len(signal), endpoint=False)
        x_new = np.linspace(0.0, duration, num=n_out, endpoint=False)
        return np.interp(x_new, x_old, signal).astype(np.float32)


def extract_channel(data, channel_index_0based: int, orig_sr: int, target_sr: int = 16000):
    """Pull one channel out of ``[frames, channels]`` data as 16 kHz mono."""

    import numpy as np  # type: ignore

    if channel_index_0based >= data.shape[1]:
        raise IndexError(
            f"channel {channel_index_0based} not present (file has {data.shape[1]})"
        )
    mono = data[:, channel_index_0based]
    return resample_mono(np.ascontiguousarray(mono), orig_sr, target_sr)


def _match_channel_file(directory: str, channel: int) -> str:
    """Find a per-channel file in ``directory`` whose name carries ``channel``."""

    candidates = sorted(
        glob.glob(os.path.join(directory, "*.wav"))
        + glob.glob(os.path.join(directory, "*.flac"))
    )
    for cand in candidates:
        name = os.path.basename(cand)
        numbers = [int(n) for n in re.findall(r"\d+", name)]
        if channel in numbers:
            return cand
    raise FileNotFoundError(
        f"no per-channel file for channel {channel} in {directory}"
    )


def iter_channels(
    input_path: str,
    channels: List[int],
    target_sr: int = 16000,
) -> Iterator[Tuple[int, "object"]]:
    """Yield ``(channel_number, mono_16k_signal)`` for each requested channel.

    ``channels`` are 1-based microphone/channel numbers as in the config.
    """

    if os.path.isdir(input_path):
        for ch in channels:
            path = _match_channel_file(input_path, ch)
            data, sr = read_audio(path)
            yield ch, extract_channel(data, 0, sr, target_sr)
    else:
        data, sr = read_audio(input_path)
        for ch in channels:
            yield ch, extract_channel(data, ch - 1, sr, target_sr)
