"""A tiny grid game rendered to pixels, so the whole pipeline is exercised offline.

Title screen with a Start button, a welcome dialog dismissed with Enter, a grid with walls where the
player walks to a star, and a win screen. Input arrives through `SimBackend`, perception through the
same template matcher a real game would use.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont

from agent_play.actions.backend import DryRunBackend, InputEvent
from agent_play.actions.policy import InteractionPolicy
from agent_play.perception.base import Perception
from agent_play.perception.capture import CallableFrameSource, Frame
from agent_play.perception.template import Template, TemplatePerceiver
from agent_play.scene.node import Rect, SceneNode
from agent_play.session import Session

WIDTH, HEIGHT = 480, 360
COLS, ROWS, CELL = 8, 6, 40
ORIGIN = (80, 70)
START_RECT = Rect(180, 150, 120, 44)
AGAIN_RECT = Rect(170, 200, 140, 44)
DIALOG_RECT = Rect(110, 100, 260, 150)
BACKGROUND = (28, 30, 40)
MOVES = {"up": (0, -1), "w": (0, -1), "down": (0, 1), "s": (0, 1), "left": (-1, 0), "a": (-1, 0), "right": (1, 0), "d": (1, 0)}


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


class GridGame:
    def __init__(self, goal: tuple[int, int] = (6, 4), start: tuple[int, int] = (0, 0), walls: set[tuple[int, int]] | None = None) -> None:
        self.goal = goal
        self.start = start
        self.walls = walls if walls is not None else {(2, 1), (2, 2), (2, 3), (5, 2), (5, 3), (5, 4)}
        self.reset()

    def reset(self) -> None:
        self.state = "title"
        self.player = self.start
        self.moves = 0
        self.history: list[str] = []

    @property
    def won(self) -> bool:
        return self.state == "won"

    def status(self) -> dict[str, Any]:
        return {"state": self.state, "player": list(self.player), "goal": list(self.goal), "moves": self.moves}

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "player": list(self.player),
            "goal": list(self.goal),
            "start": list(self.start),
            "walls": sorted(list(w) for w in self.walls),
            "moves": self.moves,
            "history": list(self.history),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "GridGame":
        game = GridGame(goal=tuple(data["goal"]), start=tuple(data["start"]), walls={tuple(w) for w in data["walls"]})
        game.state = data["state"]
        game.player = tuple(data["player"])
        game.moves = int(data["moves"])
        game.history = list(data.get("history", []))
        return game

    def save(self, path: Path) -> None:
        import json

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict()), encoding="utf-8")

    @staticmethod
    def load(path: Path) -> "GridGame":
        import json

        if not path.exists():
            return GridGame()
        return GridGame.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def handle(self, event: InputEvent) -> None:
        if event.kind == "mouse_up" and event.button == "left" and event.x is not None and event.y is not None:
            self._click(event.x, event.y)
        elif event.kind == "key_down" and event.key:
            self._key(event.key)

    def _click(self, x: float, y: float) -> None:
        if self.state == "title" and START_RECT.contains_point(x, y):
            self.state = "dialog"
            self.history.append("start")
        elif self.state == "won" and AGAIN_RECT.contains_point(x, y):
            self.reset()
            self.history.append("again")

    def _key(self, key: str) -> None:
        if self.state == "dialog" and key in ("enter", "space"):
            self.state = "playing"
            self.history.append("dialog dismissed")
        elif self.state == "playing" and key in MOVES:
            dx, dy = MOVES[key]
            nx, ny = self.player[0] + dx, self.player[1] + dy
            if 0 <= nx < COLS and 0 <= ny < ROWS and (nx, ny) not in self.walls:
                self.player = (nx, ny)
                self.moves += 1
                self.history.append(f"move {key}")
                if self.player == self.goal:
                    self.state = "won"
                    self.history.append("won")

    def cell_rect(self, col: int, row: int) -> Rect:
        return Rect(ORIGIN[0] + col * CELL, ORIGIN[1] + row * CELL, CELL, CELL)

    def render(self) -> Image.Image:
        image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
        draw = ImageDraw.Draw(image)
        if self.state == "title":
            draw.text((WIDTH // 2, 70), "AGENT PLAY SIM", fill=(230, 230, 240), font=_font(26), anchor="mm")
            self._button(draw, START_RECT, "START", (40, 160, 90))
        elif self.state in ("dialog", "playing"):
            self._board(draw)
            if self.state == "dialog":
                draw.rectangle((DIALOG_RECT.x, DIALOG_RECT.y, DIALOG_RECT.right, DIALOG_RECT.bottom), fill=(60, 62, 80), outline=(240, 240, 240), width=2)
                draw.text((DIALOG_RECT.x + 16, DIALOG_RECT.y + 14), "Welcome, traveler.", fill=(255, 255, 255), font=_font(18))
                draw.text((DIALOG_RECT.x + 16, DIALOG_RECT.y + 52), "Reach the star.", fill=(220, 220, 220), font=_font(16))
                draw.text((DIALOG_RECT.x + 16, DIALOG_RECT.y + 100), "Press Enter to begin.", fill=(255, 220, 120), font=_font(16))
        elif self.state == "won":
            draw.text((WIDTH // 2, 100), "YOU WIN", fill=(255, 220, 90), font=_font(32), anchor="mm")
            draw.text((WIDTH // 2, 150), f"Moves: {self.moves}", fill=(230, 230, 240), font=_font(18), anchor="mm")
            self._button(draw, AGAIN_RECT, "PLAY AGAIN", (60, 110, 190))
        return image

    def _button(self, draw: ImageDraw.ImageDraw, rect: Rect, label: str, color: tuple[int, int, int]) -> None:
        draw.rectangle((rect.x, rect.y, rect.right, rect.bottom), fill=color, outline=(245, 245, 245), width=2)
        draw.text(rect.center, label, fill=(255, 255, 255), font=_font(18), anchor="mm")

    def _board(self, draw: ImageDraw.ImageDraw) -> None:
        draw.text((8, 8), f"Moves: {self.moves}", fill=(230, 230, 240), font=_font(16))
        draw.text((8, HEIGHT - 26), "Quest: reach the star", fill=(255, 220, 120), font=_font(16))
        for col in range(COLS + 1):
            x = ORIGIN[0] + col * CELL
            draw.line((x, ORIGIN[1], x, ORIGIN[1] + ROWS * CELL), fill=(70, 72, 90))
        for row in range(ROWS + 1):
            y = ORIGIN[1] + row * CELL
            draw.line((ORIGIN[0], y, ORIGIN[0] + COLS * CELL, y), fill=(70, 72, 90))
        for col, row in self.walls:
            self._wall(draw, self.cell_rect(col, row))
        self._star(draw, self.cell_rect(*self.goal))
        self._hero(draw, self.cell_rect(*self.player))

    @staticmethod
    def _wall(draw: ImageDraw.ImageDraw, rect: Rect) -> None:
        draw.rectangle((rect.x + 2, rect.y + 2, rect.right - 2, rect.bottom - 2), fill=(110, 110, 120))
        draw.line((rect.x + 2, rect.y + 20, rect.right - 2, rect.y + 20), fill=(80, 80, 90), width=2)

    @staticmethod
    def _star(draw: ImageDraw.ImageDraw, rect: Rect) -> None:
        cx, cy = rect.center
        points = []
        import math

        for index in range(10):
            radius = 15 if index % 2 == 0 else 6
            angle = -math.pi / 2 + index * math.pi / 5
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
        draw.polygon(points, fill=(250, 210, 60), outline=(255, 245, 200))

    @staticmethod
    def _hero(draw: ImageDraw.ImageDraw, rect: Rect) -> None:
        draw.rectangle((rect.x + 7, rect.y + 7, rect.right - 7, rect.bottom - 7), fill=(60, 120, 230), outline=(240, 240, 255), width=2)
        draw.rectangle((rect.x + 22, rect.y + 14, rect.x + 27, rect.y + 19), fill=(20, 20, 40))

    def templates(self) -> list[Template]:
        """Sprites cropped from the renderer itself, named `<role>__<name>` like a user template directory."""
        saved = (self.state, self.player, self.moves)
        try:
            self.state, self.player, self.moves = "title", self.start, 0
            title = self.render()
            self.state = "dialog"
            dialog = self.render()
            self.state = "playing"
            board = self.render()
            self.state = "won"
            won = self.render()
        finally:
            self.state, self.player, self.moves = saved
        inset = 3
        hero_cell = self.cell_rect(*self.start)
        star_cell = self.cell_rect(*self.goal)
        return [
            Template.from_image(_crop(title, START_RECT, 3), "start", "button", threshold=0.92),
            Template.from_image(_crop(board, _inset(hero_cell, inset)), "hero", "player", threshold=0.9, max_matches=1),
            Template.from_image(_crop(board, _inset(star_cell, inset)), "star", "objective", threshold=0.9, max_matches=1, interactive=False),
            Template.from_image(_crop(dialog, Rect(DIALOG_RECT.x, DIALOG_RECT.y, DIALOG_RECT.width, 44)), "welcome", "dialog", threshold=0.92, max_matches=1, interactive=False),
            Template.from_image(_crop(won, AGAIN_RECT, 3), "play again", "button", threshold=0.92),
        ]


def _inset(rect: Rect, amount: float) -> Rect:
    return Rect(rect.x + amount, rect.y + amount, rect.width - 2 * amount, rect.height - 2 * amount)


def _crop(image: Image.Image, rect: Rect, margin: int = 0) -> Image.Image:
    return image.crop((int(rect.x - margin), int(rect.y - margin), int(rect.right + margin), int(rect.bottom + margin)))


class SimBackend(DryRunBackend):
    """Records events and feeds them to the game, the way the OS would."""

    name = "sim"

    def __init__(self, game: GridGame) -> None:
        super().__init__(on_event=game.handle)
        self.game = game


class SimPerceiver:
    """Ground-truth perception from the game state, for tests that need surfaces and text."""

    name = "sim"
    fast = True

    def __init__(self, game: GridGame) -> None:
        self.game = game

    def available(self) -> bool:
        return True

    def perceive(self, frame: Frame) -> Perception:
        game = self.game
        nodes: list[SceneNode] = []
        surfaces: list[str] = []
        if game.state == "title":
            nodes.append(SceneNode("button", "START", START_RECT, "sim", native_id="start"))
        elif game.state in ("dialog", "playing"):
            nodes.append(SceneNode("hud", "moves", Rect(8, 8, 90, 20), "sim", value=f"Moves: {game.moves}", interactive=False))
            nodes.append(SceneNode("objective", "quest", Rect(8, HEIGHT - 26, 200, 20), "sim", value="Quest: reach the star", interactive=False))
            nodes.append(SceneNode("player", "hero", game.cell_rect(*game.player), "sim", native_id="hero"))
            nodes.append(SceneNode("objective", "star", game.cell_rect(*game.goal), "sim", native_id="star", interactive=False))
            for col, row in sorted(game.walls):
                nodes.append(SceneNode("obstacle", "wall", game.cell_rect(col, row), "sim", interactive=False))
            if game.state == "dialog":
                surfaces.append("dialog")
                nodes.append(SceneNode("dialog", "Welcome", DIALOG_RECT, "sim", value="Welcome, traveler. Reach the star. Press Enter to begin.", interactive=False))
        elif game.state == "won":
            nodes.append(SceneNode("text", "YOU WIN", Rect(180, 80, 120, 40), "sim", value="YOU WIN", interactive=False))
            nodes.append(SceneNode("button", "PLAY AGAIN", AGAIN_RECT, "sim", native_id="again"))
        return Perception(nodes=nodes, surfaces=surfaces, summary=f"sim state={game.state}")


def make_session(game: GridGame, root: Path | None = None, ground_truth: bool = False, extra_perceivers: list[Any] | None = None, session_id: str | None = None) -> Session:
    perceivers: list[Any] = [SimPerceiver(game)] if ground_truth else [TemplatePerceiver(game.templates())]
    perceivers += extra_perceivers or []
    policy = InteractionPolicy(headed=True, settle_ms=0, max_actions_per_minute=10_000)
    return Session(
        source=CallableFrameSource(game.render),
        perceivers=perceivers,
        backend=SimBackend(game),
        policy=policy,
        root=root,
        session_id=session_id,
        sleep=lambda _seconds: None,
    )


def path_to_goal(game: GridGame) -> list[str]:
    """Breadth-first search over the grid, used by tests and the scripted player."""
    from collections import deque

    start, goal = game.player, game.goal
    queue: deque[tuple[tuple[int, int], list[str]]] = deque([(start, [])])
    seen = {start}
    while queue:
        (col, row), path = queue.popleft()
        if (col, row) == goal:
            return path
        for key in ("right", "down", "left", "up"):
            dx, dy = MOVES[key]
            nxt = (col + dx, row + dy)
            if 0 <= nxt[0] < COLS and 0 <= nxt[1] < ROWS and nxt not in game.walls and nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, path + [key]))
    return []


Renderer = Callable[[], Image.Image]
