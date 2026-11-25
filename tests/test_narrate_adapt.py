import io
import json

from agent_play.agent.adapt import pick_genre
from agent_play.narrate import LiveNarrator
from agent_play.scene.node import Rect, SceneNode
from agent_play.scene.snapshot import Snapshot


def _scene(nodes, summary=None, surfaces=()):
    return Snapshot(roots=list(nodes), screen=(480, 360), summary=summary, surfaces=list(surfaces), sources=["vision"])


def test_narrator_renders_the_loop_lines():
    buf = io.StringIO()
    n = LiveNarrator(stream=buf, color=False)
    snap = _scene([
        SceneNode("player", "hero", Rect(80, 70, 40, 40), "template"),
        SceneNode("objective", "star", Rect(320, 230, 34, 34), "template"),
        SceneNode("obstacle", "wall", Rect(160, 110, 40, 40), "template"),
    ])
    n.observe(snap)
    out = buf.getvalue()
    assert "[screen]" in out and "480x360 captured" in out
    assert "[detect]" in out and 'player "hero"' in out and 'objective "star"' in out and "1 obstacle" in out


def test_narrator_think_from_tool_calls_and_text():
    buf = io.StringIO()
    n = LiveNarrator(stream=buf, color=False)

    class Call:
        def __init__(self, name, inp):
            self.name, self.input = name, inp

    n.think(3, "", [Call("press", {"key": "right"})])
    n.think(4, "move toward the star", [])
    out = buf.getvalue()
    assert "step 3: press right" in out
    assert "step 4: move toward the star" in out


def test_narrator_act_shows_verify_and_change():
    buf = io.StringIO()
    n = LiveNarrator(stream=buf, color=False)
    ok = json.dumps({"ok": True, "data": {"action": "press", "disposition": {"delivery": "delivered_verified"},
                                          "events": [{"kind": "node_moved", "role": "player", "name": "hero", "from": [100, 90], "to": [140, 90]}]}})
    n.act("press", ok, False)
    out = buf.getvalue()
    assert "act]" in out and "verify]" in out
    assert "delivered_verified" in out and "moved (100, 90)→(140, 90)" in out

    buf2 = io.StringIO()
    n2 = LiveNarrator(stream=buf2, color=False)
    err = json.dumps({"ok": False, "command": "click", "error": {"code": "STALE_REF", "message": "gone"}})
    n2.act("click", err, True)
    assert "STALE_REF" in buf2.getvalue()


def test_adapt_picks_genre_from_roles_and_summary():
    menus = _scene([SceneNode("button", "Start", Rect(0, 0, 10, 10)), SceneNode("menu_item", "Options", Rect(0, 20, 10, 10))])
    genre, _ = pick_genre(menus)
    assert genre == "genres/menus"

    action = _scene([SceneNode("player", "hero", Rect(0, 0, 10, 10)), SceneNode("enemy", "slime", Rect(50, 0, 10, 10))])
    assert pick_genre(action)[0] == "genres/action_adventure"

    puzzle = _scene([SceneNode("image", "x", Rect(0, 0, 10, 10))], summary="A sliding tile puzzle board")
    assert pick_genre(puzzle)[0] == "genres/puzzle"

    blank = _scene([SceneNode("image", "x", Rect(0, 0, 10, 10))])
    assert pick_genre(blank)[0] is None
