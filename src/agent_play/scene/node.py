"""SceneNode: one element of an observed scene, from any perceiver.

The role vocabulary unites widget roles (agent-desktop's accessibility roles) with game entities, so the
agent reasons about a "Start" button and an "enemy" through the same contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

WIDGET_ROLES = {
    "button", "checkbox", "combobox", "link", "menu", "menu_item", "radio_button", "slider",
    "switch", "tab", "text_field", "list_item", "tree_item", "scroll_bar", "dialog", "window",
    "image", "text", "heading", "group", "region", "toolbar", "progress_bar", "unknown",
}
GAME_ROLES = {
    "player", "enemy", "npc", "item", "hud", "minimap", "objective", "door", "portal", "tile",
    "projectile", "obstacle", "pickup", "card", "unit", "cursor",
}
ROLES = WIDGET_ROLES | GAME_ROLES

INTERACTIVE_ROLES = {
    "button", "checkbox", "combobox", "link", "menu_item", "radio_button", "slider", "switch", "tab",
    "text_field", "list_item", "tree_item", "scroll_bar",
    "player", "enemy", "npc", "item", "door", "portal", "tile", "pickup", "card", "unit",
}

SOURCE_PRIORITY = ("a11y", "sim", "template", "ocr", "vision")


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2.0, self.y + self.height / 2.0)

    @property
    def area(self) -> float:
        return max(self.width, 0.0) * max(self.height, 0.0)

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def iou(self, other: "Rect") -> float:
        ix = max(0.0, min(self.right, other.right) - max(self.x, other.x))
        iy = max(0.0, min(self.bottom, other.bottom) - max(self.y, other.y))
        inter = ix * iy
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0

    def contains_point(self, x: float, y: float) -> bool:
        return self.x <= x <= self.right and self.y <= y <= self.bottom

    def moved_by(self, other: "Rect") -> float:
        """Distance between centers, used to notice movement of a twin-identical sprite."""
        (ax, ay), (bx, by) = self.center, other.center
        return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Rect":
        return Rect(float(data["x"]), float(data["y"]), float(data["width"]), float(data["height"]))

    @staticmethod
    def from_xyxy(x0: float, y0: float, x1: float, y1: float) -> "Rect":
        return Rect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))


@dataclass
class SceneNode:
    role: str
    name: str | None = None
    bounds: Rect | None = None
    source: str = "unknown"
    confidence: float = 1.0
    states: list[str] = field(default_factory=list)
    value: str | None = None
    description: str | None = None
    native_id: str | None = None
    interactive: bool | None = None
    children: list["SceneNode"] = field(default_factory=list)
    children_count: int | None = None
    ref_id: str | None = None
    corroborated_by: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.role = self.role.strip().lower().replace("-", "_").replace(" ", "_") or "unknown"
        if self.interactive is None:
            self.interactive = self.role in INTERACTIVE_ROLES
        self.confidence = max(0.0, min(1.0, float(self.confidence)))

    def identity_key(self) -> tuple[str, str | None, str | None, str | None]:
        """What agent-desktop uses to re-identify an element: role, native id, name, description."""
        return (self.role, self.native_id, self.name, self.description)

    def is_enabled(self) -> bool:
        return "disabled" not in self.states

    def walk(self, depth: int = 0) -> Iterator[tuple["SceneNode", int]]:
        yield self, depth
        for child in self.children:
            yield from child.walk(depth + 1)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"role": self.role, "source": self.source, "confidence": round(self.confidence, 3)}
        if self.ref_id:
            data["ref_id"] = self.ref_id
        if self.name is not None:
            data["name"] = self.name
        if self.description is not None:
            data["description"] = self.description
        if self.value is not None:
            data["value"] = self.value
        if self.native_id is not None:
            data["native_id"] = self.native_id
        if self.bounds is not None:
            data["bounds"] = self.bounds.to_dict()
        if self.states:
            data["states"] = list(self.states)
        if self.interactive:
            data["interactive"] = True
        if self.corroborated_by:
            data["corroborated_by"] = list(self.corroborated_by)
        if self.children_count is not None:
            data["children_count"] = self.children_count
        if self.children:
            data["children"] = [child.to_dict() for child in self.children]
        return data

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "SceneNode":
        return SceneNode(
            role=data.get("role", "unknown"),
            name=data.get("name"),
            bounds=Rect.from_dict(data["bounds"]) if data.get("bounds") else None,
            source=data.get("source", "unknown"),
            confidence=data.get("confidence", 1.0),
            states=list(data.get("states", [])),
            value=data.get("value"),
            description=data.get("description"),
            native_id=data.get("native_id"),
            interactive=data.get("interactive"),
            children=[SceneNode.from_dict(child) for child in data.get("children", [])],
            children_count=data.get("children_count"),
            ref_id=data.get("ref_id"),
            corroborated_by=list(data.get("corroborated_by", [])),
        )
