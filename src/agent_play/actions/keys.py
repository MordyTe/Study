"""One key vocabulary for every backend: `enter`, `escape`, `space`, `up`, `w`, `ctrl+shift+s`."""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_play.envelope import AgentPlayError, ErrorCode

MODIFIERS = ("ctrl", "alt", "shift", "meta")

ALIASES = {
    "return": "enter",
    "esc": "escape",
    "control": "ctrl",
    "ctl": "ctrl",
    "cmd": "meta",
    "command": "meta",
    "win": "meta",
    "super": "meta",
    "option": "alt",
    "del": "delete",
    "ins": "insert",
    "pgup": "page_up",
    "pageup": "page_up",
    "pgdn": "page_down",
    "pagedown": "page_down",
    "arrowup": "up",
    "arrowdown": "down",
    "arrowleft": "left",
    "arrowright": "right",
    "spacebar": "space",
    " ": "space",
    "backspace": "backspace",
    "caps": "caps_lock",
    "capslock": "caps_lock",
}

SPECIAL_KEYS = {
    "enter", "escape", "space", "tab", "backspace", "delete", "insert", "home", "end", "page_up",
    "page_down", "up", "down", "left", "right", "caps_lock", "num_lock", "print_screen", "pause",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
}


def normalize_key(key: str) -> str:
    token = key.strip().lower()
    token = ALIASES.get(token, token)
    if len(token) == 1 or token in SPECIAL_KEYS or token in MODIFIERS:
        return token
    raise AgentPlayError(
        ErrorCode.INVALID_ARGS,
        f"Unknown key {key!r}",
        "Use a single character, a modifier (ctrl, alt, shift, meta) or a named key such as enter, escape, space, up, f1.",
        {"key": key},
    )


@dataclass
class KeyCombo:
    key: str
    modifiers: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return "+".join([*self.modifiers, self.key])


def parse_combo(combo: str) -> KeyCombo:
    if not combo or not combo.strip():
        raise AgentPlayError(ErrorCode.INVALID_ARGS, "Empty key combo")
    raw = combo.strip()
    if raw == "+":
        return KeyCombo(key="+")
    parts = [p for p in raw.split("+")] if raw.count("+") else [raw]
    if raw.endswith("+") and raw.count("+") >= 2:
        parts = raw[:-1].split("+") + ["+"]
    tokens = [normalize_key(part) for part in parts if part != "" or part == "+"]
    if not tokens:
        raise AgentPlayError(ErrorCode.INVALID_ARGS, f"Invalid key combo {combo!r}")
    modifiers = [t for t in tokens[:-1]]
    for modifier in modifiers:
        if modifier not in MODIFIERS:
            raise AgentPlayError(
                ErrorCode.INVALID_ARGS,
                f"{modifier!r} is not a modifier in combo {combo!r}",
                "Write modifiers first, then one key: ctrl+shift+s",
            )
    return KeyCombo(key=tokens[-1], modifiers=modifiers)
