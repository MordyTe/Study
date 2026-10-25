"""Live caption runner — orchestrates capture → gate → Soniox → captions → sinks,
and persists finalized text to the transcript store.

Operating model (per the spec): live captions run through Soniox (cloud, no
local GPU), so a broadcast never competes with OBS/vMix for the GPU; the
high-accuracy archive is produced afterwards by the local ivrit.ai pass on the
multitrack recording.

``start()`` / ``stop()`` are non-blocking (used by the web app); ``run()`` is a
blocking convenience for the CLI. All heavy dependencies are imported lazily.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Dict, List, Optional

from ..config import Config
from ..models import Segment
from .captions import CaptionComposer
from .sinks import CaptionSink, MultiSink, build_sink

ACTIVE_WINDOW_S = 2.0


class LiveRunner:
    def __init__(self, config: Config, extra_sinks: Optional[List[CaptionSink]] = None):
        self.config = config
        self.live = config.live
        self.speaker_map = config.speaker_map()
        self.channels = config.enabled_channels()[:4]  # up to 4 speakers
        self.composer = CaptionComposer(
            throttle_ms=self.live.throttle_ms,
            max_chars=self.live.max_chars,
            max_lines=self.live.max_lines,
        )
        self._extra_sinks = list(extra_sinks or [])
        self.sink: Optional[CaptionSink] = None
        self.sink_error: Optional[str] = None
        self._lock = threading.Lock()
        self._channels_rt: Dict[int, object] = {}
        self._last_active: Dict[int, float] = {}
        self._api_key = os.environ.get(config.cloud.api_key_env, "")
        self._context = self._build_context()
        self._store = None
        self._session_id = None
        self._capture = None
        self._running = False
        self._t0 = time.monotonic()

    # --- public state ---
    @property
    def running(self) -> bool:
        return self._running

    def active_channels(self) -> List[int]:
        now = time.monotonic()
        return sorted(c for c, t in self._last_active.items() if now - t < ACTIVE_WINDOW_S)

    def status(self) -> Dict:
        return {
            "running": self._running,
            "engine": self.live.engine,
            "sink": self.live.sink,
            "sink_error": self.sink_error,
            "channels": self.channels,
            "active_channels": self.active_channels(),
            "has_api_key": bool(self._api_key),
        }

    # --- setup helpers ---
    def _build_context(self) -> Optional[str]:
        if not self.config.glossary_path or not os.path.exists(self.config.glossary_path):
            return None
        from ..glossary import build_initial_prompt, load_glossary

        return build_initial_prompt(load_glossary(self.config.glossary_path)) or None

    def _speaker(self, channel: int) -> str:
        return self.speaker_map.get(channel) or f"דובר {channel}"

    def _build_sink(self) -> CaptionSink:
        sinks: List[CaptionSink] = []
        try:
            sinks.append(build_sink(self.live))
        except Exception as exc:  # a missing OBS/vMix dep must not kill captions
            self.sink_error = str(exc)
        sinks.extend(self._extra_sinks)
        return MultiSink(sinks)

    def _open_store(self) -> None:
        if not self.config.db_path:
            return
        from ..store import TranscriptStore

        self._store = TranscriptStore(self.config.db_path)
        self._session_id = self._store.create_session(
            name=f"live {time.strftime('%Y-%m-%d %H:%M')}", source="live"
        )

    def _persist_final(self, channel: int, text: str) -> None:
        if self._store is None or not text.strip():
            return
        now = time.monotonic() - self._t0
        self._store.add_segments(
            self._session_id,
            [Segment(start=now, end=now, text=text, speaker=self._speaker(channel), channel=channel)],
        )

    # --- soniox ---
    def _ensure_channel(self, channel: int):
        rt = self._channels_rt.get(channel)
        if rt is not None:
            return rt
        from .soniox_client import SonioxRealtimeChannel

        def on_result(final_delta: str, partial: str, _ch=channel):
            self._on_result(_ch, final_delta, partial)

        rt = SonioxRealtimeChannel(
            api_key=self._api_key,
            on_result=on_result,
            model=self.live.model,
            sample_rate=self.config.sample_rate,
            context=self._context,
        )
        rt.start()
        self._channels_rt[channel] = rt
        return rt

    def _on_result(self, channel: int, final_delta: str, partial: str) -> None:
        speaker = self._speaker(channel)
        caption = None
        with self._lock:
            if final_delta:
                caption = self.composer.update(channel, speaker, final_delta, True)
                self._persist_final(channel, final_delta)
            if partial:
                caption = self.composer.update(channel, speaker, partial, False)
        if caption is not None and self.sink is not None:
            self.sink.emit(caption)

    def _on_frame(self, channel: int, pcm_bytes: bytes) -> None:
        from .vad_gate import frame_is_active

        if not frame_is_active(pcm_bytes, self.config.sample_rate, self.live.energy_threshold):
            return
        self._last_active[channel] = time.monotonic()
        self._ensure_channel(channel).send_audio(pcm_bytes)

    # --- lifecycle ---
    def start(self) -> None:
        from .capture_stream import MultiChannelCapture

        if self._running:
            return
        if self.live.engine != "soniox":
            raise NotImplementedError(
                f"live engine {self.live.engine!r} not wired yet; use 'soniox'"
            )
        if not self._api_key:
            raise RuntimeError(
                f"Soniox live needs an API key in ${self.config.cloud.api_key_env}"
            )
        if not self.channels:
            raise ValueError("no enabled channels configured")

        self.sink = self._build_sink()
        self._open_store()
        self._t0 = time.monotonic()
        self._capture = MultiChannelCapture(
            channels=self.channels,
            on_frame=self._on_frame,
            out_samplerate=self.config.sample_rate,
        )
        self._capture.start()
        self._running = True

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._capture is not None:
            try:
                self._capture.stop()
            except Exception:
                pass
            self._capture = None
        for rt in self._channels_rt.values():
            try:
                rt.stop()
            except Exception:
                pass
        self._channels_rt.clear()
        self._last_active.clear()
        if self._store is not None:
            self._store.close()
            self._store = None
        if self.sink is not None:
            self.sink.close()

    def run(self) -> None:
        """Blocking run for the CLI (Ctrl-C to stop)."""

        self.start()
        try:
            while True:
                time.sleep(0.2)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
