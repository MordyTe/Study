"""Adapt to whatever game is in the window: pick the genre skill from the first observation.

The vision perceiver already describes any screen generically. This adds one step on top: read
that first scene and choose which genre skill to load, so the agent tunes itself to the game
without the user naming it. Heuristic and transparent: it says why it chose what it chose.
"""

from __future__ import annotations

from agent_play.scene.snapshot import Snapshot

GENRES = {
    "genres/action_adventure": {"player", "enemy", "npc", "projectile", "door", "portal"},
    "genres/turn_based": {"unit", "card"},
    "genres/puzzle": {"tile"},
    "genres/menus": {"button", "menu_item", "tab", "checkbox", "text_field", "list_item"},
}
SUMMARY_HINTS = {
    "genres/puzzle": ("puzzle", "grid", "board", "match", "tiles", "sudoku"),
    "genres/turn_based": ("turn", "strategy", "card", "deck", "units", "chess"),
    "genres/action_adventure": ("platform", "adventure", "dungeon", "rpg", "explore", "combat", "overworld"),
    "genres/menus": ("menu", "settings", "launcher", "inventory", "title screen", "main menu"),
}


def pick_genre(snapshot: Snapshot) -> tuple[str | None, str]:
    """Return (genre_skill, human reason). None means the core skill alone fits."""
    roles = {node.role for node in snapshot.nodes()}
    summary = (snapshot.summary or "").lower()

    for genre, words in SUMMARY_HINTS.items():
        hit = next((w for w in words if w in summary), None)
        if hit:
            return genre, f'the scene reads as "{hit}"'

    scored: list[tuple[int, str]] = []
    for genre, markers in GENRES.items():
        overlap = roles & markers
        if overlap:
            scored.append((len(overlap), genre))
    if scored:
        scored.sort(reverse=True)
        genre = scored[0][1]
        shared = sorted(roles & GENRES[genre])
        return genre, "detected " + ", ".join(shared)

    return None, "no strong genre signal; using the core skill only"
