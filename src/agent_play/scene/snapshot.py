"""Snapshot: one observation of the screen, with the refs allocated from it.

`compact_text()` is what the model reads. It follows agent-browser's one-line-per-node format because a
model acts more reliably on `@ref [role] "name"` lines than on nested JSON.
"""

from __future__ import annotations

import copy
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

from agent_play.scene.node import SceneNode

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


def new_snapshot_id() -> str:
    return "s" + "".join(secrets.choice(_ALPHABET) for _ in range(8))


@dataclass
class Snapshot:
    snapshot_id: str = field(default_factory=new_snapshot_id)
    roots: list[SceneNode] = field(default_factory=list)
    captured_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    screen: tuple[int, int] = (0, 0)
    frame_hash: str | None = None
    surfaces: list[str] = field(default_factory=list)
    complete: bool = True
    sources: list[str] = field(default_factory=list)
    summary: str | None = None

    def walk(self) -> Iterator[tuple[SceneNode, int]]:
        for root in self.roots:
            yield from root.walk()

    def nodes(self) -> list[SceneNode]:
        return [node for node, _ in self.walk()]

    def interactive(self) -> list[SceneNode]:
        return [node for node in self.nodes() if node.interactive]

    def by_ref(self, ref_id: str) -> SceneNode | None:
        for node in self.nodes():
            if node.ref_id == ref_id:
                return node
        return None

    def find(self, role: str | None = None, name: str | None = None, exact: bool = False) -> list[SceneNode]:
        wanted = (name or "").strip().lower()
        matches = []
        for node in self.nodes():
            if role and node.role != role:
                continue
            if wanted:
                haystack = ((node.name or "") + " " + (node.value or "")).lower()
                if exact and (node.name or "").strip().lower() != wanted:
                    continue
                if not exact and wanted not in haystack:
                    continue
            matches.append(node)
        return matches

    def ref_count(self) -> int:
        return sum(1 for node in self.nodes() if node.ref_id)

    def skeleton(self, depth: int = 2) -> "Snapshot":
        """A shallow copy of the tree, as agent-desktop's `--skeleton`: cut branches carry children_count."""

        def cut(node: SceneNode, level: int) -> SceneNode:
            clone = copy.copy(node)
            if level >= depth and node.children:
                clone.children = []
                clone.children_count = len(node.children)
            else:
                clone.children = [cut(child, level + 1) for child in node.children]
            return clone

        clone = copy.copy(self)
        clone.roots = [cut(root, 0) for root in self.roots]
        return clone

    def compact_text(self, interactive_only: bool = False, with_bounds: bool = True) -> str:
        lines = [f"Snapshot {self.snapshot_id} screen={self.screen[0]}x{self.screen[1]} refs={self.ref_count()}"]
        if self.surfaces:
            lines.append("Surfaces open: " + ", ".join(self.surfaces))
        if self.summary:
            lines.append("Summary: " + self.summary.strip())
        for node, depth in self.walk():
            if interactive_only and not node.interactive and not node.children_count:
                continue
            lines.append("  " * depth + _render_line(node, with_bounds))
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "captured_at_ms": self.captured_at_ms,
            "screen": {"width": self.screen[0], "height": self.screen[1]},
            "frame_hash": self.frame_hash,
            "surfaces": list(self.surfaces),
            "complete": self.complete,
            "sources": list(self.sources),
            "summary": self.summary,
            "ref_count": self.ref_count(),
            "tree": [root.to_dict() for root in self.roots],
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Snapshot":
        screen = data.get("screen", {})
        return Snapshot(
            snapshot_id=data["snapshot_id"],
            roots=[SceneNode.from_dict(node) for node in data.get("tree", [])],
            captured_at_ms=data.get("captured_at_ms", 0),
            screen=(int(screen.get("width", 0)), int(screen.get("height", 0))),
            frame_hash=data.get("frame_hash"),
            surfaces=list(data.get("surfaces", [])),
            complete=data.get("complete", True),
            sources=list(data.get("sources", [])),
            summary=data.get("summary"),
        )


def _render_line(node: SceneNode, with_bounds: bool) -> str:
    parts = [node.ref_id or "-", f"[{node.role}]"]
    if node.name:
        parts.append(f'"{node.name}"')
    if node.value and node.value != node.name:
        parts.append(f"value={node.value!r}")
    if node.description and node.description != node.name:
        parts.append(f"desc={node.description!r}")
    if with_bounds and node.bounds:
        b = node.bounds
        parts.append(f"@({int(b.x)},{int(b.y)} {int(b.width)}x{int(b.height)})")
    if node.states:
        parts.append("states=" + ",".join(node.states))
    if node.children_count:
        parts.append(f"children_count={node.children_count}")
    parts.append(f"src={node.source}")
    if node.confidence < 0.999:
        parts.append(f"c={node.confidence:.2f}")
    return " ".join(parts)
