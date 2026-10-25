"""Caption composition: turn a stream of per-channel partial/final tokens into
a throttled, speaker-labeled, length-bounded caption string.

Pure stdlib (``time`` only, and the clock is injectable for deterministic
tests). This is the deterministic heart of the live layer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from ..normalize_he import normalize_display


@dataclass
class _Line:
    speaker: str
    final: str = ""
    partial: str = ""
    updated: float = 0.0


def _tail(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    # Keep the tail (captions scroll); cut on a word boundary when possible.
    cut = text[-max_chars:]
    space = cut.find(" ")
    return cut[space + 1 :] if 0 <= space < len(cut) - 1 else cut


class CaptionComposer:
    """Accumulate tokens per channel and render a caption on throttle/final.

    ``update(channel, speaker, text, is_final)`` returns a caption string when
    it is time to refresh the display (throttle elapsed, or a final token), else
    ``None``. ``current()`` renders the latest state regardless of throttle.
    """

    def __init__(
        self,
        throttle_ms: int = 300,
        max_chars: int = 120,
        max_lines: int = 2,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.throttle = throttle_ms / 1000.0
        self.max_chars = max_chars
        self.max_lines = max_lines
        self._clock = clock
        self._lines: Dict[int, _Line] = {}
        self._last_emit = 0.0

    def update(
        self,
        channel: int,
        speaker: str,
        text: str,
        is_final: bool,
    ) -> Optional[str]:
        now = self._clock()
        line = self._lines.get(channel)
        if line is None:
            line = _Line(speaker=speaker)
            self._lines[channel] = line
        line.speaker = speaker
        line.updated = now

        text = text.strip()
        if is_final:
            line.final = normalize_display(f"{line.final} {text}") if line.final else text
            # Bound memory over a long show; display only ever uses the tail.
            if len(line.final) > 2 * self.max_chars:
                line.final = _tail(line.final, 2 * self.max_chars)
            line.partial = ""
        else:
            line.partial = text

        if is_final or (now - self._last_emit) >= self.throttle:
            self._last_emit = now
            return self.current()
        return None

    def current(self) -> str:
        active = sorted(self._lines.values(), key=lambda l: l.updated, reverse=True)
        rendered: List[str] = []
        for line in active[: self.max_lines]:
            body = normalize_display(f"{line.final} {line.partial}")
            body = _tail(body, self.max_chars)
            if body:
                rendered.append(f"{line.speaker}: {body}" if line.speaker else body)
        return "\n".join(rendered)

    def reset_channel(self, channel: int) -> None:
        """Clear a channel's state (e.g. after a long silence / segment end)."""

        self._lines.pop(channel, None)
