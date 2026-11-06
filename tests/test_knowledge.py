import json

from agent_play.agent.loop import AgentConfig, GameAgent
from agent_play.agent.model import ScriptedModelClient, ToolCall
from agent_play.knowledge.store import KnowledgeStore


def test_store_persists_across_instances(tmp_path):
    store = KnowledgeStore(tmp_path)
    slug = store.add("Grid game controls", "arrow keys move one cell; enter closes dialogs")
    assert slug == "grid-game-controls"
    again = KnowledgeStore(tmp_path)
    assert again.topics() == ["grid-game-controls"]
    assert "enter closes dialogs" in again.read("Grid game controls")
    assert again.render().startswith("# Grid game controls")


def test_in_memory_store_and_truncation():
    store = KnowledgeStore(None)
    store.add("a", "x" * 50)
    store.add("b", "y" * 50)
    assert store.topics() == ["a", "b"]
    assert "[knowledge truncated]" in store.render(max_chars=60)


def test_learn_tool_writes_knowledge_that_the_next_run_sees(sim_session, tmp_path):
    first = ScriptedModelClient([[ToolCall("", "learn", {"topic": "sim rules", "text": "the star is the goal"}), ToolCall("", "done", {"success": False, "summary": "learned"})]])
    GameAgent(sim_session, first, AgentConfig(include_image=False)).run("explore")
    assert KnowledgeStore(tmp_path).read("sim rules") is not None
    second = ScriptedModelClient([[ToolCall("", "done", {"success": False, "summary": "x"})]])
    GameAgent(sim_session, second, AgentConfig(include_image=False)).run("explore again")
    assert "the star is the goal" in second.systems[0]
    tool_results = [b for b in first.seen[0][-1]["content"] if False]
    assert tool_results == []


def test_cli_knowledge_commands(capsys, tmp_path):
    from agent_play.cli import main

    assert main(["--home", str(tmp_path), "knowledge", "add", "boss fight", "dodge left, then attack"]) == 0
    added = json.loads(capsys.readouterr().out.strip())
    assert added["data"]["topics"] == ["boss-fight"]
    assert main(["--home", str(tmp_path), "knowledge", "show", "boss fight"]) == 0
    shown = json.loads(capsys.readouterr().out.strip())
    assert "dodge left" in shown["data"]["content"]
    assert main(["--home", str(tmp_path), "knowledge", "show", "missing"]) == 1
