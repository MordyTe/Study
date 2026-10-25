"""Voice Activity Detection helpers (Silero) for the streaming / capture path.

The offline faster-whisper engine already applies Silero via ``vad_filter=True``.
This standalone wrapper is for the live layer and for pre-gating a channel so
only genuinely active microphones create ASR work (saves GPU when many mics are
patched but only a few are talking).

``torch`` + the Silero model are imported lazily.
"""

from __future__ import annotations

from typing import List, Tuple


def energy_gate(signal, frame_ms: int = 30, sample_rate: int = 16000, threshold: float = 1e-4) -> bool:
    """Cheap pre-gate: is there any frame whose RMS energy exceeds ``threshold``?

    Used to skip Silero entirely on a silent channel.
    """

    import numpy as np  # type: ignore

    frame = max(1, int(sample_rate * frame_ms / 1000))
    sig = np.asarray(signal, dtype=np.float32)
    if sig.size == 0:
        return False
    n = (sig.size // frame) * frame
    if n == 0:
        return float(np.sqrt(np.mean(sig ** 2))) > threshold
    frames = sig[:n].reshape(-1, frame)
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    return bool(np.any(rms > threshold))


class SileroVad:
    """Lazy wrapper around the Silero VAD model."""

    def __init__(self, threshold: float = 0.5, sample_rate: int = 16000):
        self.threshold = threshold
        self.sample_rate = sample_rate
        self._model = None
        self._get_ts = None

    def _ensure_model(self):
        if self._model is not None:
            return
        try:
            import torch  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("torch is required for Silero VAD") from exc
        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad", model="silero_vad", trust_repo=True
        )
        self._model = model
        self._get_ts = utils[0]  # get_speech_timestamps

    def speech_segments(self, signal) -> List[Tuple[float, float]]:
        """Return ``(start_s, end_s)`` speech regions in ``signal``."""

        import torch  # type: ignore

        self._ensure_model()
        tensor = torch.as_tensor(signal, dtype=torch.float32)
        stamps = self._get_ts(
            tensor,
            self._model,
            threshold=self.threshold,
            sampling_rate=self.sample_rate,
        )
        return [(s["start"] / self.sample_rate, s["end"] / self.sample_rate) for s in stamps]
