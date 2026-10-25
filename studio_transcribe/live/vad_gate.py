"""Per-channel activity gate for the live layer.

Converts a PCM int16 frame back to float and asks the energy gate whether the
channel is active, so silent microphones are not streamed to the cloud (saves
connections and cost). Thin wrapper over
:func:`studio_transcribe.vad.energy_gate`.
"""

from __future__ import annotations

from ..vad import energy_gate


def frame_is_active(pcm_bytes: bytes, sample_rate: int = 16000, threshold: float = 1e-4) -> bool:
    import numpy as np  # type: ignore

    if not pcm_bytes:
        return False
    signal = np.frombuffer(pcm_bytes, dtype="<i2").astype("float32") / 32767.0
    return energy_gate(signal, sample_rate=sample_rate, threshold=threshold)
