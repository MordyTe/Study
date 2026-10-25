"""Engine interface shared by local and cloud transcribers."""

from __future__ import annotations

from typing import List, Optional

from ..models import Segment


class TranscriptionEngine:
    """Transcribe one channel's 16 kHz mono audio into segments.

    Implementations receive a NumPy float32 array (or a file path) for a single
    channel and return :class:`~studio_transcribe.models.Segment` objects with
    quality fields populated where the backend provides them.
    """

    def transcribe(
        self,
        audio,
        language: str = "he",
        initial_prompt: Optional[str] = None,
    ) -> List[Segment]:
        raise NotImplementedError

    def close(self) -> None:  # optional cleanup hook
        pass
