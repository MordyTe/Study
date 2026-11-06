"""Live run: Claude plays the simulator for real. Skipped unless ANTHROPIC_API_KEY is set."""

import os

import pytest

from agent_play.agent.loop import AgentConfig, GameAgent
from agent_play.agent.model import AnthropicModelClient

pytestmark = pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")


def test_live_claude_plays_the_simulator(sim_session, game):
    agent = GameAgent(sim_session, AnthropicModelClient(effort="medium"), AgentConfig(max_steps=30), skills=["core", "genres/puzzle"])
    result = agent.run("Reach the star.")
    assert result.status in ("success", "success_unverified"), result.summary
    assert game.won
