"""Live narration of the agent loop: the scrolling 'cockpit' terminal you see beside the game.

It turns the observe-decide-act-verify loop into readable lines as it happens:
  [screen] 480x360 captured
  [detect] player "hero" @(80,70) · objective "star" @(320,230) · 2 obstacles
  [think]  step 4: press right
  [act]    press right
  [verify] ✓ delivered_verified — player moved (100,90)→(140,90)

It only formats what the loop already produces. It changes nothing the agent does.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, TextIO

from agent_play.scene.snapshot import Snapshot

_COLORS = {
    "screen": "36",   # cyan
    "detect": "34",   # blue
    "think": "33",    # yellow
    "act": "35",      # magenta
    "verify": "32",   # green
    "error": "31",    # red
    "meta": "90",     # grey
}
ROLE_ICON = {
    "player": "@", "enemy": "!", "npc": "&", "item": "*", "objective": "★", "button": "▸",
    "dialog": "▢", "obstacle": "#", "door": "▯", "text": "·", "hud": "▤",
}


class LiveNarrator:
    """Prints the loop as a live terminal feed. Stateless except for timing and a step counter."""

    def __init__(self, stream: TextIO | None = None, color: bool | None = None, delay_ms: int = 0) -> None:
        self.out = stream or sys.stderr
        self.color = (color if color is not None else self.out.isatty()) and not os.environ.get("NO_COLOR")
        self.delay = delay_ms / 1000.0
        self.started = time.monotonic()

    def _c(self, tag: str, text: str) -> str:
        if not self.color:
            return text
        return f"\033[{_COLORS.get(tag, '0')}m{text}\033[0m"

    def _line(self, tag: str, body: str) -> None:
        clock = time.monotonic() - self.started
        stamp = self._c("meta", f"{clock:6.1f}s")
        label = self._c(tag, f"[{tag:>6}]")
        self.out.write(f"{stamp} {label} {body}\n")
        self.out.flush()
        if self.delay:
            time.sleep(self.delay)

    def banner(self, task: str, target: str) -> None:
        rule = "═" * 58
        self.out.write(self._c("meta", rule) + "\n")
        self.out.write(self._c("think", f"  AGENT-PLAY  ·  playing: {target}") + "\n")
        self.out.write(self._c("meta", f"  task: {task}") + "\n")
        self.out.write(self._c("meta", rule) + "\n")
        self.out.flush()

    def observe(self, snapshot: Snapshot) -> None:
        w, h = snapshot.screen
        self._line("screen", f"{w}x{h} captured  ·  {snapshot.ref_count()} refs  ·  src={'+'.join(snapshot.sources) or 'none'}")
        self._line("detect", self._detect_summary(snapshot))
        if snapshot.surfaces:
            self._line("detect", "surface open: " + ", ".join(snapshot.surfaces))

    def _detect_summary(self, snapshot: Snapshot) -> str:
        key_roles = ("player", "enemy", "npc", "objective", "button", "dialog", "door", "item")
        parts: list[str] = []
        counts: dict[str, int] = {}
        for node in snapshot.nodes():
            if node.bounds is None:
                continue
            if node.role in key_roles:
                icon = ROLE_ICON.get(node.role, "·")
                cx, cy = node.bounds.center
                name = f' "{node.name}"' if node.name else ""
                parts.append(f"{icon} {node.role}{name} @({int(cx)},{int(cy)})")
            else:
                counts[node.role] = counts.get(node.role, 0) + 1
        for role, n in sorted(counts.items()):
            if role in ("obstacle", "item", "text"):
                parts.append(f"{n} {role}{'s' if n > 1 else ''}")
        return "  ·  ".join(parts) if parts else "nothing actionable on screen"

    def think(self, step: int, text: str, tool_calls: list[Any]) -> None:
        if text.strip():
            self._line("think", f"step {step}: {text.strip()[:120]}")
            return
        intents = [self._intent(c.name, getattr(c, "input", {})) for c in tool_calls]
        self._line("think", f"step {step}: " + (", ".join(i for i in intents if i) or "observe"))

    @staticmethod
    def _intent(name: str, args: dict[str, Any]) -> str:
        if name == "press":
            return f"press {args.get('key', '?')}"
        if name == "hold_key":
            return f"hold {args.get('key', '?')} {args.get('duration_ms', '?')}ms"
        if name in ("click", "double_click", "right_click", "hover"):
            return f"{name} {args.get('ref_id', '?')}"
        if name == "type_text":
            return f'type "{args.get("text", "")[:24]}"'
        if name == "set_objectives":
            return "plan objectives"
        if name == "done":
            return f"done ({'win' if args.get('success') else 'stop'})"
        return name

    def act(self, name: str, outcome_json: str, is_error: bool) -> None:
        try:
            payload = json.loads(outcome_json)
        except (ValueError, TypeError):
            payload = {}
        if is_error or not payload.get("ok", True):
            err = payload.get("error", {})
            self._line("error", f"{name} → {err.get('code', 'ERROR')}: {err.get('message', '')[:80]}")
            return
        data = payload.get("data", {})
        delivery = data.get("disposition", {}).get("delivery")
        if delivery is None:
            return  # observe / wait / remember: not a physical act worth a verify line
        args = data.get("point") or data.get("ref_id") or ""
        self._line("act", f"{name} {args if isinstance(args, str) else ''}".strip())
        mark = "✓" if delivery == "delivered_verified" else ("·" if delivery == "delivered_unverified" else "✗")
        change = self._change(data.get("events", []))
        self._line("verify", f"{mark} {delivery}" + (f" — {change}" if change else ""))

    @staticmethod
    def _change(events: list[dict[str, Any]]) -> str:
        for ev in events:
            kind = ev.get("kind")
            role = ev.get("role", "")
            name = ev.get("name", "")
            label = (role + (f' "{name}"' if name else "")).strip()
            if kind == "node_moved" and ev.get("from") and ev.get("to"):
                return f"{label or 'target'} moved {tuple(ev['from'])}→{tuple(ev['to'])}"
            if kind == "node_appeared":
                return f"{label or 'something'} appeared"
            if kind == "node_disappeared":
                return f"{label or 'something'} gone"
            if kind == "surface_appeared":
                return f"{ev.get('surface', 'overlay')} opened"
        return ""

    def done(self, status: str, summary: str) -> None:
        tag = "verify" if status in ("success",) else "error" if status in ("failed", "refused", "blocked_policy") else "meta"
        rule = "─" * 58
        self.out.write(self._c("meta", rule) + "\n")
        self._line(tag, f"RUN {status.upper()} — {summary[:100]}")
        self.out.write(self._c("meta", rule) + "\n")
        self.out.flush()
