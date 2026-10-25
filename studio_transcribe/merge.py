"""Merge per-channel results into one speaker-tagged timeline.

Because every microphone is captured on its own channel off the X32, the
channel number *is* the speaker identity — this module just tags each segment
with the configured speaker name, drops them onto a single timeline sorted by
start time, and (optionally) joins adjacent segments from the same speaker that
are separated by only a short gap, so the exported transcript reads naturally.

No diarization, no third-party dependencies.
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional

from .models import ChannelResult, Segment
from .normalize_he import collapse_whitespace


def default_speaker_name(channel: int) -> str:
    return f"דובר {channel}"  # "דובר N"


def tag_speakers(
    results: List[ChannelResult],
    speaker_map: Optional[Mapping[int, str]] = None,
) -> List[Segment]:
    """Flatten channel results into one list, tagging each segment's speaker."""

    speaker_map = speaker_map or {}
    out: List[Segment] = []
    for result in results:
        speaker = speaker_map.get(result.channel) or default_speaker_name(result.channel)
        for seg in result.segments:
            seg.speaker = speaker
            seg.channel = result.channel
            out.append(seg)
    return out


def _join_two(a: Segment, b: Segment) -> Segment:
    text = collapse_whitespace(f"{a.text} {b.text}")
    return Segment(
        start=a.start,
        end=b.end,
        text=text,
        words=list(a.words) + list(b.words),
        speaker=a.speaker,
        channel=a.channel,
        # Quality fields are per-decode and not meaningful once joined.
        avg_logprob=None,
        no_speech_prob=None,
        compression_ratio=None,
    )


def merge_timeline(
    results: List[ChannelResult],
    speaker_map: Optional[Mapping[int, str]] = None,
    join_gap: float = 0.0,
) -> List[Segment]:
    """Return a single timeline of segments sorted by start time.

    If ``join_gap`` > 0, consecutive segments from the *same speaker* whose gap
    is <= ``join_gap`` seconds are merged into one segment.
    """

    segments = tag_speakers(results, speaker_map)
    segments.sort(key=lambda s: (s.start, s.channel if s.channel is not None else 0))

    if join_gap <= 0:
        return segments

    merged: List[Segment] = []
    for seg in segments:
        if (
            merged
            and merged[-1].speaker == seg.speaker
            and seg.start - merged[-1].end <= join_gap
        ):
            merged[-1] = _join_two(merged[-1], seg)
        else:
            merged.append(seg)
    return merged


def speaker_totals(segments: List[Segment]) -> Dict[str, float]:
    """Total speaking time per speaker — a quick sanity/monitoring metric."""

    totals: Dict[str, float] = {}
    for seg in segments:
        key = seg.speaker or "?"
        totals[key] = totals.get(key, 0.0) + seg.duration
    return totals
