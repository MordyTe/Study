"""Real-time multichannel ASIO capture for the live layer.

Opens one ASIO input stream (all requested channels come off the same
clock-locked device), and for each audio block deinterleaves the requested
channels, resamples each to 16 kHz mono, converts to little-endian int16 PCM,
and calls ``on_frame(channel, pcm_bytes)``.

``sounddevice``/``numpy`` are imported lazily.
"""

from __future__ import annotations

from typing import Callable, List, Optional

from ..audio_io import resample_mono

OnFrame = Callable[[int, bytes], None]


class MultiChannelCapture:
    def __init__(
        self,
        channels: List[int],
        on_frame: OnFrame,
        device: Optional[str] = None,
        in_samplerate: int = 48000,
        out_samplerate: int = 16000,
        blocksize: int = 4800,  # 100 ms at 48 kHz
    ):
        self.channels = channels
        self.on_frame = on_frame
        self.device = device
        self.in_samplerate = in_samplerate
        self.out_samplerate = out_samplerate
        self.blocksize = blocksize
        self._stream = None

    def _callback(self, indata, frames, time_info, status):  # pragma: no cover - audio thread
        import numpy as np  # type: ignore

        for pos, channel in enumerate(self._keep_index):
            mono = np.ascontiguousarray(indata[:, pos])
            resampled = resample_mono(mono, self.in_samplerate, self.out_samplerate)
            pcm16 = np.clip(resampled, -1.0, 1.0)
            pcm16 = (pcm16 * 32767.0).astype("<i2").tobytes()
            self.on_frame(channel, pcm16)

    def start(self) -> None:
        import sounddevice as sd  # type: ignore

        extra = None
        if self.device and "asio" in str(self.device).lower():
            extra = sd.AsioSettings(channel_selectors=[c - 1 for c in self.channels])
            in_channels = len(self.channels)
            self._keep_index = list(range(len(self.channels)))
        else:
            in_channels = max(self.channels)
            self._keep_index = [c - 1 for c in self.channels]

        self._stream = sd.InputStream(
            device=self.device,
            channels=in_channels,
            samplerate=self.in_samplerate,
            blocksize=self.blocksize,
            dtype="float32",
            callback=self._callback,
            extra_settings=extra,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
