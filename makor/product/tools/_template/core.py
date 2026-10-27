"""_template.core — pure functions for the tool. Stdlib only, no network, no I/O.

Contract (shared by every Makor tool):
* every public function returns a dict and never raises;
* success  -> {"ok": True, ...fields}
* failure  -> {"ok": False, "error": <code>, "message": <human text>, ...fields}
* "" (empty input) -> ok=True with an empty result;
* None / non-str     -> {"ok": False, "error": "invalid_input"}
* len(text) > MAX_INPUT_CHARS -> {"ok": False, "error": "input_too_large"}
"""
from __future__ import annotations

import functools

MAX_INPUT_CHARS = 100_000

# --------------------------------------------------------------------------- helpers


def ok(**fields) -> dict:
    """Build a success result."""
    result = {"ok": True}
    result.update(fields)
    return result


def err(code: str, message: str, **fields) -> dict:
    """Build a failure result with a stable machine-readable ``error`` code."""
    result = {"ok": False, "error": code, "message": message}
    result.update(fields)
    return result


def check_text(text) -> dict | None:
    """Return an error dict if ``text`` is not acceptable input, otherwise None."""
    if not isinstance(text, str):
        return err("invalid_input", f"expected str, got {type(text).__name__}")
    if len(text) > MAX_INPUT_CHARS:
        return err(
            "input_too_large",
            f"input has {len(text)} characters; the limit is {MAX_INPUT_CHARS}",
            limit=MAX_INPUT_CHARS,
        )
    return None


def never_raises(fn):
    """Last line of defence: turn an unexpected exception into an error result."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - the contract is "no exceptions"
            return err("internal_error", f"{type(exc).__name__}: {exc}")

    return wrapper


# --------------------------------------------------------------------------- public API


@never_raises
def count_words(text: str) -> dict:
    """Example function: count whitespace-separated words.

    Replace this with the real functions of your tool; keep the shape.
    """
    bad = check_text(text)
    if bad:
        return bad
    words = text.split()
    return ok(words=len(words), characters=len(text))
