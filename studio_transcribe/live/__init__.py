"""Live-caption layer (Stage 3).

Streams the studio's per-microphone channels in real time through a streaming
ASR engine (Soniox cloud by default — best live Hebrew/English code-switching,
and zero local GPU load during a broadcast), composes rolling captions, and
pushes them to OBS / vMix while persisting finals to the transcript store.

Deterministic pieces (:mod:`~studio_transcribe.live.captions`, the file/stdout
sinks) are unit-tested. The websocket / ASIO / OBS integrations import their
dependencies lazily.
"""

from .captions import CaptionComposer

__all__ = ["CaptionComposer"]
