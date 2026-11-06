"""The anti-cheat registry: which games are protected, by what, and what the agent does about it.

Pure data lookup. It exists so the agent recognizes a protected game before the first action and
refuses with an explanation; it contains nothing about avoiding detection.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Any

POLICY_RANK = {"refuse": 3, "warn": 2, "unknown": 1, "ok": 0}


@dataclass
class Assessment:
    policy: str
    game: str | None = None
    system: str | None = None
    system_name: str | None = None
    mode: str | None = None
    reason: str = ""
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"policy": self.policy, "reason": self.reason}
        if self.game:
            data["game"] = self.game
        if self.system:
            data.update({"system": self.system, "system_name": self.system_name, "mode": self.mode})
        if self.keywords:
            data["online_keywords"] = self.keywords
        return data


@lru_cache(maxsize=1)
def registry() -> dict[str, Any]:
    text = resources.files("agent_play.knowledge").joinpath("anticheat.json").read_text(encoding="utf-8")
    return json.loads(text)


def _normalize(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", text.lower()).strip() + " "


def _mentions(haystack: str, needle: str) -> bool:
    return (" " + re.sub(r"[^a-z0-9]+", " ", needle.lower()).strip() + " ") in haystack


def assess(text: str) -> Assessment:
    """Classifies a task or game name as refuse, warn, ok or unknown. The strictest match wins."""
    data = registry()
    haystack = _normalize(text)
    keywords = [word for word in data["online_keywords"] if _mentions(haystack, word)]
    best: Assessment | None = None
    for game in data["games"]:
        names = [game["name"], *game.get("aliases", [])]
        if not any(_mentions(haystack, name) for name in names):
            continue
        system_id = game.get("system")
        system = data["systems"].get(system_id, {}) if system_id else {}
        policy = game.get("policy") or ("refuse" if system.get("mode") == "kernel" or game.get("competitive") else "ok")
        candidate = Assessment(
            policy=policy,
            game=game["name"],
            system=system_id,
            system_name=system.get("name"),
            mode=system.get("mode"),
            reason=_reason(policy, game, system),
            keywords=keywords,
        )
        if best is None or POLICY_RANK[candidate.policy] > POLICY_RANK[best.policy]:
            best = candidate
    if best is not None:
        if best.policy == "ok" and keywords:
            best = Assessment("warn", best.game, best.system, best.system_name, best.mode, f"{best.game} is normally offline, but the task mentions {', '.join(keywords)}; online play may be restricted by its terms.", keywords)
        return best
    if keywords:
        return Assessment("warn", reason=f"No known game named, but the task mentions {', '.join(keywords)}; ask whether this is an online game before acting.", keywords=keywords)
    return Assessment("unknown", reason="No known game or online keyword in the task; proceed for single-player activity and ask if other players appear on screen.")


def _reason(policy: str, game: dict[str, Any], system: dict[str, Any]) -> str:
    name = game["name"]
    notes = game.get("notes") or system.get("notes") or ""
    if policy == "refuse":
        protected = f" is protected by {system['name']} ({system['mode']}-mode)" if system else " forbids automation"
        return f"{name}{protected}; synthesized input is what it detects, and the consequence is an account ban, often in a delayed ban wave. {notes}".strip()
    if policy == "warn":
        return f"{name} is online or server dependent; automation may violate its terms or a server's anti-cheat. {notes}".strip()
    return f"{name} is offline or single-player; no anti-cheat applies. {notes}".strip()


def known_games() -> list[dict[str, Any]]:
    return [dict(game) for game in registry()["games"]]


def known_systems() -> dict[str, dict[str, Any]]:
    return {key: dict(value) for key, value in registry()["systems"].items()}
