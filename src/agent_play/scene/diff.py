"""Pure diff between two snapshots. The evidence base for verification and waits.

Modeled on agent-desktop's `diff_signals`: no perceiver involved, every path testable with fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_play.scene.node import SceneNode
from agent_play.scene.snapshot import Snapshot

MOVE_TOLERANCE_PX = 2.0


@dataclass
class SceneEvent:
    kind: str
    role: str | None = None
    name: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind}
        if self.role:
            data["role"] = self.role
        if self.name:
            data["name"] = self.name
        if self.details:
            data.update(self.details)
        return data

    def __str__(self) -> str:
        label = f"{self.kind} {self.role or ''}".strip()
        if self.name:
            label += f' "{self.name}"'
        if "from" in self.details and "to" in self.details:
            label += f" {self.details['from']} -> {self.details['to']}"
        return label


def diff_snapshots(before: Snapshot, after: Snapshot) -> list[SceneEvent]:
    events: list[SceneEvent] = []
    before_nodes = [node for node in before.nodes() if node.bounds is not None]
    after_nodes = [node for node in after.nodes() if node.bounds is not None]
    unmatched_after = list(after_nodes)

    for old in before_nodes:
        match = _closest_same_identity(old, unmatched_after)
        if match is None:
            events.append(SceneEvent("node_disappeared", old.role, old.name, {"ref_id": old.ref_id}))
            continue
        unmatched_after.remove(match)
        assert old.bounds is not None and match.bounds is not None
        if old.bounds.moved_by(match.bounds) > MOVE_TOLERANCE_PX:
            events.append(
                SceneEvent(
                    "node_moved",
                    old.role,
                    old.name,
                    {"from": _center(old), "to": _center(match), "ref_id": match.ref_id},
                )
            )
        if (old.value or "") != (match.value or ""):
            events.append(SceneEvent("value_changed", old.role, old.name, {"from": old.value, "to": match.value}))
        if set(old.states) != set(match.states):
            events.append(SceneEvent("state_changed", old.role, old.name, {"from": old.states, "to": match.states}))

    for new in unmatched_after:
        events.append(SceneEvent("node_appeared", new.role, new.name, {"ref_id": new.ref_id, "text": new.value}))

    for surface in after.surfaces:
        if surface not in before.surfaces:
            events.append(SceneEvent("surface_appeared", details={"surface": surface}))
    for surface in before.surfaces:
        if surface not in after.surfaces:
            events.append(SceneEvent("surface_dismissed", details={"surface": surface}))

    if not events and before.frame_hash and after.frame_hash and before.frame_hash != after.frame_hash:
        events.append(SceneEvent("frame_changed"))

    events.sort(key=lambda event: _RANK.get(event.kind, 99))
    return events


_RANK = {
    "surface_dismissed": 0,
    "node_disappeared": 1,
    "surface_appeared": 2,
    "node_appeared": 3,
    "node_moved": 4,
    "value_changed": 5,
    "state_changed": 6,
    "frame_changed": 7,
}


def _center(node: SceneNode) -> tuple[int, int]:
    assert node.bounds is not None
    cx, cy = node.bounds.center
    return (int(round(cx)), int(round(cy)))


def _closest_same_identity(old: SceneNode, pool: list[SceneNode]) -> SceneNode | None:
    key = old.identity_key()
    same = [node for node in pool if node.identity_key() == key]
    if not same:
        return None
    assert old.bounds is not None
    return min(same, key=lambda node: old.bounds.moved_by(node.bounds))  # type: ignore[arg-type]
