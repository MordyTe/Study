"""Quick microphone test — transcribe the computer's default mic, zero setup.

The simplest possible way to confirm transcription works before wiring up the
X32 / Dante / Soniox. One button in the UI starts it: it opens the default
system microphone (no device picking, no channel mapping), buffers the audio,
and every few seconds transcribes the buffered speech with the local ivrit.ai
engine and streams the text to the UI.

Design split (so it is testable without audio hardware or the ASR deps):

* ``feed(signal)`` appends 16 kHz mono float audio to the buffer.
* ``flush_once()`` transcribes the buffered speech (if any) and emits an event.
* ``start()``/``stop()`` wire the default-mic capture and a periodic worker;
  the engine and ``sounddevice`` are imported/built lazily in a background
  thread so the API call returns instantly and the UI can show "loading…".
"""

from __future__ import annotations

import copy
import threading
import time
from typing import Callable, List, Optional

from ..config import Config
from ..normalize_he import normalize_display
from ..vad import energy_gate

# Event kinds sent to on_event: {"kind": "status"|"text"|"error", "text": ...}
OnEvent = Callable[[dict], None]


class MicTestRunner:
    def __init__(
        self,
        config: Config,
        on_event: OnEvent,
        engine=None,
    ):
        self.config = config
        self.on_event = on_event
        self.sample_rate = config.sample_rate
        self.interval = max(1.0, config.mic_test.interval_s)
        self._engine = engine  # injectable for tests; else built on start()
        self._buf: List = []
        self._lock = threading.Lock()
        self._running = False
        self._capture = None
        self._worker: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        return self._running

    # --- core (unit-tested) ---
    def feed(self, signal) -> None:
        import numpy as np  # type: ignore

        with self._lock:
            self._buf.append(np.asarray(signal, dtype=np.float32))

    def _drain(self):
        import numpy as np  # type: ignore

        with self._lock:
            if not self._buf:
                return None
            chunk = np.concatenate(self._buf)
            self._buf = []
        return chunk

    def flush_once(self) -> None:
        chunk = self._drain()
        if chunk is None or chunk.size == 0:
            return
        if not energy_gate(chunk, sample_rate=self.sample_rate):
            return  # silence — nothing to transcribe
        if self._engine is None:
            return
        segments = self._engine.transcribe(chunk, language=self.config.language)
        text = normalize_display(" ".join(s.text for s in segments))
        if text:
            self.on_event({"kind": "text", "text": text})

    # --- lifecycle ---
    def _build_engine(self):
        from ..engines import build_engine

        cfg = copy.deepcopy(self.config)
        cfg.engine = "faster-whisper"  # mic test is always the local engine
        if self.config.mic_test.model:
            cfg.model = self.config.mic_test.model
        return build_engine(cfg)

    def _open_default_mic(self):
        import sounddevice as sd  # type: ignore

        def callback(indata, frames, time_info, status):  # pragma: no cover - audio thread
            self.feed(indata[:, 0].copy())

        try:
            stream = sd.InputStream(
                device=None,  # default system microphone
                channels=1,
                samplerate=self.sample_rate,
                dtype="float32",
                callback=callback,
            )
            stream.start()
            return stream
        except Exception:
            # Fallback: open at the device default rate and resample on the way in.
            from ..audio_io import resample_mono

            default_sr = int(sd.query_devices(None, "input")["default_samplerate"])

            def cb2(indata, frames, time_info, status):  # pragma: no cover
                self.feed(resample_mono(indata[:, 0].copy(), default_sr, self.sample_rate))

            stream = sd.InputStream(
                device=None, channels=1, samplerate=default_sr, dtype="float32", callback=cb2
            )
            stream.start()
            return stream

    def _worker_loop(self) -> None:
        while self._running:
            time.sleep(self.interval)
            try:
                self.flush_once()
            except Exception as exc:  # keep the test running; surface the error
                self.on_event({"kind": "error", "text": str(exc)})

    def _init_async(self) -> None:
        try:
            self.on_event({"kind": "status", "text": "טוען מודל…"})  # "טוען מודל…"
            if self._engine is None:
                self._engine = self._build_engine()
            self._capture = self._open_default_mic()
            self._worker = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker.start()
            self.on_event({"kind": "status", "text": "מוכן — דברו"})  # "מוכן — דברו"
        except Exception as exc:
            self._running = False
            self.on_event({"kind": "error", "text": str(exc)})

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        threading.Thread(target=self._init_async, daemon=True).start()

    def stop(self) -> None:
        self._running = False
        if self._capture is not None:
            try:
                self._capture.stop()
                self._capture.close()
            except Exception:
                pass
            self._capture = None
        with self._lock:
            self._buf = []
        self.on_event({"kind": "status", "text": "הופסק"})  # "הופסק"
