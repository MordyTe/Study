"""Caption sinks — where a composed caption string is sent.

* ``StdoutSink`` / ``FileSink`` — pure stdlib, unit-tested. FileSink also feeds
  an OBS "text from file" source or a vMix Data Source.
* ``ObsTextSink`` — pushes to an OBS Text (GDI+) source over obs-websocket v5
  (``obsws-python``), lazily imported.
* ``VmixSink`` — pushes to a vMix Title field via the vMix Web API
  (``requests``), lazily imported.
"""

from __future__ import annotations

import sys
from typing import Callable, List, Optional

from ..config import LiveConfig


class CaptionSink:
    def emit(self, text: str) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class CallbackSink(CaptionSink):
    """Call an arbitrary function with each caption (e.g. push to the web UI)."""

    def __init__(self, callback: Callable[[str], None]):
        self._callback = callback

    def emit(self, text: str) -> None:
        self._callback(text)


class MultiSink(CaptionSink):
    """Fan a caption out to several sinks; one failing sink never blocks the rest."""

    def __init__(self, sinks: List[CaptionSink]):
        self._sinks = sinks

    def emit(self, text: str) -> None:
        for sink in self._sinks:
            try:
                sink.emit(text)
            except Exception:
                pass

    def close(self) -> None:
        for sink in self._sinks:
            try:
                sink.close()
            except Exception:
                pass


class StdoutSink(CaptionSink):
    def __init__(self, stream=None):
        self._stream = stream or sys.stdout

    def emit(self, text: str) -> None:
        self._stream.write(text.replace("\n", " | ") + "\n")
        self._stream.flush()


class FileSink(CaptionSink):
    """Overwrite a file with the current caption (OBS text-from-file / vMix data)."""

    def __init__(self, path: str):
        self.path = path

    def emit(self, text: str) -> None:
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(text)
        import os

        os.replace(tmp, self.path)  # atomic swap so readers never see a partial write


class ObsTextSink(CaptionSink):
    def __init__(self, host: str = "localhost", port: int = 4455, password: str = "", source: str = "captions"):
        try:
            import obsws_python as obs  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("obsws-python is required for OBS captions") from exc
        self.source = source
        self._client = obs.ReqClient(host=host, port=port, password=password)

    def emit(self, text: str) -> None:
        self._client.set_input_settings(self.source, {"text": text}, True)


class VmixSink(CaptionSink):
    def __init__(self, url: str = "http://127.0.0.1:8088/api/", input: str = "", field: str = "Headline.Text"):
        try:
            import requests  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("requests is required for vMix captions") from exc
        self._requests = requests
        self.url = url
        self.input = input
        self.field = field

    def emit(self, text: str) -> None:
        self._requests.get(
            self.url,
            params={
                "Function": "SetText",
                "Input": self.input,
                "SelectedName": self.field,
                "Value": text,
            },
            timeout=2,
        )


def build_sink(live: LiveConfig) -> CaptionSink:
    kind = (live.sink or "stdout").lower()
    if kind == "stdout":
        return StdoutSink()
    if kind == "file":
        return FileSink(live.file.get("path", "captions.txt"))
    if kind == "obs":
        return ObsTextSink(
            host=live.obs.get("host", "localhost"),
            port=int(live.obs.get("port", 4455)),
            password=live.obs.get("password", ""),
            source=live.obs.get("source", "captions"),
        )
    if kind == "vmix":
        return VmixSink(
            url=live.vmix.get("url", "http://127.0.0.1:8088/api/"),
            input=str(live.vmix.get("input", "")),
            field=live.vmix.get("field", "Headline.Text"),
        )
    raise ValueError(f"unknown caption sink: {live.sink!r}")
