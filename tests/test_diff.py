from agent_play.scene.diff import diff_snapshots
from agent_play.scene.node import Rect, SceneNode
from agent_play.scene.snapshot import Snapshot


def _snap(nodes, surfaces=(), frame_hash=None):
    return Snapshot(roots=list(nodes), surfaces=list(surfaces), frame_hash=frame_hash)


def test_appear_disappear_move_value_and_surface_events_in_rank_order():
    before = _snap(
        [
            SceneNode("player", "hero", Rect(0, 0, 10, 10), native_id="hero"),
            SceneNode("button", "Start", Rect(50, 50, 20, 10)),
            SceneNode("hud", "moves", Rect(0, 90, 10, 5), value="Moves: 0"),
        ],
        surfaces=["dialog"],
    )
    after = _snap(
        [
            SceneNode("player", "hero", Rect(40, 0, 10, 10), native_id="hero"),
            SceneNode("hud", "moves", Rect(0, 90, 10, 5), value="Moves: 1"),
            SceneNode("dialog", "Welcome", Rect(10, 10, 50, 50)),
        ],
    )
    kinds = [event.kind for event in diff_snapshots(before, after)]
    assert kinds == ["surface_dismissed", "node_disappeared", "node_appeared", "node_moved", "value_changed"]
    moved = next(e for e in diff_snapshots(before, after) if e.kind == "node_moved")
    assert moved.details["from"] == (5, 5) and moved.details["to"] == (45, 5)
    assert str(moved).startswith('node_moved player "hero"')


def test_twins_are_matched_to_the_nearest_counterpart():
    before = _snap([SceneNode("enemy", "slime", Rect(0, 0, 10, 10)), SceneNode("enemy", "slime", Rect(100, 0, 10, 10))])
    after = _snap([SceneNode("enemy", "slime", Rect(101, 0, 10, 10)), SceneNode("enemy", "slime", Rect(1, 0, 10, 10))])
    assert diff_snapshots(before, after) == []


def test_frame_hash_fallback_when_no_nodes_changed():
    before = _snap([], frame_hash="aaaa")
    after = _snap([], frame_hash="bbbb")
    assert [e.kind for e in diff_snapshots(before, after)] == ["frame_changed"]
    assert diff_snapshots(before, _snap([], frame_hash="aaaa")) == []
