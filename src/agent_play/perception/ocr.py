"""Optional OCR perception for quest text, dialogs and HUD numbers.

Uses RapidOCR when installed, otherwise pytesseract, otherwise reports itself unavailable. Text nodes
carry the text in `value` so fusion can label a button or a dialog that another source found.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from agent_play.perception.base import Perception
from agent_play.perception.capture import Frame
from agent_play.scene.node import Rect, SceneNode


class OcrPerceiver:
    name = "ocr"
    fast = True

    def __init__(self, min_confidence: float = 0.5) -> None:
        self.min_confidence = min_confidence
        self._engine: Any | None = None
        self._kind: str | None = None

    def available(self) -> bool:
        return self._load() is not None

    def _load(self) -> Any | None:
        if self._engine is not None:
            return self._engine
        try:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore

            self._engine = RapidOCR()
            self._kind = "rapidocr"
            return self._engine
        except Exception:
            pass
        try:
            import pytesseract  # type: ignore

            pytesseract.get_tesseract_version()
            self._engine = pytesseract
            self._kind = "tesseract"
            return self._engine
        except Exception:
            return None

    def perceive(self, frame: Frame) -> Perception:
        engine = self._load()
        if engine is None:
            return Perception(nodes=[], complete=False)
        if self._kind == "rapidocr":
            return Perception(nodes=self._rapid(engine, frame))
        return Perception(nodes=self._tesseract(engine, frame))

    def _rapid(self, engine: Any, frame: Frame) -> list[SceneNode]:
        result, _ = engine(np.asarray(frame.image.convert("RGB")))
        nodes = []
        for box, text, score in result or []:
            if float(score) < self.min_confidence or not str(text).strip():
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            nodes.append(self._text_node(str(text).strip(), Rect.from_xyxy(min(xs), min(ys), max(xs), max(ys)), float(score)))
        return nodes

    def _tesseract(self, engine: Any, frame: Frame) -> list[SceneNode]:
        data = engine.image_to_data(frame.image, output_type=engine.Output.DICT)
        nodes = []
        for index, text in enumerate(data.get("text", [])):
            text = str(text).strip()
            conf = float(data["conf"][index]) / 100.0 if data["conf"][index] not in ("-1", -1) else 0.0
            if not text or conf < self.min_confidence:
                continue
            rect = Rect(float(data["left"][index]), float(data["top"][index]), float(data["width"][index]), float(data["height"][index]))
            nodes.append(self._text_node(text, rect, conf))
        return nodes

    def _text_node(self, text: str, rect: Rect, confidence: float) -> SceneNode:
        return SceneNode(role="text", name=text[:60], value=text, bounds=rect, source=self.name, confidence=confidence, interactive=False)
