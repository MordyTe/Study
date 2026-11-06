from agent_play.perception.fusion import fuse
from agent_play.scene.node import Rect, SceneNode


def test_higher_priority_source_keeps_identity_and_gains_corroboration():
    template = SceneNode("button", "start", Rect(10, 10, 100, 40), "template", confidence=0.93)
    vision = SceneNode("button", "Start game", Rect(12, 11, 98, 40), "vision", confidence=0.7, value="START")
    fused = fuse([("vision", [vision]), ("template", [template])])
    assert len(fused) == 1
    node = fused[0]
    assert node.name == "start" and node.source == "template"
    assert node.value == "START", "the lower source fills missing text"
    assert node.corroborated_by == ["vision"] and node.confidence == 0.93


def test_ocr_text_labels_an_unnamed_vision_box():
    box = SceneNode("button", None, Rect(0, 0, 60, 20), "vision", confidence=0.6)
    text = SceneNode("text", "OK", Rect(2, 2, 56, 16), "ocr", value="OK")
    (node,) = fuse([("vision", [box]), ("ocr", [text])])
    assert node.role == "button" and node.name == "OK" and node.source == "ocr"
    assert "vision" in node.corroborated_by and node.interactive


def test_non_overlapping_and_incompatible_nodes_stay_separate():
    a = SceneNode("button", "a", Rect(0, 0, 10, 10), "vision")
    b = SceneNode("button", "b", Rect(50, 50, 10, 10), "vision")
    c = SceneNode("enemy", "c", Rect(0, 0, 10, 10), "template")
    assert len(fuse([("vision", [a, b]), ("template", [c])])) == 3


def test_accessibility_tree_is_kept_whole_and_absorbs_overlaps():
    child = SceneNode("button", "Save", Rect(10, 10, 30, 10), "a11y", native_id="@sx:e1")
    window = SceneNode("window", "App", Rect(0, 0, 100, 100), "a11y", children=[child])
    vision = SceneNode("button", "Save?", Rect(11, 10, 29, 10), "vision", confidence=0.5)
    fused = fuse([("vision", [vision]), ("a11y", [window])])
    assert fused == [window]
    assert child.corroborated_by == ["vision"] and child.name == "Save"
