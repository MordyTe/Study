"""ActionExecutor: resolve, re-identify, gate, dispatch, verify.

The contract follows agent-desktop: a ref is re-identified against a fresh observation before anything
is sent; an absent target is `STALE_REF`, an ambiguous one `AMBIGUOUS_TARGET`; the result carries a
delivery disposition, and `delivered_verified` needs a fresh observation that shows a change.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from agent_play.actions.backend import BaseBackend
from agent_play.actions.keys import parse_combo
from agent_play.actions.policy import InteractionPolicy
from agent_play.envelope import AgentPlayError, Delivery, ErrorCode
from agent_play.perception.capture import Frame, fingerprint_similarity
from agent_play.scene.diff import SceneEvent, diff_snapshots
from agent_play.scene.node import SceneNode
from agent_play.scene.refs import (
    RefEntry,
    RefStore,
    choose_by_position,
    match_candidates,
)
from agent_play.scene.snapshot import Snapshot

POINTER_ACTIONS = {"click", "double_click", "right_click", "hover", "mouse_click", "drag", "scroll"}
KEY_ACTIONS = {"press", "key_down", "key_up", "hold_key", "type_text"}
MOVING_ROLES = {"player", "enemy", "npc", "projectile", "unit", "cursor"}
STABILITY_SAMPLE_MS = 40
STABILITY_TOLERANCE_PX = 3.0


@dataclass
class ActionRequest:
    action: str
    ref_id: str | None = None
    x: float | None = None
    y: float | None = None
    key: str | None = None
    text: str | None = None
    duration_ms: int | None = None
    button: str = "left"
    amount: int = 3
    direction: str = "down"
    to_ref: str | None = None
    to_x: float | None = None
    to_y: float | None = None
    expect_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in self.__dict__.items() if value is not None}


@dataclass
class ActionResult:
    action: str
    delivery: Delivery
    ref_id: str | None = None
    point: tuple[float, float] | None = None
    verification: dict[str, Any] = field(default_factory=dict)
    events: list[SceneEvent] = field(default_factory=list)
    surfaces: list[str] = field(default_factory=list)
    reidentified_by: str | None = None
    stable: bool | None = None
    duration_ms: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"action": self.action, "disposition": self.delivery.to_dict()}
        if self.ref_id:
            data["ref_id"] = self.ref_id
        if self.point:
            data["point"] = {"x": round(self.point[0], 1), "y": round(self.point[1], 1)}
        if self.reidentified_by:
            data["reidentified_by"] = self.reidentified_by
        if self.stable is not None:
            data["stable"] = self.stable
        if self.verification:
            data["verification"] = self.verification
        if self.events:
            data["events"] = [event.to_dict() for event in self.events]
        if self.surfaces:
            data["surfaces"] = list(self.surfaces)
        data["duration_ms"] = self.duration_ms
        if self.details:
            data["details"] = self.details
        return data


class ActionExecutor:
    def __init__(
        self,
        refs: RefStore,
        backend: BaseBackend,
        policy: InteractionPolicy,
        capture: Callable[[], Frame],
        observe_fast: Callable[[], Snapshot | None],
        screen: Callable[[], tuple[int, int]],
        a11y_click: Callable[[str], dict[str, Any]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.refs = refs
        self.backend = backend
        self.policy = policy
        self.capture = capture
        self.observe_fast = observe_fast
        self.screen = screen
        self.a11y_click = a11y_click
        self.sleep = sleep
        self.on_event = on_event or (lambda _name, _data: None)

    def execute(self, request: ActionRequest) -> ActionResult:
        started = time.monotonic()
        self.policy.check_action(request.action)
        if request.action not in POINTER_ACTIONS | KEY_ACTIONS:
            raise AgentPlayError(ErrorCode.INVALID_ARGS, f"Unknown action {request.action!r}")
        before = self.observe_fast()
        before_frame = self.capture() if before is None else None
        target = self._resolve_target(request, before)
        if target is not None and target.entry is not None and target.entry.source == "a11y" and self.a11y_click and request.action == "click":
            result = self._delegate_a11y(request, target)
        else:
            result = self._dispatch(request, target)
        result.duration_ms = int((time.monotonic() - started) * 1000)
        if result.delivery is Delivery.NOT_DELIVERED:
            return result
        self.sleep(self.policy.settle_ms / 1000.0)
        after = self.observe_fast()
        self._verify(request, result, before, before_frame, after)
        result.duration_ms = int((time.monotonic() - started) * 1000)
        return result

    @dataclass
    class _Target:
        point: tuple[float, float] | None
        entry: RefEntry | None
        node: SceneNode | None
        method: str | None
        stable: bool | None

    def _resolve_target(self, request: ActionRequest, before: Snapshot | None) -> "_Target | None":
        if request.action in KEY_ACTIONS:
            return None
        if request.ref_id is None:
            if request.x is None or request.y is None:
                raise AgentPlayError(ErrorCode.INVALID_ARGS, f"{request.action} needs a ref_id or x,y coordinates")
            self._require_on_screen(request.x, request.y)
            return self._Target((request.x, request.y), None, None, "coordinates", None)
        entry = self.refs.resolve(request.ref_id)
        if "disabled" in entry.states:
            raise AgentPlayError(ErrorCode.ACTION_FAILED, f"Element {request.ref_id} was disabled when captured", "Observe again; act on it once it is enabled", {"kind": "not_enabled"}, Delivery.NOT_DELIVERED)
        if not self.policy.require_reidentify:
            rect = entry.rect()
            assert rect is not None
            return self._Target(rect.center, entry, None, "skipped", None)
        if before is not None and before.sources:
            node, stable = self._reidentify_in_scene(entry, before)
            assert node.bounds is not None
            self.on_event("ref.resolve.ok", {"ref_id": entry.ref_id, "method": "scene", "stable": stable})
            return self._Target(node.bounds.center, entry, node, "scene", stable)
        point = self._reidentify_by_fingerprint(entry)
        self.on_event("ref.resolve.ok", {"ref_id": entry.ref_id, "method": "fingerprint"})
        return self._Target(point, entry, None, "fingerprint", None)

    def _reidentify_in_scene(self, entry: RefEntry, scene: Snapshot) -> tuple[SceneNode, bool | None]:
        candidates = match_candidates(entry, scene.nodes())
        if not candidates:
            self.on_event("ref.resolve.error", {"ref_id": entry.ref_id, "kind": "saved_ref_absent"})
            raise AgentPlayError(
                ErrorCode.STALE_REF,
                f"Element {entry.ref_id} ({entry.role} {entry.name!r}) is no longer on screen",
                "Take a fresh snapshot and use the new ref.",
                {"kind": "saved_ref_absent", "ref_id": entry.ref_id},
            )
        if len(candidates) == 1:
            node = candidates[0]
        else:
            chosen = choose_by_position(entry, candidates, self.policy.twin_max_distance_px)
            if chosen is None:
                self.on_event("ref.resolve.error", {"ref_id": entry.ref_id, "kind": "identity_not_unique"})
                raise AgentPlayError(
                    ErrorCode.AMBIGUOUS_TARGET,
                    f"{len(candidates)} elements match {entry.ref_id} and none is near its captured position",
                    "Snapshot again and act on the twin at the position you mean, or use mouse_click with coordinates.",
                    {"kind": "identity_not_unique", "candidate_count": len(candidates)},
                )
            node = chosen
        if node.bounds is not None and "disabled" in node.states:
            raise AgentPlayError(ErrorCode.ACTION_FAILED, f"Element {entry.ref_id} is disabled", details={"kind": "not_enabled"})
        stable: bool | None = None
        if entry.role in MOVING_ROLES:
            self.sleep(STABILITY_SAMPLE_MS / 1000.0)
            again = self.observe_fast()
            if again is not None:
                later = match_candidates(entry, again.nodes())
                if later:
                    newest = choose_by_position(entry, later, self.policy.twin_max_distance_px) or later[0]
                    assert node.bounds is not None and newest.bounds is not None
                    stable = node.bounds.moved_by(newest.bounds) <= STABILITY_TOLERANCE_PX
                    node = newest
        return node, stable

    def _reidentify_by_fingerprint(self, entry: RefEntry) -> tuple[float, float]:
        rect = entry.rect()
        if rect is None:
            raise AgentPlayError(ErrorCode.STALE_REF, f"{entry.ref_id} has no bounds", details={"kind": "saved_ref_absent"})
        frame = self.capture()
        if entry.fingerprint:
            similarity = fingerprint_similarity(entry.fingerprint, frame.fingerprint(rect))
            if similarity < self.policy.fingerprint_threshold:
                self.on_event("ref.resolve.error", {"ref_id": entry.ref_id, "kind": "fingerprint_mismatch", "similarity": round(similarity, 3)})
                raise AgentPlayError(
                    ErrorCode.STALE_REF,
                    f"The screen region of {entry.ref_id} no longer looks like the captured element",
                    "Take a fresh snapshot and use the new ref.",
                    {"kind": "fingerprint_mismatch", "similarity": round(similarity, 3), "threshold": self.policy.fingerprint_threshold},
                )
        self._require_on_screen(*rect.center)
        return rect.center

    def _require_on_screen(self, x: float, y: float) -> None:
        width, height = self.screen()
        if width and height and not (0 <= x < width and 0 <= y < height):
            raise AgentPlayError(ErrorCode.ACTION_FAILED, f"Point ({x:.0f}, {y:.0f}) is outside the {width}x{height} screen", details={"kind": "offscreen"})

    def _delegate_a11y(self, request: ActionRequest, target: "_Target") -> ActionResult:
        assert target.entry is not None and self.a11y_click is not None
        native = target.entry.native_id or ""
        if not native.startswith("@"):
            return self._dispatch(request, target)
        envelope = self.a11y_click(native)
        if not envelope.get("ok"):
            error = envelope.get("error", {})
            disposition = error.get("disposition", {}).get("delivery", "not_delivered")
            raise AgentPlayError(ErrorCode.ACTION_FAILED, f"agent-desktop click failed: {error.get('message')}", error.get("suggestion"), {"agent_desktop": error}, Delivery(disposition))
        data = envelope.get("data", {})
        delivery = Delivery(data.get("disposition", {}).get("delivery", "delivered_unverified"))
        return ActionResult("click", delivery, request.ref_id, target.point, reidentified_by="a11y", details={"delegated_to": "agent-desktop"}, surfaces=[s.get("type", "") for s in data.get("surfaces", []) if isinstance(s, dict)])

    def _dispatch(self, request: ActionRequest, target: "_Target | None") -> ActionResult:
        self.on_event("action.start", {"action": request.action, "ref_id": request.ref_id})
        sent = False
        try:
            if request.action in ("click", "mouse_click", "double_click", "right_click", "hover"):
                assert target is not None and target.point is not None
                x, y = target.point
                sent = True
                if request.action == "hover":
                    self.backend.move(x, y)
                elif request.action == "double_click":
                    self.backend.click(x, y, "left", 2)
                elif request.action == "right_click":
                    self.backend.click(x, y, "right", 1)
                else:
                    self.backend.click(x, y, request.button, 1)
            elif request.action == "scroll":
                assert target is not None and target.point is not None
                x, y = target.point
                sign = -1 if request.direction in ("down", "right") else 1
                dx, dy = (sign * request.amount, 0) if request.direction in ("left", "right") else (0, sign * request.amount)
                sent = True
                self.backend.scroll(x, y, dx, dy)
            elif request.action == "drag":
                assert target is not None and target.point is not None
                dest = self._drag_destination(request)
                sent = True
                self.backend.drag(target.point[0], target.point[1], dest[0], dest[1], request.duration_ms or 300, request.button)
            elif request.action == "press":
                if not request.key:
                    raise AgentPlayError(ErrorCode.INVALID_ARGS, "press needs a key")
                combo = parse_combo(request.key)
                sent = True
                self.backend.press(combo)
            elif request.action in ("key_down", "key_up"):
                if not request.key:
                    raise AgentPlayError(ErrorCode.INVALID_ARGS, f"{request.action} needs a key")
                sent = True
                (self.backend.key_down if request.action == "key_down" else self.backend.key_up)(request.key)
            elif request.action == "hold_key":
                if not request.key:
                    raise AgentPlayError(ErrorCode.INVALID_ARGS, "hold_key needs a key")
                sent = True
                self.backend.hold_key(request.key, request.duration_ms or 100)
            elif request.action == "type_text":
                if request.text is None:
                    raise AgentPlayError(ErrorCode.INVALID_ARGS, "type_text needs text")
                sent = True
                self.backend.type_text(request.text)
        except AgentPlayError as exc:
            exc.delivery = Delivery.DELIVERY_UNCERTAIN if sent else Delivery.NOT_DELIVERED
            self.on_event("action.error", {"action": request.action, "code": exc.code.value})
            raise
        except Exception as exc:
            self.on_event("action.error", {"action": request.action, "code": "ACTION_FAILED"})
            raise AgentPlayError(
                ErrorCode.ACTION_FAILED,
                f"{request.action} failed in the {self.backend.name} backend: {exc}",
                details={"cause": type(exc).__name__},
                delivery=Delivery.DELIVERY_UNCERTAIN if sent else Delivery.NOT_DELIVERED,
            ) from exc
        return ActionResult(
            request.action,
            Delivery.DELIVERED_UNVERIFIED,
            request.ref_id,
            target.point if target else None,
            reidentified_by=target.method if target else None,
            stable=target.stable if target else None,
        )

    def _drag_destination(self, request: ActionRequest) -> tuple[float, float]:
        if request.to_ref:
            entry = self.refs.resolve(request.to_ref)
            rect = entry.rect()
            if rect is None:
                raise AgentPlayError(ErrorCode.STALE_REF, f"{request.to_ref} has no bounds")
            return rect.center
        if request.to_x is None or request.to_y is None:
            raise AgentPlayError(ErrorCode.INVALID_ARGS, "drag needs to_ref or to_x,to_y")
        return (request.to_x, request.to_y)

    def _verify(self, request: ActionRequest, result: ActionResult, before: Snapshot | None, before_frame: Frame | None, after: Snapshot | None) -> None:
        if after is not None and before is not None:
            result.events = diff_snapshots(before, after)
            result.surfaces = list(after.surfaces)
            changed = bool(result.events)
            scope = "scene_diff"
        else:
            fresh = self.capture()
            previous = before_frame.hash() if before_frame is not None else None
            changed = previous is not None and fresh.hash() != previous
            scope = "frame_hash"
            if changed:
                result.events = [SceneEvent("frame_changed")]
        if request.expect_text:
            found = after is not None and any(request.expect_text.lower() in ((n.value or "") + " " + (n.name or "")).lower() for n in after.nodes())
            result.verification = {"scope": "expected_text", "expected": request.expect_text, "found": found}
            result.delivery = Delivery.DELIVERED_VERIFIED if found else Delivery.DELIVERED_UNVERIFIED
            if not found:
                result.verification["reason"] = "expected_text_absent"
            return
        if request.action == "hover":
            result.verification = {"scope": "unavailable", "reason": "hover_has_no_readback"}
            return
        if changed:
            result.delivery = Delivery.DELIVERED_VERIFIED
            result.verification = {"scope": scope, "reason": "scene_changed"}
        else:
            result.delivery = Delivery.DELIVERED_UNVERIFIED
            result.verification = {"scope": scope, "reason": "no_observable_change"}
        self.on_event("action.end", {"action": request.action, "delivery": result.delivery.value, "events": len(result.events)})
