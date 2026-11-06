from __future__ import annotations

import pytest

from agent_play.sim.grid_game import GridGame, make_session


@pytest.fixture
def game() -> GridGame:
    return GridGame()


@pytest.fixture
def sim_session(game: GridGame, tmp_path):
    return make_session(game, root=tmp_path)


@pytest.fixture
def truth_session(game: GridGame, tmp_path):
    return make_session(game, root=tmp_path, ground_truth=True)
