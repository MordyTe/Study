"""Bridge to Vercel's agent-desktop CLI for apps that expose an accessibility tree.

When the binary is installed, its snapshot becomes `source="a11y"` nodes that win in fusion, and its
qualified ref is kept in `native_id` so the executor can delegate a click to the semantic path instead
of synthesizing input. When it is absent, the perceiver reports `available() == False`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from agent_play.envelope import AgentPlayError, ErrorCode
from agent_play.perception.base import Perception
from agent_play.perception.capture import Frame
from agent_play.scene.node import Rect, SceneNode

ROLE_MAP = {
    "textfield": "text_field",
    "menuitem": "menu_item",
    "menubutton": "button",
    "statictext": "text",
    "radiobutton": "radio_button",
    "scrollarea": "region",
    "scrollbar": "scroll_bar",
    "listbox": "list_item",
    "treeitem": "tree_item",
    "tablist": "group",
    "tabpanel": "region",
    "webarea": "region",
    "alertdialog": "dialog",
    "sheet": "dialog",
    "popover": "dialog",
    "progressbar": "progress_bar",
    "switch": "switch",
}


class AccessibilityBridge:
    def __init__(self, binary: str = "agent-desktop", timeout_s: float = 20.0, session: str | None = None) -> None:
        self.binary = binary
        self.timeout_s = timeout_s
        self.session = session

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def run(self, *args: str) -> dict[str, Any]:
        if not self.available():
            raise AgentPlayError(ErrorCode.PLATFORM_NOT_SUPPORTED, f"{self.binary} is not installed", "npm install -g agent-desktop")
        command = [self.binary, *args]
        env = None
        if self.session:
            import os

            env = {**os.environ, "AGENT_DESKTOP_SESSION": self.session}
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout_s, env=env, check=False)
        except subprocess.TimeoutExpired as exc:
            raise AgentPlayError(ErrorCode.TIMEOUT, f"{self.binary} did not answer within {self.timeout_s}s", details={"args": list(args)}) from exc
        line = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""
        try:
            envelope = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AgentPlayError(ErrorCode.INTERNAL, f"{self.binary} printed no JSON envelope", details={"stderr": completed.stderr[-500:]}) from exc
        return envelope

    def click(self, native_ref: str, headed: bool = False) -> dict[str, Any]:
        args = ["--headed", "click", native_ref] if headed else ["click", native_ref]
        return self.run(*args)


class AccessibilityPerceiver:
    name = "a11y"
    fast = True

    def __init__(self, bridge: AccessibilityBridge | None = None, app: str | None = None, interactive_only: bool = False, skeleton: bool = False) -> None:
        self.bridge = bridge or AccessibilityBridge()
        self.app = app
        self.interactive_only = interactive_only
        self.skeleton = skeleton

    def available(self) -> bool:
        return self.bridge.available()

    def perceive(self, frame: Frame) -> Perception:
        args = ["snapshot", "--compact"]
        if self.interactive_only:
            args.append("-i")
        if self.skeleton:
            args.append("--skeleton")
        if self.app:
            args += ["--app", self.app]
        envelope = self.bridge.run(*args)
        if not envelope.get("ok"):
            error = envelope.get("error", {})
            raise AgentPlayError(
                ErrorCode.PERCEPTION_FAILED,
                f"agent-desktop snapshot failed: {error.get('message', 'unknown error')}",
                error.get("suggestion"),
                {"agent_desktop_code": error.get("code")},
            )
        data = envelope.get("data", {})
        tree = data.get("tree")
        roots = [convert_node(tree, frame.origin)] if isinstance(tree, dict) else [convert_node(n, frame.origin) for n in tree or []]
        return Perception(nodes=roots, complete=bool(data.get("complete", True)))


def convert_node(data: dict[str, Any], origin: tuple[int, int] = (0, 0)) -> SceneNode:
    role_token = str(data.get("role", "unknown")).lower()
    role = ROLE_MAP.get(role_token, role_token)
    bounds = None
    if isinstance(data.get("bounds"), dict):
        b = data["bounds"]
        bounds = Rect(float(b["x"]) - origin[0], float(b["y"]) - origin[1], float(b["width"]), float(b["height"]))
    native = data.get("ref_id")
    if native is None and isinstance(data.get("native_id"), dict):
        native = f"{data['native_id'].get('kind')}:{data['native_id'].get('value')}"
    return SceneNode(
        role=role,
        name=data.get("name"),
        description=data.get("description"),
        value=data.get("value"),
        bounds=bounds,
        source="a11y",
        confidence=1.0,
        states=[str(s) for s in data.get("states", [])],
        native_id=native,
        interactive=bool(data.get("ref_id")) or None,
        children=[convert_node(child, origin) for child in data.get("children", [])],
        children_count=data.get("children_count"),
    )
