"""studio_transcribe — מערכת תמלול אולפן בדיוק גבוה (עברית + אנגלית).

Studio-grade, speaker-tagged transcription for a broadcast studio that feeds
per-microphone audio off a Behringer X32 (over Dante) into a dedicated node.

The package is split into two layers:

* A **pure-stdlib core** that always imports and is fully unit-tested here:
  :mod:`studio_transcribe.models`, :mod:`studio_transcribe.normalize_he`,
  :mod:`studio_transcribe.eval_wer`, :mod:`studio_transcribe.merge`,
  :mod:`studio_transcribe.export`, :mod:`studio_transcribe.glossary`,
  :mod:`studio_transcribe.config`.

* A **heavy runtime layer** (ASR engines, VAD, audio IO, capture) that pulls in
  optional dependencies (faster-whisper, torch, soundfile, sounddevice). Those
  modules import their dependencies lazily so the core keeps working without
  them installed.
"""

from .models import Word, Segment, ChannelResult

__all__ = ["Word", "Segment", "ChannelResult"]

__version__ = "0.1.0"
