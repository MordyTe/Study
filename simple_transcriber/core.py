"""Pure logic for the speaker transcriber — no audio devices, no ASR model.

Kept separate from the window/capture code so it can be unit-tested anywhere.
Only depends on numpy.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import List, Optional

import numpy as np

TARGET_SR = 16000  # what the Whisper model expects


def to_mono(data: np.ndarray) -> np.ndarray:
    """``[frames, channels]`` (or 1-D) float audio -> 1-D float32 mono."""

    data = np.asarray(data, dtype=np.float32)
    if data.ndim == 2:
        data = data.mean(axis=1)
    return data.astype(np.float32, copy=False)


def resample(signal: np.ndarray, orig_sr: int, target_sr: int = TARGET_SR) -> np.ndarray:
    """Resample mono audio. Integer ratios (48k->16k) use block averaging, which
    doubles as a simple anti-alias filter; other ratios use linear interpolation."""

    signal = np.asarray(signal, dtype=np.float32)
    if orig_sr == target_sr or signal.size == 0:
        return signal
    if orig_sr % target_sr == 0:
        factor = orig_sr // target_sr
        usable = (signal.size // factor) * factor
        return signal[:usable].reshape(-1, factor).mean(axis=1).astype(np.float32)
    n_out = int(round(signal.size * target_sr / orig_sr))
    x_old = np.linspace(0.0, 1.0, num=signal.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
    return np.interp(x_new, x_old, signal).astype(np.float32)


class Chunker:
    """Cut a continuous 16 kHz stream into speech chunks for the model.

    A chunk is emitted when speech is followed by ``silence_s`` of quiet (a
    natural pause), or when it reaches ``max_s`` (so long monologues still show
    up regularly). Pure silence is never emitted — only a short pre-roll is kept
    so the first syllable isn't clipped.
    """

    FRAME = 480  # 30 ms at 16 kHz

    def __init__(
        self,
        sample_rate: int = TARGET_SR,
        threshold: float = 0.004,
        silence_s: float = 0.8,
        min_s: float = 1.0,
        max_s: float = 15.0,
        preroll_s: float = 0.3,
    ):
        self.sr = sample_rate
        self.threshold = threshold
        self.silence_frames = int(silence_s * sample_rate / self.FRAME)
        self.min_samples = int(min_s * sample_rate)
        self.max_samples = int(max_s * sample_rate)
        self.preroll_frames = max(1, int(preroll_s * sample_rate / self.FRAME))
        self._frames: List[np.ndarray] = []
        self._pending = np.zeros(0, dtype=np.float32)
        self._has_speech = False
        self._quiet_run = 0

    def _is_loud(self, frame: np.ndarray) -> bool:
        return float(np.sqrt(np.mean(frame * frame))) > self.threshold

    def _take(self) -> np.ndarray:
        chunk = np.concatenate(self._frames) if self._frames else np.zeros(0, np.float32)
        self._frames = []
        self._has_speech = False
        self._quiet_run = 0
        return chunk

    def feed(self, signal: np.ndarray) -> List[np.ndarray]:
        """Add audio; return any chunks that are now complete."""

        out: List[np.ndarray] = []
        data = np.concatenate([self._pending, np.asarray(signal, dtype=np.float32)])
        n_full = (data.size // self.FRAME) * self.FRAME
        self._pending = data[n_full:]

        for start in range(0, n_full, self.FRAME):
            frame = data[start : start + self.FRAME]
            self._frames.append(frame)
            if self._is_loud(frame):
                self._has_speech = True
                self._quiet_run = 0
            else:
                self._quiet_run += 1

            size = len(self._frames) * self.FRAME
            if not self._has_speech:
                # Only silence so far: keep just a short pre-roll.
                if len(self._frames) > self.preroll_frames:
                    self._frames = self._frames[-self.preroll_frames :]
            elif size >= self.max_samples:
                out.append(self._take())
            elif self._quiet_run >= self.silence_frames and size >= self.min_samples:
                out.append(self._take())
        return out

    def flush(self) -> Optional[np.ndarray]:
        """Return whatever speech is buffered (call when stopping)."""

        if not self._has_speech:
            self._frames = []
            return None
        chunk = self._take()
        return chunk if chunk.size else None


def format_line(text: str, when: datetime) -> str:
    return f"[{when:%H:%M:%S}] {text.strip()}"


def new_transcript_path(folder: str, now: datetime) -> str:
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"תמלול_{now:%Y-%m-%d_%H-%M}.txt")  # תמלול_...


class TranscriptWriter:
    """Append lines to a UTF-8 text file, flushing each one (nothing lost on a crash)."""

    def __init__(self, path: str):
        self.path = path

    def write_line(self, line: str) -> None:
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
