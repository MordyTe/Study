import pytest
from PIL import Image, ImageDraw

from agent_play.actions.backend import DryRunBackend
from agent_play.actions.executor import ActionRequest
from agent_play.actions.policy import InteractionPolicy
from agent_play.envelope import AgentPlayError, Delivery, ErrorCode
from agent_play.perception.base import Perception
from agent_play.perception.capture import CallableFrameSource
from agent_play.scene.node import Rect, SceneNode
from agent_play.session import Session
from agent_play.sim.grid_game import START_RECT


def _start_ref(session):
    snapshot = session.observe()
    node = next(n for n in snapshot.nodes() if n.name == "start")
    return node.ref_id


def test_click_on_start_is_reidentified_and_verified(sim_session, game):
    ref = _start_ref(sim_session)
    result = sim_session.act(ActionRequest("click", ref_id=ref))
    assert game.state == "dialog"
    assert result.delivery is Delivery.DELIVERED_VERIFIED
    assert result.reidentified_by == "scene"
    assert result.verification == {"scope": "scene_diff", "reason": "scene_changed"}
    kinds = {event.kind for event in result.events}
    assert "node_disappeared" in kinds and "node_appeared" in kinds
    assert START_RECT.contains_point(*result.point)
    assert result.to_dict()["disposition"] == {"delivery": "delivered_verified", "retry": "unsafe"}


def test_stale_ref_after_the_screen_changed(sim_session, game):
    ref = _start_ref(sim_session)
    sim_session.act(ActionRequest("click", ref_id=ref))
    with pytest.raises(AgentPlayError) as info:
        sim_session.act(ActionRequest("click", ref_id=ref))
    assert info.value.code is ErrorCode.STALE_REF
    assert info.value.details["kind"] == "saved_ref_absent"
    assert info.value.delivery is Delivery.NOT_DELIVERED
    assert game.state == "dialog", "nothing was sent"


def test_key_press_moves_player_and_verification_sees_the_move(sim_session, game):
    sim_session.act(ActionRequest("click", ref_id=_start_ref(sim_session)))
    sim_session.act(ActionRequest("press", key="enter"))
    assert game.state == "playing"
    result = sim_session.act(ActionRequest("press", key="right"))
    assert game.player == (1, 0)
    assert result.delivery is Delivery.DELIVERED_VERIFIED
    moved = [e for e in result.events if e.kind == "node_moved" and e.role == "player"]
    assert moved and moved[0].details["from"][0] < moved[0].details["to"][0]


def test_blocked_move_is_delivered_but_unverified(sim_session, game):
    sim_session.act(ActionRequest("click", ref_id=_start_ref(sim_session)))
    sim_session.act(ActionRequest("press", key="enter"))
    result = sim_session.act(ActionRequest("press", key="up"))
    assert game.player == (0, 0)
    assert result.delivery is Delivery.DELIVERED_UNVERIFIED
    assert result.verification["reason"] == "no_observable_change"


def test_expected_text_verification(truth_session, game):
    snapshot = truth_session.observe()
    ref = next(n.ref_id for n in snapshot.nodes() if n.name == "START")
    result = truth_session.act(ActionRequest("click", ref_id=ref, expect_text="Welcome"))
    assert result.delivery is Delivery.DELIVERED_VERIFIED and result.verification["found"] is True
    assert result.surfaces == ["dialog"]


def test_policy_denials_send_nothing(sim_session, game):
    ref = _start_ref(sim_session)
    sim_session.policy.allow_coordinates = False
    with pytest.raises(AgentPlayError) as denied:
        sim_session.act(ActionRequest("mouse_click", x=1, y=1))
    assert denied.value.code is ErrorCode.POLICY_DENIED
    sim_session.policy.blocked_actions.add("click")
    with pytest.raises(AgentPlayError):
        sim_session.act(ActionRequest("click", ref_id=ref))
    assert game.state == "title"


def test_rate_limit():
    policy = InteractionPolicy(max_actions_per_minute=2)
    policy.check_action("press")
    policy.check_action("press")
    with pytest.raises(AgentPlayError) as info:
        policy.check_action("press")
    assert info.value.code is ErrorCode.POLICY_DENIED


def test_invalid_requests_are_not_delivered(sim_session):
    with pytest.raises(AgentPlayError) as info:
        sim_session.act(ActionRequest("press"))
    assert info.value.code is ErrorCode.INVALID_ARGS and info.value.delivery is Delivery.NOT_DELIVERED
    with pytest.raises(AgentPlayError) as unknown:
        sim_session.act(ActionRequest("teleport"))
    assert unknown.value.code is ErrorCode.INVALID_ARGS
    with pytest.raises(AgentPlayError) as off:
        sim_session.act(ActionRequest("mouse_click", x=5000, y=5000))
    assert off.value.details["kind"] == "offscreen"


def test_disabled_element_is_refused(tmp_path):
    class Static:
        name, fast = "sim", True

        def available(self):
            return True

        def perceive(self, frame):
            return Perception(nodes=[SceneNode("button", "Buy", Rect(10, 10, 40, 20), "sim", states=["disabled"])])

    session = Session(CallableFrameSource(lambda: Image.new("RGB", (100, 100))), [Static()], DryRunBackend(), InteractionPolicy(settle_ms=0), root=tmp_path, sleep=lambda s: None)
    ref = session.observe().nodes()[0].ref_id
    with pytest.raises(AgentPlayError) as info:
        session.act(ActionRequest("click", ref_id=ref))
    assert info.value.code is ErrorCode.ACTION_FAILED and info.value.details["kind"] == "not_enabled"


class _VisionOnly:
    """A slow perceiver that reports a button wherever the fake 'model' says it is."""

    name, fast = "vision", False

    def __init__(self, rect):
        self.rect = rect

    def available(self):
        return True

    def perceive(self, frame):
        return Perception(nodes=[SceneNode("button", "Go", self.rect, "vision", confidence=0.7)])


def _frame_with_button(color):
    image = Image.new("RGB", (120, 80), (10, 10, 10))
    ImageDraw.Draw(image).rectangle((20, 20, 60, 40), fill=color, outline=(255, 255, 255))
    return image


def test_fingerprint_reidentification_when_only_vision_exists(tmp_path):
    current = {"image": _frame_with_button((40, 160, 90))}
    backend = DryRunBackend()
    session = Session(CallableFrameSource(lambda: current["image"]), [_VisionOnly(Rect(20, 20, 41, 21))], backend, InteractionPolicy(settle_ms=0), root=tmp_path, sleep=lambda s: None)
    ref = session.observe().nodes()[0].ref_id
    result = session.act(ActionRequest("click", ref_id=ref))
    assert result.reidentified_by == "fingerprint"
    assert result.delivery is Delivery.DELIVERED_UNVERIFIED and result.verification["scope"] == "frame_hash"
    assert backend.events[-1].kind == "mouse_up" and 20 <= backend.events[-1].x <= 61

    current["image"] = Image.new("RGB", (120, 80), (10, 10, 10))
    with pytest.raises(AgentPlayError) as info:
        session.act(ActionRequest("click", ref_id=ref))
    assert info.value.code is ErrorCode.STALE_REF and info.value.details["kind"] == "fingerprint_mismatch"


def test_ambiguous_twins_far_from_the_captured_position(tmp_path):
    positions = {"rects": [Rect(0, 0, 10, 10), Rect(100, 0, 10, 10)]}

    class Twins:
        name, fast = "sim", True

        def available(self):
            return True

        def perceive(self, frame):
            return Perception(nodes=[SceneNode("enemy", "slime", r, "sim", native_id="slime") for r in positions["rects"]])

    session = Session(CallableFrameSource(lambda: Image.new("RGB", (200, 50))), [Twins()], DryRunBackend(), InteractionPolicy(settle_ms=0, twin_max_distance_px=5), root=tmp_path, sleep=lambda s: None)
    ref = session.observe().nodes()[0].ref_id
    positions["rects"] = [Rect(50, 0, 10, 10), Rect(150, 0, 10, 10)]
    with pytest.raises(AgentPlayError) as info:
        session.act(ActionRequest("click", ref_id=ref))
    assert info.value.code is ErrorCode.AMBIGUOUS_TARGET and info.value.details["candidate_count"] == 2
    positions["rects"] = [Rect(2, 0, 10, 10), Rect(150, 0, 10, 10)]
    result = session.act(ActionRequest("click", ref_id=ref))
    assert result.point[0] < 20 and result.stable is True
