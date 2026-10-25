"""Soniox real-time WebSocket client — one connection per active channel.

Endpoint and protocol per Soniox docs (verify field names against the current
docs before production): connect to ``wss://stt-rt.soniox.com/transcribe-websocket``,
send a JSON config first, then stream raw PCM (s16le) frames as binary
messages. The server streams back token objects, each marked ``is_final``;
non-final tokens are the tentative tail and may change. Send ``{"type":
"finalize"}`` to force finalization, and an empty message to end the stream.

``websocket-client`` is imported lazily.
"""

from __future__ import annotations

import json
import threading
from typing import Callable, List, Optional

ENDPOINT = "wss://stt-rt.soniox.com/transcribe-websocket"

# on_result(final_delta, partial): final_delta is newly-finalized text (append),
# partial is the current tentative tail (replaces the previous partial).
OnResult = Callable[[str, str], None]


class SonioxRealtimeChannel:
    def __init__(
        self,
        api_key: str,
        on_result: OnResult,
        model: str = "stt-rt-v4",
        sample_rate: int = 16000,
        language_hints: Optional[List[str]] = None,
        context: Optional[str] = None,
        endpoint: str = ENDPOINT,
    ):
        self.api_key = api_key
        self.on_result = on_result
        self.model = model
        self.sample_rate = sample_rate
        self.language_hints = language_hints or ["he", "en"]
        self.context = context
        self.endpoint = endpoint
        self._ws = None
        self._thread: Optional[threading.Thread] = None
        self._closed = False

    def start(self) -> None:
        import websocket  # type: ignore  # websocket-client

        self._ws = websocket.create_connection(self.endpoint, enable_multithread=True)
        config = {
            "api_key": self.api_key,
            "model": self.model,
            "audio_format": "pcm_s16le",
            "sample_rate": self.sample_rate,
            "num_channels": 1,
            "language_hints": self.language_hints,
        }
        if self.context:
            # Glossary/context biasing for names and English terms.
            config["context"] = self.context
        self._ws.send(json.dumps(config))
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()

    def _recv_loop(self) -> None:
        import websocket  # type: ignore

        while not self._closed:
            try:
                raw = self._ws.recv()
            except Exception:
                break
            if raw is None or raw == "":
                continue
            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                continue
            tokens = msg.get("tokens") or []
            final_delta = "".join(t.get("text", "") for t in tokens if t.get("is_final"))
            partial = "".join(t.get("text", "") for t in tokens if not t.get("is_final"))
            if final_delta or partial:
                self.on_result(final_delta, partial)

    def send_audio(self, pcm_bytes: bytes) -> None:
        if self._ws is not None and not self._closed:
            self._ws.send_binary(pcm_bytes)

    def finalize(self) -> None:
        if self._ws is not None and not self._closed:
            self._ws.send(json.dumps({"type": "finalize"}))

    def stop(self) -> None:
        self._closed = True
        if self._ws is not None:
            try:
                self._ws.send("")  # empty message signals end-of-stream
            except Exception:
                pass
            try:
                self._ws.close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)
