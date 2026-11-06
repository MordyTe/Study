import json

from agent_play.agent.loop import AgentConfig, GameAgent
from agent_play.agent.model import ScriptedModelClient, ToolCall
from agent_play.knowledge.anticheat import assess, known_games, known_systems
from agent_play.knowledge.store import KnowledgeStore
from agent_play.sim.grid_game import GridGame, make_session
from agent_play.skills import list_skills, load_skill


def test_registry_is_consistent():
    systems = known_systems()
    for game in known_games():
        assert game["policy"] in ("refuse", "warn", "ok")
        assert game["system"] is None or game["system"] in systems


def test_protected_games_get_the_refuse_tier_by_name_or_alias():
    for text in ("play Valorant ranked for me", "win a game of valo", "grind Fortnite", "farm gold in WoW", "a CS2 match"):
        result = assess(text)
        assert result.policy == "refuse", text
        assert result.system is not None and "ban" in result.reason


def test_offline_games_are_ok_and_online_words_raise_a_warning():
    assert assess("water the crops in Stardew Valley").policy == "ok"
    assert assess("play Civilization VI multiplayer").policy == "warn"
    assert assess("play Minecraft on my own world").policy == "warn"


def test_unknown_games_proceed_unless_the_task_sounds_online():
    assert assess("beat level 3 of my puzzle game").policy == "unknown"
    warned = assess("climb the leaderboard in some new game")
    assert warned.policy == "warn" and "leaderboard" in warned.keywords


def test_agent_warns_but_proceeds_by_default(sim_session):
    model = ScriptedModelClient([[ToolCall("", "done", {"success": False, "summary": "stopping"})]])
    result = GameAgent(sim_session, model, AgentConfig(include_image=False)).run("Win a ranked match in Valorant")
    assert result.status == "failed", "the default is to warn and continue, not block"
    assert model.turn_index == 1, "the model was consulted"
    assert result.assessment["policy"] == "refuse" and result.assessment["system"] == "vanguard"
    assert any(note.startswith("Anti-cheat risk") and "ban" in note for note in result.memory.notes)
    assert result.to_dict()["anticheat"]["game"] == "valorant"


def test_block_protected_flag_stops_before_observing(sim_session):
    model = ScriptedModelClient([[ToolCall("", "done", {"success": True, "summary": "should never run"})]])
    result = GameAgent(sim_session, model, AgentConfig(include_image=False, block_protected=True)).run("Win a ranked match in Valorant")
    assert result.status == "blocked_policy"
    assert model.turn_index == 0, "the model was never called"
    assert "snapshot.saved" not in [e["event"] for e in sim_session.trace.events]
    assert result.assessment["system_name"].startswith("Riot Vanguard")


def test_warn_game_adds_a_note_and_continues(sim_session):
    model = ScriptedModelClient([[ToolCall("", "done", {"success": False, "summary": "stopping"})]])
    result = GameAgent(sim_session, model, AgentConfig(include_image=False)).run("play Minecraft on a server")
    assert result.status == "failed" and result.assessment["policy"] == "warn"
    assert any(note.startswith("Anti-cheat risk") for note in result.memory.notes)


def test_anti_cheat_skill_is_loaded_by_default(sim_session):
    assert "anti_cheat" in list_skills()
    model = ScriptedModelClient([[ToolCall("", "done", {"success": False, "summary": "x"})]])
    GameAgent(sim_session, model, AgentConfig(include_image=False)).run("reach the star")
    assert "Anti-cheat awareness" in model.systems[0]
    assert "refuse" in load_skill("anti_cheat")


def test_learn_persists_across_sessions(tmp_path):
    first = make_session(GridGame(), root=tmp_path, session_id="a")
    teacher = ScriptedModelClient(
        [
            [ToolCall("", "learn", {"topic": "grid game", "text": "the star is the goal; walls block movement"})],
            [ToolCall("", "done", {"success": False, "summary": "noted"})],
        ]
    )
    GameAgent(first, teacher, AgentConfig(include_image=False)).run("explore the grid")
    assert (tmp_path / "knowledge" / "grid-game.md").exists()

    second = make_session(GridGame(), root=tmp_path, session_id="b")
    later = GameAgent(second, ScriptedModelClient([[ToolCall("", "done", {"success": False, "summary": "x"})]]), AgentConfig(include_image=False))
    prompt = later.system_prompt()
    assert "Knowledge you kept from earlier runs" in prompt
    assert "the star is the goal" in prompt


def test_knowledge_store_in_memory_without_a_root():
    store = KnowledgeStore(None)
    store.add("controls", "wasd moves the hero")
    assert "controls" in store.topics()
    assert "wasd moves" in store.read("controls")
    assert "wasd moves" in store.render()


def test_cli_anticheat_command(capsys):
    from agent_play.cli import main

    assert main(["anticheat", "play apex legends"]) == 0
    envelope = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert envelope["data"]["policy"] == "refuse" and envelope["data"]["system"] == "eac"
    assert main(["anticheat", "--list"]) == 0
    listing = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert "vanguard" in listing["data"]["systems"] and len(listing["data"]["games"]) > 20


def test_cli_knowledge_commands(capsys, tmp_path):
    from agent_play.cli import main

    assert main(["--home", str(tmp_path), "knowledge", "add", "controls", "wasd moves the hero"]) == 0
    capsys.readouterr()
    assert main(["--home", str(tmp_path), "knowledge", "list"]) == 0
    listing = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert "controls" in listing["data"]["topics"]
    assert main(["--home", str(tmp_path), "knowledge", "show", "controls"]) == 0
    shown = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert "wasd moves the hero" in shown["data"]["content"]
