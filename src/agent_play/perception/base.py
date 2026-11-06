"""The perceiver seam. A perceiver turns one frame into nodes; it knows nothing about refs or actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from agent_play.perception.capture import Frame
from agent_play.scene.node import SceneNode


@dataclass
class Perception:
    nodes: list[SceneNode] = field(default_factory=list)
    surfaces: list[str] = field(default_factory=list)
    summary: str | None = None
    complete: bool = True


@runtime_checkable
class Perceiver(Protocol):
    name: str
    fast: bool

    def available(self) -> bool: ...

    def perceive(self, frame: Frame) -> Perception: ...
