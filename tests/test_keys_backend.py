import sys

import pytest

from agent_play.actions.backend import (
    DryRunBackend,
    Win32SendInputBackend,
    default_backend,
)
from agent_play.actions.keys import KeyCombo, normalize_key, parse_combo
from agent_play.envelope import AgentPlayError, ErrorCode


def test_key_normalization_and_aliases():
    assert normalize_key("Return") == "enter" and normalize_key("ESC") == "escape"
    assert normalize_key("ArrowUp") == "up" and normalize_key("cmd") == "meta" and normalize_key("W") == "w"
    with pytest.raises(AgentPlayError) as info:
        normalize_key("hyperspace")
    assert info.value.code is ErrorCode.INVALID_ARGS


def test_parse_combo():
    assert parse_combo("ctrl+shift+s") == KeyCombo("s", ["ctrl", "shift"])
    assert parse_combo("enter") == KeyCombo("enter", [])
    assert parse_combo("ctrl++") == KeyCombo("+", ["ctrl"])
    with pytest.raises(AgentPlayError):
        parse_combo("s+ctrl")
    with pytest.raises(AgentPlayError):
        parse_combo("")


def test_dry_run_records_composite_gestures():
    backend = DryRunBackend()
    backend.click(10, 20, "left", 2)
    backend.press(parse_combo("ctrl+s"))
    backend.hold_key("w", 50)
    backend.type_text("hi\n")
    backend.drag(0, 0, 10, 10, duration_ms=32)
    kinds = [e.kind for e in backend.events]
    assert kinds[:5] == ["move", "mouse_down", "mouse_up", "mouse_down", "mouse_up"]
    assert [(e.kind, e.key) for e in backend.events[5:9]] == [("key_down", "ctrl"), ("key_down", "s"), ("key_up", "s"), ("key_up", "ctrl")]
    assert [(e.kind, e.key) for e in backend.events[9:11]] == [("key_down", "w"), ("key_up", "w")]
    typed = [e.key for e in backend.events[11:17] if e.kind == "key_down"]
    assert typed == ["h", "i", "enter"]
    assert backend.events[-1].kind == "mouse_up" and backend.events[-1].x == 10


def test_default_backend_is_dry_run_unless_headed():
    assert default_backend(headed=False).name == "dryrun"
    assert default_backend(headed=True, prefer="dryrun").name == "dryrun"
    with pytest.raises(AgentPlayError):
        default_backend(headed=True, prefer="telepathy")


@pytest.mark.skipif(sys.platform == "win32", reason="only meaningful off Windows")
def test_win32_backend_refuses_other_platforms():
    with pytest.raises(AgentPlayError) as info:
        Win32SendInputBackend()
    assert info.value.code is ErrorCode.PLATFORM_NOT_SUPPORTED
