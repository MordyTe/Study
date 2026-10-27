"""Tests for _template.core. Import ``core`` only — never ``server`` (needs mcp)."""
import pytest

from .. import core


def test_ok_shape():
    r = core.count_words("hello world")
    assert r == {"ok": True, "words": 2, "characters": 11}


def test_empty_string_is_ok_and_empty():
    assert core.count_words("") == {"ok": True, "words": 0, "characters": 0}


@pytest.mark.parametrize("bad", [None, 5, 1.5, b"bytes", ["list"], {"k": 1}])
def test_non_str_is_invalid_input(bad):
    r = core.count_words(bad)
    assert r["ok"] is False
    assert r["error"] == "invalid_input"
    assert "message" in r


def test_input_too_large():
    r = core.count_words("x" * (core.MAX_INPUT_CHARS + 1))
    assert r["ok"] is False
    assert r["error"] == "input_too_large"
    assert r["limit"] == core.MAX_INPUT_CHARS


def test_input_at_limit_is_accepted():
    assert core.count_words("x" * core.MAX_INPUT_CHARS)["ok"] is True


def test_never_raises_wrapper():
    @core.never_raises
    def boom(_):
        raise ValueError("kaboom")

    r = boom("anything")
    assert r["ok"] is False
    assert r["error"] == "internal_error"
    assert "kaboom" in r["message"]
