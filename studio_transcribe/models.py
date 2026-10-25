"""Core data structures shared across the pipeline.

Pure stdlib: no third-party imports so the whole project can be reasoned about
and tested without the heavy ASR dependencies installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import List, Optional


@dataclass
class Word:
    """A single recognised word with its time span and model probability."""

    text: str
    start: float
    end: float
    prob: Optional[float] = None


@dataclass
class Segment:
    """A contiguous recognised utterance on one speaker's timeline.

    ``speaker`` is filled in during the merge step from the channel→speaker
    map (channel == microphone == speaker, so no diarization is needed).

    The quality fields (``avg_logprob``, ``no_speech_prob``,
    ``compression_ratio``) come straight from the ASR engine and drive the
    anti-hallucination filtering and the "low-confidence only" LLM correction
    pass.
    """

    start: float
    end: float
    text: str
    words: List[Word] = field(default_factory=list)
    speaker: Optional[str] = None
    channel: Optional[int] = None
    avg_logprob: Optional[float] = None
    no_speech_prob: Optional[float] = None
    compression_ratio: Optional[float] = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def with_speaker(self, speaker: str) -> "Segment":
        return replace(self, speaker=speaker)

    def is_low_confidence(
        self,
        logprob_threshold: float = -0.7,
        compression_ratio_threshold: float = 2.4,
    ) -> bool:
        """Heuristic used to decide which segments get the LLM correction pass.

        A segment is "uncertain" if the model's average log-probability is low
        or the text is suspiciously repetitive (high compression ratio — the
        classic Whisper loop signature).
        """

        if self.avg_logprob is not None and self.avg_logprob < logprob_threshold:
            return True
        if (
            self.compression_ratio is not None
            and self.compression_ratio > compression_ratio_threshold
        ):
            return True
        return False


@dataclass
class ChannelResult:
    """All segments recognised on a single input channel (one microphone)."""

    channel: int
    segments: List[Segment] = field(default_factory=list)

    def total_speech(self) -> float:
        return sum(s.duration for s in self.segments)
