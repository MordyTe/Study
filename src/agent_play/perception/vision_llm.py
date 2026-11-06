"""Vision perception through Claude: the frame becomes a strict `report_scene` tool call.

Boxes come back in the pixel space of the image that was sent (downscaled when large) and are mapped
back to screen pixels. Every node is tagged `source="vision"` with the model's confidence: it is a
hypothesis the executor re-checks before acting.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any, Protocol

from agent_play.envelope import AgentPlayError, ErrorCode
from agent_play.perception.base import Perception
from agent_play.perception.capture import Frame
from agent_play.scene.node import ROLES, Rect, SceneNode

DEFAULT_VISION_MODEL = "claude-opus-5-5"
MAX_IMAGE_SIDE = 1568

SURFACE_KINDS = ["dialog", "menu", "alert", "inventory", "map", "loading", "cutscene", "pause", "shop"]
STATE_KINDS = ["disabled", "selected", "checked", "focused", "hidden", "hostile", "friendly", "highlighted"]

REPORT_SCENE_TOOL: dict[str, Any] = {
    "name": "report_scene",
    "description": (
        "Report every element visible in the screenshot that an agent could act on or needs to read: "
        "buttons, menu items, text fields, dialogs, quest or objective text, HUD values, the player, "
        "enemies, NPCs, items, doors. Give tight pixel boxes [x0, y0, x1, y1] in the image you were shown. "
        "Set text to the exact visible text or an empty string. Confidence is your own estimate in [0, 1]."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "One or two sentences: what screen this is and what is happening."},
            "surfaces": {"type": "array", "items": {"type": "string", "enum": SURFACE_KINDS}},
            "elements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string", "enum": sorted(ROLES)},
                        "name": {"type": "string"},
                        "text": {"type": "string"},
                        "box": {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4},
                        "interactive": {"type": "boolean"},
                        "states": {"type": "array", "items": {"type": "string", "enum": STATE_KINDS}},
                        "confidence": {"type": "number"},
                    },
                    "required": ["role", "name", "text", "box", "interactive", "states", "confidence"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["summary", "surfaces", "elements"],
        "additionalProperties": False,
    },
}

VISION_SYSTEM_PROMPT = (
    "You are the perception module of a computer-use agent that plays games and operates desktop apps. "
    "You receive one screenshot and must call the report_scene tool exactly once with everything an agent "
    "could act on or must read. Be literal: report what is on screen, not what you infer should be there. "
    "Boxes are in the pixel coordinates of the image you see, x to the right and y downward, and must "
    "fit tightly around the element. Prefer fewer, correct elements over many guesses; use confidence "
    "to express doubt. Never report an element you cannot see."
)


@dataclass
class SceneReport:
    summary: str
    surfaces: list[str]
    elements: list[dict[str, Any]]
    usage: dict[str, int] = field(default_factory=dict)


class VisionModel(Protocol):
    def describe(self, png: bytes, width: int, height: int, hints: str) -> SceneReport: ...


class AnthropicVisionModel:
    def __init__(self, model: str = DEFAULT_VISION_MODEL, effort: str = "low", client: Any | None = None, max_tokens: int = 8000) -> None:
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def describe(self, png: bytes, width: int, height: int, hints: str) -> SceneReport:
        import anthropic

        prompt = f"The image is {width}x{height} pixels. Call report_scene."
        if hints:
            prompt += "\nContext from the agent: " + hints
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=[{"type": "text", "text": VISION_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                output_config={"effort": self.effort},
                tools=[REPORT_SCENE_TOOL],
                tool_choice={"type": "auto"},
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.standard_b64encode(png).decode("ascii")}},
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            )
        except anthropic.APIStatusError as exc:
            raise AgentPlayError(ErrorCode.PERCEPTION_FAILED, f"Vision model request failed: {exc.message}", details={"status": exc.status_code}) from exc
        except anthropic.APIConnectionError as exc:
            raise AgentPlayError(ErrorCode.PERCEPTION_FAILED, "Vision model unreachable", details={"cause": str(exc)}) from exc
        if response.stop_reason == "refusal":
            category = getattr(getattr(response, "stop_details", None), "category", None)
            raise AgentPlayError(ErrorCode.MODEL_REFUSED, "The vision model declined to describe this frame", details={"category": category})
        usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
        for block in response.content:
            if block.type == "tool_use" and block.name == "report_scene":
                payload = dict(block.input)
                return SceneReport(
                    summary=str(payload.get("summary", "")),
                    surfaces=[str(s) for s in payload.get("surfaces", [])],
                    elements=list(payload.get("elements", [])),
                    usage=usage,
                )
        text = " ".join(block.text for block in response.content if block.type == "text")
        raise AgentPlayError(ErrorCode.PERCEPTION_FAILED, "The vision model answered without calling report_scene", details={"text": text[:500]})


class VisionPerceiver:
    name = "vision"
    fast = False

    def __init__(self, model: VisionModel, hints: str = "", max_side: int = MAX_IMAGE_SIDE) -> None:
        self.model = model
        self.hints = hints
        self.max_side = max_side
        self.last_report: SceneReport | None = None

    def available(self) -> bool:
        return True

    def perceive(self, frame: Frame) -> Perception:
        small, scale = frame.downscaled(self.max_side)
        report = self.model.describe(small.to_png_bytes(), small.width, small.height, self.hints)
        self.last_report = report
        nodes = [node for node in (self._to_node(element, scale, frame) for element in report.elements) if node is not None]
        return Perception(nodes=nodes, surfaces=list(report.surfaces), summary=report.summary or None)

    def _to_node(self, element: dict[str, Any], scale: float, frame: Frame) -> SceneNode | None:
        box = element.get("box") or []
        if len(box) != 4:
            return None
        x0, y0, x1, y1 = (float(v) / scale for v in box)
        rect = Rect.from_xyxy(max(0.0, x0), max(0.0, y0), min(float(frame.width), x1), min(float(frame.height), y1))
        if rect.width < 1 or rect.height < 1:
            return None
        text = (element.get("text") or "").strip() or None
        name = (element.get("name") or "").strip() or text
        return SceneNode(
            role=str(element.get("role", "unknown")),
            name=name,
            value=text,
            bounds=rect,
            source=self.name,
            confidence=float(element.get("confidence", 0.5)),
            states=[str(s) for s in element.get("states", [])],
            interactive=bool(element.get("interactive")) or None,
        )
