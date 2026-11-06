"""Template matching: deterministic, millisecond perception for known sprites and widgets.

Normalized cross-correlation (zero-mean) computed with FFT in numpy, so the core has no OpenCV
dependency. OpenCV's `matchTemplate` is used when it is installed because it is faster on large frames.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from agent_play.perception.base import Perception
from agent_play.perception.capture import Frame
from agent_play.scene.node import Rect, SceneNode


@dataclass
class Template:
    name: str
    role: str
    image: np.ndarray
    threshold: float = 0.90
    interactive: bool | None = None
    max_matches: int = 8
    description: str | None = None

    @property
    def height(self) -> int:
        return int(self.image.shape[0])

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @staticmethod
    def from_image(image: Image.Image, name: str, role: str, **kwargs) -> "Template":
        gray = np.asarray(image.convert("L"), dtype=np.float32)
        return Template(name=name, role=role, image=gray, **kwargs)

    @staticmethod
    def from_file(path: Path, name: str | None = None, role: str | None = None, **kwargs) -> "Template":
        stem = path.stem
        if role is None or name is None:
            parsed_role, parsed_name = _parse_stem(stem)
            role = role or parsed_role
            name = name or parsed_name
        with Image.open(path) as image:
            return Template.from_image(image, name=name, role=role, **kwargs)


def _parse_stem(stem: str) -> tuple[str, str]:
    """`button__start` -> ("button", "start"); a stem without `__` is an item named after the file."""
    if "__" in stem:
        role, name = stem.split("__", 1)
        return role, name.replace("_", " ")
    return "item", stem.replace("_", " ")


class TemplateLibrary:
    """A directory of PNG templates named `<role>__<name>.png`, with optional `templates.json` overrides."""

    @staticmethod
    def load_dir(directory: Path) -> list[Template]:
        overrides: dict[str, dict] = {}
        manifest = directory / "templates.json"
        if manifest.exists():
            overrides = json.loads(manifest.read_text(encoding="utf-8"))
        templates = []
        for path in sorted(directory.glob("*.png")):
            extra = overrides.get(path.stem, {})
            templates.append(
                Template.from_file(
                    path,
                    name=extra.get("name"),
                    role=extra.get("role"),
                    threshold=float(extra.get("threshold", 0.90)),
                    interactive=extra.get("interactive"),
                    max_matches=int(extra.get("max_matches", 8)),
                    description=extra.get("description"),
                )
            )
        return templates


def _window_sums(values: np.ndarray, h: int, w: int) -> np.ndarray:
    H, W = values.shape
    integral = np.zeros((H + 1, W + 1), dtype=np.float64)
    integral[1:, 1:] = values.cumsum(axis=0).cumsum(axis=1)
    return integral[h:, w:] - integral[:-h, w:] - integral[h:, :-w] + integral[:-h, :-w]


def match_template(image: np.ndarray, template: np.ndarray) -> np.ndarray:
    """Zero-mean normalized cross-correlation map with shape (H-h+1, W-w+1), values in [-1, 1]."""
    img = np.asarray(image, dtype=np.float64)
    tpl = np.asarray(template, dtype=np.float64)
    H, W = img.shape
    h, w = tpl.shape
    if h > H or w > W or h == 0 or w == 0:
        return np.zeros((0, 0), dtype=np.float64)
    try:
        import cv2  # type: ignore

        result = cv2.matchTemplate(img.astype(np.float32), tpl.astype(np.float32), cv2.TM_CCOEFF_NORMED)
        return np.asarray(result, dtype=np.float64)
    except Exception:
        pass
    centered = tpl - tpl.mean()
    tpl_norm = float(np.sqrt((centered * centered).sum()))
    out_shape = (H - h + 1, W - w + 1)
    if tpl_norm < 1e-9:
        return np.zeros(out_shape, dtype=np.float64)
    fft_shape = (H + h - 1, W + w - 1)
    spectrum = np.fft.rfft2(img, fft_shape) * np.fft.rfft2(centered[::-1, ::-1], fft_shape)
    full = np.fft.irfft2(spectrum, fft_shape)
    cross = full[h - 1 : H, w - 1 : W]
    s1 = _window_sums(img, h, w)
    s2 = _window_sums(img * img, h, w)
    n = float(h * w)
    variance = np.clip(s2 - (s1 * s1) / n, 0.0, None)
    denom = np.sqrt(variance) * tpl_norm
    with np.errstate(divide="ignore", invalid="ignore"):
        ncc = np.where(denom > 1e-6, cross / denom, 0.0)
    return np.clip(ncc, -1.0, 1.0)


def _peaks(scores: np.ndarray, threshold: float, w: int, h: int, max_matches: int, nms_iou: float) -> list[tuple[Rect, float]]:
    if scores.size == 0:
        return []
    ys, xs = np.nonzero(scores >= threshold)
    if ys.size == 0:
        return []
    order = np.argsort(-scores[ys, xs])
    accepted: list[tuple[Rect, float]] = []
    for index in order:
        rect = Rect(float(xs[index]), float(ys[index]), float(w), float(h))
        if any(rect.iou(other) > nms_iou for other, _ in accepted):
            continue
        accepted.append((rect, float(scores[ys[index], xs[index]])))
        if len(accepted) >= max_matches:
            break
    return accepted


class TemplatePerceiver:
    name = "template"
    fast = True

    def __init__(self, templates: list[Template], nms_iou: float = 0.3) -> None:
        self.templates = list(templates)
        self.nms_iou = nms_iou

    def available(self) -> bool:
        return bool(self.templates)

    def perceive(self, frame: Frame) -> Perception:
        gray = frame.gray()
        nodes: list[SceneNode] = []
        for template in self.templates:
            scores = match_template(gray, template.image)
            for rect, score in _peaks(scores, template.threshold, template.width, template.height, template.max_matches, self.nms_iou):
                nodes.append(
                    SceneNode(
                        role=template.role,
                        name=template.name,
                        bounds=rect,
                        source=self.name,
                        confidence=score,
                        native_id=f"template:{template.role}:{template.name}",
                        interactive=template.interactive,
                        description=template.description,
                    )
                )
        return Perception(nodes=nodes)
