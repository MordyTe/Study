from agent_play.scene.node import Rect, SceneNode
from agent_play.scene.snapshot import Snapshot, new_snapshot_id


def test_rect_geometry():
    a = Rect(0, 0, 10, 10)
    b = Rect(5, 5, 10, 10)
    assert a.center == (5, 5)
    assert abs(a.iou(b) - 25 / 175) < 1e-9
    assert a.iou(Rect(20, 20, 5, 5)) == 0.0
    assert a.contains_point(10, 10) and not a.contains_point(11, 0)
    assert Rect.from_xyxy(10, 10, 0, 0) == Rect(0, 0, 10, 10)


def test_node_normalizes_role_and_defaults_interactive():
    button = SceneNode("Menu Item", "Save")
    assert button.role == "menu_item" and button.interactive is True
    text = SceneNode("text", "hello")
    assert text.interactive is False
    forced = SceneNode("text", "hello", interactive=True)
    assert forced.interactive is True
    assert SceneNode("button", confidence=1.7).confidence == 1.0


def test_snapshot_compact_text_and_roundtrip():
    root = SceneNode("window", "Game", Rect(0, 0, 100, 100), "sim", children=[SceneNode("button", "Start", Rect(10, 10, 20, 10), "template", confidence=0.95)])
    snapshot = Snapshot(snapshot_id="s12345678", roots=[root], screen=(100, 100), surfaces=["dialog"], summary="title screen")
    snapshot.roots[0].children[0].ref_id = "@s12345678:e1"
    text = snapshot.compact_text()
    assert "Snapshot s12345678 screen=100x100 refs=1" in text
    assert "Surfaces open: dialog" in text
    assert '  @s12345678:e1 [button] "Start" @(10,10 20x10) src=template c=0.95' in text
    again = Snapshot.from_dict(snapshot.to_dict())
    assert again.compact_text() == text
    assert again.by_ref("@s12345678:e1").name == "Start"


def test_skeleton_cuts_deep_branches_with_children_count():
    leaf = SceneNode("button", "deep", Rect(0, 0, 1, 1))
    mid = SceneNode("group", "mid", Rect(0, 0, 5, 5), children=[leaf, leaf])
    root = SceneNode("window", "root", Rect(0, 0, 9, 9), children=[mid])
    skeleton = Snapshot(roots=[root]).skeleton(depth=1)
    cut = skeleton.roots[0].children[0]
    assert cut.children == [] and cut.children_count == 2
    assert len(root.children[0].children) == 2, "the original tree is untouched"


def test_find_by_role_and_text():
    snapshot = Snapshot(roots=[SceneNode("button", "Start Game", Rect(0, 0, 1, 1)), SceneNode("text", "quest", value="Reach the star")])
    assert [n.name for n in snapshot.find(role="button")] == ["Start Game"]
    assert snapshot.find(name="the star")[0].value == "Reach the star"
    assert snapshot.find(name="start game", exact=True)[0].name == "Start Game"
    assert snapshot.find(name="start", exact=True) == []


def test_snapshot_ids_are_unique_and_well_formed():
    ids = {new_snapshot_id() for _ in range(50)}
    assert len(ids) == 50 and all(i.startswith("s") and len(i) == 9 for i in ids)
