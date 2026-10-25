"""Live caption runner — orchestrates capture → gate → Soniox → captions → sinks,
and persists finalized text to the transcript store.

Operating model (per the spec): live captions run through Soniox (cloud, no
local GPU), so a broadcast never competes with OBS/vMix for the GPU; the
high-accuracy archive is produced afterwards by the local ivrit.ai pass on the
multitrack recording.

All heavy dependencies are imported lazily via the submodules.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Dict, Optional

from ..config import Config
from ..models import Segment
from .captions import CaptionComposer
from .sinks import CaptionSink, build_sink


class LiveRunner:
    def __init__(self, config: Config):
        self.config = config
        self.live = config.live
        self.speaker_map = config.speaker_map()
        self.channels = config.enabled_channels()[:4]  # up to 4 speakers
        self.composer = CaptionComposer(
            throttle_ms=self.live.throttle_ms,
            max_chars=self.live.max_chars,
            max_lines=self.live.max_lines,
        )
        self.sink: CaptionSink = build_sink(self.live)
        self._lock = threading.Lock()
        self._channels_rt: Dict[int, object] = {}
        self._api_key = os.environ.get(config.cloud.api_key_env, "")
        self._context = self._build_context()
        self._store = None
        self._session_id = None
        self._t0 = time.monotonic()

    def _build_context(self) -> Optional[str]:
        if not self.config.glossary_path:
            return None
        from ..glossary import build_initial_prompt, load_glossary

        return build_initial_prompt(load_glossary(self.config.glossary_path)) or None

    def _speaker(self, channel: int) -> str:
        return self.speaker_map.get(channel) or f"דובר {channel}"

    # --- store ---
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
        if caption is not None:
            self.sink.emit(caption)

    def _on_frame(self, channel: int, pcm_bytes: bytes) -> None:
        from .vad_gate import frame_is_active

        if not frame_is_active(pcm_bytes, self.config.sample_rate, self.live.energy_threshold):
            return
        if not self._api_key:
            return  # no cloud key -> nothing to stream
        self._ensure_channel(channel).send_audio(pcm_bytes)

    def run(self) -> None:
        from .capture_stream import MultiChannelCapture

        if self.live.engine != "soniox":
            raise NotImplementedError(
                f"live engine {self.live.engine!r} not wired yet; use 'soniox'"
            )
        if not self._api_key:
            raise RuntimeError(
                f"Soniox live needs an API key in ${self.config.cloud.api_key_env}"
            )
        self._open_store()
        capture = MultiChannelCapture(
            channels=self.channels,
            on_frame=self._on_frame,
            out_samplerate=self.config.sample_rate,
        )
        capture.start()
        try:
            while True:
                time.sleep(0.2)
        except KeyboardInterrupt:
            pass
        finally:
            capture.stop()
            for rt in self._channels_rt.values():
                rt.stop()
            if self._store is not None:
                self._store.close()
            self.sink.close()
