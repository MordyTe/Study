import json

import pytest

from agent_play.actions.executor import ActionRequest
from agent_play.envelope import AgentPlayError, ErrorCode


def test_observe_allocates_refs_from_pixels(sim_session, game):
    snapshot = sim_session.observe()
    names = {(n.role, n.name): n.ref_id for n in snapshot.nodes()}
    assert names[("button", "start")].startswith(f"@{snapshot.snapshot_id}:e")
    assert snapshot.sources == ["template"] and snapshot.screen == (480, 360)
    assert snapshot.frame_hash and snapshot.complete


def test_status_reports_perceivers_and_backend(sim_session):
    status = sim_session.status()
    assert status["backend"] == "sim" and status["headed"] is True
    assert status["perceivers"] == [{"name": "template", "fast": True, "available": True}]
    assert status["screen"] == [480, 360]


def test_wait_for_text_and_timeout(truth_session, game):
    snapshot = truth_session.observe()
    ref = next(n.ref_id for n in snapshot.nodes() if n.name == "START")
    truth_session.act(ActionRequest("click", ref_id=ref))
    assert truth_session.wait(text="Press Enter", timeout_ms=50)["condition"] == "text_present"
    with pytest.raises(AgentPlayError) as info:
        truth_session.wait(text="never", timeout_ms=30, poll_ms=5)
    assert info.value.code is ErrorCode.TIMEOUT and info.value.details["retryable"] is False
    assert truth_session.wait(ref_id=ref, gone=True, timeout_ms=50)["condition"] == "ref_gone"
    assert truth_session.wait(stable=True, timeout_ms=200, poll_ms=1)["condition"] == "stable"


def test_trace_is_written_and_redacted(sim_session, tmp_path, game):
    snapshot = sim_session.observe()
    ref = next(n.ref_id for n in snapshot.nodes() if n.name == "start")
    sim_session.act(ActionRequest("click", ref_id=ref))
    sim_session.trace.write("note", {"text": "secret quest text", "count": 3})
    lines = [json.loads(line) for line in sim_session.trace.path.read_text().splitlines()]
    events = [line["event"] for line in lines]
    assert events[0] == "trace.meta"
    assert "snapshot.saved" in events and "ref.resolve.ok" in events and "action.end" in events
    note = next(line for line in lines if line["event"] == "note")
    assert note["text"] == {"redacted": True} and note["count"] == 3
    assert all(line["session_id"] == sim_session.session_id for line in lines)
    assert sim_session.dir == tmp_path / "sessions" / sim_session.session_id
