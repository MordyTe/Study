import json

from agent_play.agent.loop import OMITTED_FRAME, AgentConfig, GameAgent
from agent_play.agent.model import ModelTurn, ScriptedModelClient, ToolCall
from agent_play.sim.grid_game import path_to_goal


def _ref_named(session, name):
    snapshot = session.last_snapshot
    return next(n.ref_id for n in snapshot.nodes() if n.name == name and n.ref_id)


def _scripted_player(session, game, claim_early=False):
    def script(messages, index):
        if game.state == "title":
            return [ToolCall("", "set_objectives", {"objectives": [{"text": "press start", "status": "active"}, {"text": "reach the star", "status": "pending"}]}), ToolCall("", "click", {"ref_id": _ref_named(session, "start")})]
        if game.state == "dialog":
            return [ToolCall("", "remember", {"note": "the welcome dialog closes with enter"}), ToolCall("", "press", {"key": "enter"})]
        if game.state == "playing":
            path = path_to_goal(game)
            calls = [ToolCall("", "press", {"key": key}) for key in path[:3]]
            if claim_early and len(path) <= 3:
                calls.append(ToolCall("", "done", {"success": True, "summary": "I pressed the last key"}))
            return calls
        return [ToolCall("", "done", {"success": True, "summary": "YOU WIN is on screen"})]

    return ScriptedModelClient(script)


def test_scripted_model_wins_the_game_through_pixels(sim_session, game):
    model = _scripted_player(sim_session, game)
    agent = GameAgent(sim_session, model, AgentConfig(max_steps=30, include_image=True), skills=["core", "genres/puzzle"])
    result = agent.run("Reach the star.")
    assert result.status == "success", result.summary
    assert game.won and game.moves > 0
    assert result.memory.notes == ["the welcome dialog closes with enter"]
    assert [o.text for o in result.memory.objectives] == ["press start", "reach the star"]
    assert "agent-play core" in model.systems[0] and "Puzzle games" in model.systems[0]
    first_user = model.seen[0][0]["content"]
    assert first_user[0]["type"] == "image" and "First observation" in first_user[1]["text"]
    last_messages = model.seen[-1]
    tool_results = [b for b in last_messages[-1]["content"] if b.get("type") == "tool_result"]
    assert tool_results and all(not b["is_error"] for b in tool_results)
    payload = json.loads(tool_results[-1]["content"])
    assert payload["ok"] and payload["data"]["disposition"]["delivery"] in ("delivered_verified", "delivered_unverified")
    images = [b for m in last_messages if m["role"] == "user" for b in m["content"] if b.get("type") == "image"]
    assert len(images) == 1, "only the latest frame stays in context"
    assert any(b.get("text") == OMITTED_FRAME for m in last_messages if m["role"] == "user" for b in m["content"])
    trace_events = [e["event"] for e in sim_session.trace.events]
    assert trace_events.count("run.start") == 1 and trace_events[-1] == "run.end"


def test_success_claimed_before_observing_is_downgraded(sim_session, game):
    model = _scripted_player(sim_session, game, claim_early=True)
    result = GameAgent(sim_session, model, AgentConfig(max_steps=30, include_image=False)).run("Reach the star.")
    assert result.status == "success_unverified"
    assert "before observing" in result.summary


def test_stale_ref_error_is_returned_to_the_model_and_recovered(sim_session, game):
    stale = {"ref": None}

    def script(messages, index):
        if index == 0:
            stale["ref"] = _ref_named(sim_session, "start")
            return [ToolCall("", "click", {"ref_id": stale["ref"]})]
        if index == 1:
            return [ToolCall("", "click", {"ref_id": stale["ref"]})]
        if index == 2:
            return [ToolCall("", "press", {"key": "enter"})]
        return [ToolCall("", "done", {"success": False, "summary": "stopping"})]

    model = ScriptedModelClient(script)
    result = GameAgent(sim_session, model, AgentConfig(max_steps=6, include_image=False)).run("test")
    second_turn_results = [b for b in model.seen[2][-1]["content"] if b.get("type") == "tool_result"]
    assert second_turn_results[0]["is_error"] is True
    assert json.loads(second_turn_results[0]["content"])["error"]["code"] == "STALE_REF"
    assert game.state == "playing" and result.status == "failed"
    assert any("stale" in line.lower() or "STALE_REF" in line for line in result.memory.recent)


def test_ask_user_stops_with_question(sim_session):
    model = ScriptedModelClient([[ToolCall("", "ask_user", {"question": "Which save slot?"})]])
    result = GameAgent(sim_session, model, AgentConfig(include_image=False)).run("load the game")
    assert result.status == "needs_input" and result.question == "Which save slot?"


def test_refusal_and_text_only_turns_end_the_run(sim_session):
    refusal = ScriptedModelClient([ModelTurn("", [], "refusal", [{"type": "text", "text": ""}], refusal_category="cyber")])
    assert GameAgent(sim_session, refusal, AgentConfig(include_image=False)).run("x").status == "refused"
    chatty = ScriptedModelClient([ModelTurn("thinking out loud", [], "end_turn", [{"type": "text", "text": "hmm"}])] * 5)
    result = GameAgent(sim_session, chatty, AgentConfig(include_image=False, max_text_turns=1)).run("x")
    assert result.status == "failed" and "stopped calling tools" in result.summary


def test_step_budget_exhaustion_is_reported(sim_session):
    model = ScriptedModelClient(lambda messages, index: [ToolCall("", "observe", {"detail": "fast"})])
    result = GameAgent(sim_session, model, AgentConfig(max_steps=3, include_image=False)).run("loop forever")
    assert result.status == "budget_exhausted" and result.steps == 3
    assert result.to_dict()["trace_path"].endswith("trace.jsonl")
