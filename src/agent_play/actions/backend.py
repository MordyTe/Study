"""Input backends. Every synthesized event goes through `InputBackend`, so tests and the simulator
replace the OS with a recorder, and a game that ignores virtual keys gets scancodes on Windows."""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

from agent_play.actions.keys import KeyCombo, normalize_key, parse_combo
from agent_play.envelope import AgentPlayError, ErrorCode


@runtime_checkable
class InputBackend(Protocol):
    name: str

    def move(self, x: float, y: float) -> None: ...

    def mouse_down(self, x: float, y: float, button: str = "left") -> None: ...

    def mouse_up(self, x: float, y: float, button: str = "left") -> None: ...

    def click(self, x: float, y: float, button: str = "left", count: int = 1) -> None: ...

    def key_down(self, key: str) -> None: ...

    def key_up(self, key: str) -> None: ...

    def press(self, combo: KeyCombo) -> None: ...

    def hold_key(self, key: str, duration_ms: int) -> None: ...

    def type_text(self, text: str) -> None: ...

    def scroll(self, x: float, y: float, dx: int, dy: int) -> None: ...

    def drag(self, x0: float, y0: float, x1: float, y1: float, duration_ms: int = 300, button: str = "left") -> None: ...


class BaseBackend:
    """Composite gestures built from the primitives a concrete backend implements."""

    name = "base"
    sleep: Callable[[float], None] = staticmethod(time.sleep)

    def click(self, x: float, y: float, button: str = "left", count: int = 1) -> None:
        self.move(x, y)
        for index in range(max(1, count)):
            self.mouse_down(x, y, button)
            self.mouse_up(x, y, button)
            if index + 1 < count:
                self.sleep(0.06)

    def press(self, combo: KeyCombo) -> None:
        for modifier in combo.modifiers:
            self.key_down(modifier)
        self.key_down(combo.key)
        self.key_up(combo.key)
        for modifier in reversed(combo.modifiers):
            self.key_up(modifier)

    def hold_key(self, key: str, duration_ms: int) -> None:
        name = normalize_key(key)
        self.key_down(name)
        try:
            self.sleep(max(0, duration_ms) / 1000.0)
        finally:
            self.key_up(name)

    def type_text(self, text: str) -> None:
        for char in text:
            if char == "\n":
                self.press(KeyCombo("enter"))
                continue
            key = " " if char == " " else char
            self.key_down(key)
            self.key_up(key)

    def drag(self, x0: float, y0: float, x1: float, y1: float, duration_ms: int = 300, button: str = "left") -> None:
        steps = max(2, int(duration_ms / 16))
        self.move(x0, y0)
        self.mouse_down(x0, y0, button)
        for step in range(1, steps + 1):
            t = step / steps
            self.move(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
            self.sleep(duration_ms / 1000.0 / steps)
        self.mouse_up(x1, y1, button)

    def move(self, x: float, y: float) -> None:
        raise NotImplementedError

    def mouse_down(self, x: float, y: float, button: str = "left") -> None:
        raise NotImplementedError

    def mouse_up(self, x: float, y: float, button: str = "left") -> None:
        raise NotImplementedError

    def key_down(self, key: str) -> None:
        raise NotImplementedError

    def key_up(self, key: str) -> None:
        raise NotImplementedError

    def scroll(self, x: float, y: float, dx: int, dy: int) -> None:
        raise NotImplementedError


@dataclass
class InputEvent:
    kind: str
    x: float | None = None
    y: float | None = None
    key: str | None = None
    button: str | None = None
    dx: int = 0
    dy: int = 0
    at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind}
        for name in ("x", "y", "key", "button"):
            value = getattr(self, name)
            if value is not None:
                data[name] = value
        if self.dx or self.dy:
            data["dx"], data["dy"] = self.dx, self.dy
        return data


class DryRunBackend(BaseBackend):
    """Records every event instead of sending it. The default when no real backend is chosen."""

    name = "dryrun"
    sleep = staticmethod(lambda seconds: None)

    def __init__(self, on_event: Callable[[InputEvent], None] | None = None) -> None:
        self.events: list[InputEvent] = []
        self.on_event = on_event

    def _emit(self, event: InputEvent) -> None:
        self.events.append(event)
        if self.on_event is not None:
            self.on_event(event)

    def move(self, x: float, y: float) -> None:
        self._emit(InputEvent("move", x, y))

    def mouse_down(self, x: float, y: float, button: str = "left") -> None:
        self._emit(InputEvent("mouse_down", x, y, button=button))

    def mouse_up(self, x: float, y: float, button: str = "left") -> None:
        self._emit(InputEvent("mouse_up", x, y, button=button))

    def key_down(self, key: str) -> None:
        self._emit(InputEvent("key_down", key=normalize_key(key)))

    def key_up(self, key: str) -> None:
        self._emit(InputEvent("key_up", key=normalize_key(key)))

    def scroll(self, x: float, y: float, dx: int, dy: int) -> None:
        self._emit(InputEvent("scroll", x, y, dx=dx, dy=dy))

    def clear(self) -> None:
        self.events.clear()


class PynputBackend(BaseBackend):
    """Cross-platform synthesized input through pynput (optional dependency)."""

    name = "pynput"

    def __init__(self) -> None:
        try:
            from pynput import keyboard, mouse
        except Exception as exc:
            raise AgentPlayError(
                ErrorCode.PLATFORM_NOT_SUPPORTED,
                "Input injection needs the optional dependency pynput and a display session",
                "pip install 'agent-play[input]'",
                {"cause": str(exc)},
            ) from exc
        self._keyboard = keyboard
        self._mouse = mouse
        self._kb = keyboard.Controller()
        self._ms = mouse.Controller()

    def _key(self, key: str) -> Any:
        name = normalize_key(key)
        if len(name) == 1:
            return name
        table = {
            "enter": self._keyboard.Key.enter,
            "escape": self._keyboard.Key.esc,
            "space": self._keyboard.Key.space,
            "tab": self._keyboard.Key.tab,
            "backspace": self._keyboard.Key.backspace,
            "delete": self._keyboard.Key.delete,
            "insert": getattr(self._keyboard.Key, "insert", None),
            "home": self._keyboard.Key.home,
            "end": self._keyboard.Key.end,
            "page_up": self._keyboard.Key.page_up,
            "page_down": self._keyboard.Key.page_down,
            "up": self._keyboard.Key.up,
            "down": self._keyboard.Key.down,
            "left": self._keyboard.Key.left,
            "right": self._keyboard.Key.right,
            "ctrl": self._keyboard.Key.ctrl,
            "alt": self._keyboard.Key.alt,
            "shift": self._keyboard.Key.shift,
            "meta": self._keyboard.Key.cmd,
            "caps_lock": self._keyboard.Key.caps_lock,
            "num_lock": getattr(self._keyboard.Key, "num_lock", None),
            "print_screen": getattr(self._keyboard.Key, "print_screen", None),
            "pause": getattr(self._keyboard.Key, "pause", None),
        }
        if name.startswith("f") and name[1:].isdigit():
            return getattr(self._keyboard.Key, name)
        resolved = table.get(name)
        if resolved is None:
            raise AgentPlayError(ErrorCode.ACTION_NOT_SUPPORTED, f"Key {key!r} is not available on this platform")
        return resolved

    def _button(self, button: str) -> Any:
        return {"left": self._mouse.Button.left, "right": self._mouse.Button.right, "middle": self._mouse.Button.middle}[button]

    def move(self, x: float, y: float) -> None:
        self._ms.position = (int(x), int(y))

    def mouse_down(self, x: float, y: float, button: str = "left") -> None:
        self._ms.position = (int(x), int(y))
        self._ms.press(self._button(button))

    def mouse_up(self, x: float, y: float, button: str = "left") -> None:
        self._ms.release(self._button(button))

    def key_down(self, key: str) -> None:
        self._kb.press(self._key(key))

    def key_up(self, key: str) -> None:
        self._kb.release(self._key(key))

    def scroll(self, x: float, y: float, dx: int, dy: int) -> None:
        self._ms.position = (int(x), int(y))
        self._ms.scroll(dx, dy)


SCANCODES = {
    "escape": 0x01, "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06, "6": 0x07, "7": 0x08, "8": 0x09,
    "9": 0x0A, "0": 0x0B, "-": 0x0C, "=": 0x0D, "backspace": 0x0E, "tab": 0x0F, "q": 0x10, "w": 0x11,
    "e": 0x12, "r": 0x13, "t": 0x14, "y": 0x15, "u": 0x16, "i": 0x17, "o": 0x18, "p": 0x19, "[": 0x1A,
    "]": 0x1B, "enter": 0x1C, "ctrl": 0x1D, "a": 0x1E, "s": 0x1F, "d": 0x20, "f": 0x21, "g": 0x22,
    "h": 0x23, "j": 0x24, "k": 0x25, "l": 0x26, ";": 0x27, "'": 0x28, "`": 0x29, "shift": 0x2A,
    "\\": 0x2B, "z": 0x2C, "x": 0x2D, "c": 0x2E, "v": 0x2F, "b": 0x30, "n": 0x31, "m": 0x32, ",": 0x33,
    ".": 0x34, "/": 0x35, "alt": 0x38, "space": 0x39, "caps_lock": 0x3A, "f1": 0x3B, "f2": 0x3C,
    "f3": 0x3D, "f4": 0x3E, "f5": 0x3F, "f6": 0x40, "f7": 0x41, "f8": 0x42, "f9": 0x43, "f10": 0x44,
    "num_lock": 0x45, "f11": 0x57, "f12": 0x58,
}
EXTENDED_SCANCODES = {
    "up": 0x48, "left": 0x4B, "right": 0x4D, "down": 0x50, "home": 0x47, "end": 0x4F, "page_up": 0x49,
    "page_down": 0x51, "insert": 0x52, "delete": 0x53, "meta": 0x5B,
}


class Win32SendInputBackend(BaseBackend):
    """Windows SendInput with hardware scancodes (KEYEVENTF_SCANCODE), which DirectInput games read."""

    name = "win32"

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise AgentPlayError(ErrorCode.PLATFORM_NOT_SUPPORTED, "The win32 backend only runs on Windows")
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._screen = (self._user32.GetSystemMetrics(0), self._user32.GetSystemMetrics(1))

        ULONG_PTR = ctypes.c_size_t

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

        class _INPUTUNION(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]

        class INPUT(ctypes.Structure):
            _anonymous_ = ("u",)
            _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

        self._INPUT, self._MOUSEINPUT, self._KEYBDINPUT = INPUT, MOUSEINPUT, KEYBDINPUT

    def _send(self, inp: Any) -> None:
        sent = self._user32.SendInput(1, self._ctypes.byref(inp), self._ctypes.sizeof(inp))
        if sent != 1:
            raise AgentPlayError(ErrorCode.ACTION_FAILED, "SendInput rejected the event", details={"last_error": self._ctypes.get_last_error()})

    def _key_event(self, key: str, up: bool) -> None:
        name = normalize_key(key)
        flags = 0x0008  # KEYEVENTF_SCANCODE
        if name in EXTENDED_SCANCODES:
            scan, flags = EXTENDED_SCANCODES[name], flags | 0x0001  # KEYEVENTF_EXTENDEDKEY
        elif name in SCANCODES:
            scan = SCANCODES[name]
        else:
            raise AgentPlayError(ErrorCode.ACTION_NOT_SUPPORTED, f"No scancode for key {key!r}")
        if up:
            flags |= 0x0002  # KEYEVENTF_KEYUP
        inp = self._INPUT(type=1)
        inp.ki = self._KEYBDINPUT(0, scan, flags, 0, 0)
        self._send(inp)

    def _mouse_event(self, flags: int, x: float | None = None, y: float | None = None, data: int = 0) -> None:
        inp = self._INPUT(type=0)
        dx = dy = 0
        if x is not None and y is not None:
            dx = int(x * 65535 / max(1, self._screen[0] - 1))
            dy = int(y * 65535 / max(1, self._screen[1] - 1))
            flags |= 0x8000 | 0x0001  # MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE
        inp.mi = self._MOUSEINPUT(dx, dy, data, flags, 0, 0)
        self._send(inp)

    def move(self, x: float, y: float) -> None:
        self._mouse_event(0, x, y)

    def mouse_down(self, x: float, y: float, button: str = "left") -> None:
        self._mouse_event({"left": 0x0002, "right": 0x0008, "middle": 0x0020}[button], x, y)

    def mouse_up(self, x: float, y: float, button: str = "left") -> None:
        self._mouse_event({"left": 0x0004, "right": 0x0010, "middle": 0x0040}[button], x, y)

    def key_down(self, key: str) -> None:
        self._key_event(key, up=False)

    def key_up(self, key: str) -> None:
        self._key_event(key, up=True)

    def scroll(self, x: float, y: float, dx: int, dy: int) -> None:
        self.move(x, y)
        if dy:
            self._mouse_event(0x0800, data=int(dy * 120))  # MOUSEEVENTF_WHEEL
        if dx:
            self._mouse_event(0x1000, data=int(dx * 120))  # MOUSEEVENTF_HWHEEL


def default_backend(headed: bool, prefer: str | None = None) -> BaseBackend:
    """Dry-run unless headed. `AGENT_PLAY_INPUT` or `prefer` chooses `pynput` or `win32`."""
    if not headed:
        return DryRunBackend()
    choice = (prefer or os.environ.get("AGENT_PLAY_INPUT") or ("win32" if sys.platform == "win32" else "pynput")).lower()
    if choice == "dryrun":
        return DryRunBackend()
    if choice == "win32":
        return Win32SendInputBackend()
    if choice == "pynput":
        return PynputBackend()
    raise AgentPlayError(ErrorCode.INVALID_ARGS, f"Unknown input backend {choice!r}", "Use dryrun, pynput or win32")


def parse_key_for_backend(combo: str) -> KeyCombo:
    return parse_combo(combo)
