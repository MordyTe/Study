"""The tools the model can call. Strict schemas: every property required, no extras."""

from __future__ import annotations

from typing import Any


def _tool(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties.keys()),
            "additionalProperties": False,
        },
    }


REF = {"type": "string", "description": "A qualified ref from the latest snapshot, such as @s8f3k2p9:e3"}

TOOLS: list[dict[str, Any]] = [
    _tool(
        "observe",
        "Take a fresh observation of the screen. 'full' runs every perceiver including the vision model; "
        "'fast' runs only cheap perceivers; 'skeleton' returns a shallow tree for dense screens. "
        "You receive a new observation after every action anyway; call this when you need a fresh full look.",
        {"detail": {"type": "string", "enum": ["full", "fast", "skeleton"]}},
    ),
    _tool("click", "Left-click the center of an element by ref.", {"ref_id": REF}),
    _tool("double_click", "Double-click an element by ref.", {"ref_id": REF}),
    _tool("right_click", "Right-click an element by ref.", {"ref_id": REF}),
    _tool("hover", "Move the pointer over an element by ref without clicking.", {"ref_id": REF}),
    _tool(
        "mouse_click",
        "Click a screen coordinate. Last resort when no ref exists for the target; say why in your text.",
        {"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string", "enum": ["left", "right", "middle"]}},
    ),
    _tool(
        "press",
        "Press and release a key or combo: enter, escape, space, up, w, f5, ctrl+s, shift+tab.",
        {"key": {"type": "string"}},
    ),
    _tool(
        "hold_key",
        "Hold a key down for a duration in milliseconds, then release. Games read held keys for movement.",
        {"key": {"type": "string"}, "duration_ms": {"type": "integer"}},
    ),
    _tool("type_text", "Type text with individual key presses into the focused field.", {"text": {"type": "string"}}),
    _tool(
        "scroll",
        "Scroll over an element by ref. amount is in wheel notches.",
        {"ref_id": REF, "direction": {"type": "string", "enum": ["up", "down", "left", "right"]}, "amount": {"type": "integer"}},
    ),
    _tool("drag", "Drag from one ref to another ref.", {"ref_id": REF, "to_ref": REF}),
    _tool(
        "wait",
        "Wait until a condition holds, up to timeout_ms. Give exactly one of: text (appears, or disappears "
        "when gone is true), ref_id (present, or gone), or stable (the screen stops changing). "
        "Leave unused string fields empty and unused booleans false. A fixed sleep is a race; wait for a signal.",
        {
            "text": {"type": "string"},
            "ref_id": {"type": "string"},
            "gone": {"type": "boolean"},
            "stable": {"type": "boolean"},
            "timeout_ms": {"type": "integer"},
        },
    ),
    _tool("remember", "Save a note to working memory for later steps (a key you found, a rule you learned).", {"note": {"type": "string"}}),
    _tool(
        "learn",
        "Save durable knowledge that must survive this run and future sessions: a game's rules, its "
        "control mapping, a fact the user taught you. It is shown to you at the start of every later run. "
        "Use remember for things that matter only now.",
        {"topic": {"type": "string"}, "text": {"type": "string"}},
    ),
    _tool(
        "set_objectives",
        "Replace the objective list that decomposes the task. Keep it short; mark progress with status.",
        {
            "objectives": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "status": {"type": "string", "enum": ["pending", "active", "done", "blocked"]},
                    },
                    "required": ["text", "status"],
                    "additionalProperties": False,
                },
            }
        },
    ),
    _tool(
        "ask_user",
        "Stop and ask the user a question when the task is ambiguous or needs a decision only they can make "
        "(spending currency, deleting a save, choosing between characters).",
        {"question": {"type": "string"}},
    ),
    _tool(
        "done",
        "Finish the run. success is true only when your latest observation shows the task is achieved. "
        "The summary states what you observed, not what you intended.",
        {"success": {"type": "boolean"}, "summary": {"type": "string"}},
    ),
]

ACTION_TOOLS = {"click", "double_click", "right_click", "hover", "mouse_click", "press", "hold_key", "type_text", "scroll", "drag"}
CONTROL_TOOLS = {"done", "ask_user"}


def tool_names() -> list[str]:
    return [tool["name"] for tool in TOOLS]
