"""Shared test plumbing. NO TEST IN THIS DIRECTORY MAY TOUCH THE NETWORK.

Two layers of protection:
1. ``no_network`` (autouse) replaces ``urllib.request.urlopen`` with a function
   that raises, so even a test that forgets to mock ``fetch_json`` cannot reach
   the wire.
2. ``fixture_fetch`` builds a fake ``fetch_json`` that serves files from
   ``tests/fixtures/`` (parsed with ``json.loads`` exactly like the real one, so
   a broken fixture raises ``json.JSONDecodeError`` just as a broken body would).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

import pytest

TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TOOL_DIR not in sys.path:
    sys.path.insert(0, TOOL_DIR)

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


class NetworkCallAttempted(AssertionError):
    """Raised if anything tries to open a real socket through urllib."""


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise NetworkCallAttempted("urllib.request.urlopen was called inside a test")
    monkeypatch.setattr(urllib.request, "urlopen", _blocked)
    yield


def load_fixture(name: str):
    with open(os.path.join(FIXTURES_DIR, name), "r", encoding="utf-8") as fh:
        return json.loads(fh.read())


@pytest.fixture
def fixture_fetch(monkeypatch):
    """Return ``install(fixture_name)``: patches ``core.fetch_json`` to serve that
    fixture and returns a list that records every URL requested."""
    import core

    def install(name: str):
        calls = []

        def fake_fetch_json(url: str):
            calls.append(url)
            return load_fixture(name)

        monkeypatch.setattr(core, "fetch_json", fake_fetch_json)
        return calls

    return install
