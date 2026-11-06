import pytest

from agent_play.envelope import AgentPlayError, ErrorCode
from agent_play.scene.node import Rect, SceneNode
from agent_play.scene.refs import (
    RefStore,
    choose_by_position,
    match_candidates,
    parse_ref,
)
from agent_play.scene.snapshot import Snapshot


def _snapshot():
    return Snapshot(
        snapshot_id="sabcdefgh",
        roots=[
            SceneNode("button", "Start", Rect(10, 10, 20, 10), "template"),
            SceneNode("text", "title", Rect(0, 0, 50, 5), "ocr", value="hello"),
            SceneNode("enemy", "slime", Rect(100, 100, 10, 10), "vision", native_id="t:enemy:slime"),
            SceneNode("enemy", "slime", Rect(200, 100, 10, 10), "vision", native_id="t:enemy:slime"),
            SceneNode("button", "No bounds"),
        ],
    )


def test_parse_ref_accepts_qualified_and_rejects_bare():
    assert parse_ref("@sabcdefgh:e12") == ("sabcdefgh", 12)
    for bad in ("@e1", "sabcdefgh:e1", "@sabcdefgh:e0", "@sabcdefgh:e", "@S1:e1", ""):
        with pytest.raises(AgentPlayError) as info:
            parse_ref(bad)
        assert info.value.code is ErrorCode.INVALID_ARGS


def test_allocate_only_interactive_nodes_with_bounds():
    store = RefStore()
    snapshot = store.allocate(_snapshot())
    refs = [node.ref_id for node in snapshot.nodes()]
    assert refs == ["@sabcdefgh:e1", None, "@sabcdefgh:e2", "@sabcdefgh:e3", None]
    entry = store.resolve("@sabcdefgh:e1")
    assert entry.identity_unique is True and entry.role == "button"
    assert store.resolve("@sabcdefgh:e2").identity_unique is False, "twins are not unique"


def test_resolve_errors():
    store = RefStore()
    store.allocate(_snapshot())
    with pytest.raises(AgentPlayError) as missing:
        store.resolve("@szzzzzzzz:e1")
    assert missing.value.code is ErrorCode.SNAPSHOT_NOT_FOUND
    with pytest.raises(AgentPlayError) as stale:
        store.resolve("@sabcdefgh:e99")
    assert stale.value.code is ErrorCode.STALE_REF
    assert stale.value.details["kind"] == "saved_ref_absent"


def test_refs_persist_across_processes(tmp_path):
    first = RefStore(tmp_path)
    first.allocate(_snapshot(), fingerprint_fn=lambda rect: [1, 2, 3])
    second = RefStore(tmp_path)
    entry = second.resolve("@sabcdefgh:e1")
    assert entry.fingerprint == [1, 2, 3] and entry.name == "Start"
    assert second.snapshot("sabcdefgh").ref_count() == 3
    assert second.latest().snapshot_id == "sabcdefgh"


def test_memory_store_evicts_old_snapshots():
    store = RefStore(keep_in_memory=2)
    for index in range(3):
        snapshot = _snapshot()
        snapshot.snapshot_id = f"s0000000{index}"
        store.allocate(snapshot)
    with pytest.raises(AgentPlayError) as info:
        store.resolve("@s00000000:e1")
    assert info.value.code is ErrorCode.SNAPSHOT_NOT_FOUND
    assert store.resolve("@s00000002:e1").name == "Start"


def test_twins_resolve_by_position():
    store = RefStore()
    snapshot = store.allocate(_snapshot())
    entry = store.resolve("@sabcdefgh:e3")
    fresh = [
        SceneNode("enemy", "slime", Rect(104, 100, 10, 10), "vision", native_id="t:enemy:slime"),
        SceneNode("enemy", "slime", Rect(203, 101, 10, 10), "vision", native_id="t:enemy:slime"),
    ]
    candidates = match_candidates(entry, fresh)
    assert len(candidates) == 2
    chosen = choose_by_position(entry, candidates, max_distance=20)
    assert chosen is fresh[1]
    far = [SceneNode("enemy", "slime", Rect(400, 400, 10, 10), "vision", native_id="t:enemy:slime")]
    assert choose_by_position(entry, far, max_distance=20) is None
    assert snapshot.by_ref("@sabcdefgh:e3").bounds.x == 200
