"""ASR engine implementations and a factory that builds one from a Config."""

from __future__ import annotations

from ..config import Config
from .base import TranscriptionEngine


def build_engine(config: Config) -> TranscriptionEngine:
    """Instantiate the engine named by ``config.engine``.

    Heavy dependencies are imported inside each engine module, so importing this
    package is cheap and only the chosen engine's deps are required.
    """

    engine = config.engine.lower().replace("_", "-")
    if engine in ("faster-whisper", "ivrit", "whisper"):
        from .faster_whisper_engine import FasterWhisperEngine

        return FasterWhisperEngine(config)
    if engine in ("soniox", "elevenlabs", "azure", "cloud"):
        from .cloud import CloudEngine

        return CloudEngine(config)
    raise ValueError(f"unknown engine: {config.engine!r}")


__all__ = ["TranscriptionEngine", "build_engine"]
