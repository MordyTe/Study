"""Frames and frame sources. Screen capture is optional (mss); tests use static or callable sources."""

from __future__ import annotations

import hashlib
import io
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

import numpy as np
from PIL import Image

from agent_play.envelope import AgentPlayError, ErrorCode
from agent_play.scene.node import Rect

FINGERPRINT_SIZE = (16, 16)


@dataclass
class Frame:
    image: Image.Image
    captured_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    scale_factor: float = 1.0
    origin: tuple[int, int] = (0, 0)

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height

    @property
    def size(self) -> tuple[int, int]:
        return (self.image.width, self.image.height)

    def to_png_bytes(self) -> bytes:
        buffer = io.BytesIO()
        self.image.convert("RGB").save(buffer, format="PNG", optimize=False)
        return buffer.getvalue()

    def gray(self) -> np.ndarray:
        return np.asarray(self.image.convert("L"), dtype=np.float32)

    def hash(self) -> str:
        """A coarse content hash: equal for identical frames, stable against single-pixel noise."""
        small = self.image.convert("L").resize((32, 18), Image.Resampling.BILINEAR)
        quantized = (np.asarray(small, dtype=np.uint8) // 16).tobytes()
        return hashlib.sha1(quantized).hexdigest()[:16]

    def crop(self, rect: Rect) -> Image.Image:
        x0 = int(max(0, round(rect.x)))
        y0 = int(max(0, round(rect.y)))
        x1 = int(min(self.width, round(rect.right)))
        y1 = int(min(self.height, round(rect.bottom)))
        if x1 <= x0 or y1 <= y0:
            return Image.new("L", (1, 1))
        return self.image.crop((x0, y0, x1, y1))

    def fingerprint(self, rect: Rect) -> list[int]:
        """A 16x16 grayscale thumbnail of the element, stored with its ref for later re-identification."""
        thumb = self.crop(rect).convert("L").resize(FINGERPRINT_SIZE, Image.Resampling.BILINEAR)
        return [int(v) for v in np.asarray(thumb, dtype=np.uint8).flatten()]

    def downscaled(self, max_side: int) -> tuple["Frame", float]:
        longest = max(self.width, self.height)
        if longest <= max_side:
            return self, 1.0
        scale = max_side / float(longest)
        resized = self.image.resize((max(1, int(self.width * scale)), max(1, int(self.height * scale))), Image.Resampling.LANCZOS)
        return Frame(resized, self.captured_at_ms, self.scale_factor, self.origin), scale


def fingerprint_similarity(stored: list[int], fresh: list[int]) -> float:
    """Normalized cross-correlation of two fingerprints in [-1, 1]; 1 means the same picture."""
    a = np.asarray(stored, dtype=np.float64)
    b = np.asarray(fresh, dtype=np.float64)
    if a.size != b.size or a.size == 0:
        return 0.0
    a = a - a.mean()
    b = b - b.mean()
    denom = np.sqrt((a * a).sum() * (b * b).sum())
    if denom < 1e-9:
        return 1.0 if np.allclose(a, b) else 0.0
    return float((a * b).sum() / denom)


class FrameSource(Protocol):
    def capture(self) -> Frame: ...


class StaticFrameSource:
    def __init__(self, image: Image.Image) -> None:
        self.image = image

    def capture(self) -> Frame:
        return Frame(self.image.copy())


class CallableFrameSource:
    def __init__(self, render: Callable[[], Image.Image]) -> None:
        self.render = render

    def capture(self) -> Frame:
        return Frame(self.render())


class ScreenCapture:
    """Captures a monitor or a region with mss. Imported lazily so the package works without a display."""

    def __init__(self, monitor: int = 1, region: Rect | None = None) -> None:
        self.monitor = monitor
        self.region = region
        self._sct = None

    def available(self) -> bool:
        try:
            import mss  # noqa: F401
        except Exception:
            return False
        return True

    def capture(self) -> Frame:
        try:
            import mss
        except Exception as exc:
            raise AgentPlayError(
                ErrorCode.PLATFORM_NOT_SUPPORTED,
                "Screen capture needs the optional dependency mss",
                "pip install 'agent-play[capture]'",
                {"cause": str(exc)},
            ) from exc
        if self._sct is None:
            self._sct = mss.mss()
        monitors = self._sct.monitors
        if self.monitor >= len(monitors):
            raise AgentPlayError(
                ErrorCode.INVALID_ARGS,
                f"Monitor {self.monitor} out of range; {len(monitors) - 1} monitor(s) available",
                "Run 'agent-play status' to see the monitors",
            )
        box = monitors[self.monitor]
        if self.region is not None:
            box = {
                "left": int(box["left"] + self.region.x),
                "top": int(box["top"] + self.region.y),
                "width": int(self.region.width),
                "height": int(self.region.height),
            }
        shot = self._sct.grab(box)
        image = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        return Frame(image, origin=(int(box["left"]), int(box["top"])))
