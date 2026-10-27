"""server.py must import and work without the optional ``mcp`` package."""
from __future__ import annotations

import importlib
import sys

import pytest

import core


def test_server_imports_without_mcp(monkeypatch):
    # Make sure the guarded import takes the "missing" branch deterministically.
    monkeypatch.setitem(sys.modules, "mcp", None)
    monkeypatch.setitem(sys.modules, "mcp.server", None)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", None)
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    assert server.MCP_AVAILABLE is False
    assert server.build_server() is None
    assert server.main() == 1  # graceful exit code, no exception


def test_server_tools_delegate_to_core(monkeypatch, fixture_fetch):
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", None)
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    assert [t.__name__ for t in server.TOOLS] == ["search_datasets", "get_dataset", "search_records"]

    fixture_fetch("package_search_transport.json")
    out = server.search_datasets("תחבורה", 2)
    assert out["ok"] is True and len(out["results"]) == 2

    fixture_fetch("package_show.json")
    assert server.get_dataset("mechirmnm")["dataset"]["name"] == "mechirmnm"

    fixture_fetch("datastore_search.json")
    assert server.search_records("b7cf8f14-64a2-4b33-8d4b-edb286fdbd37", "", 3)["count"] == 23

    assert server.search_datasets("")["error"] == "invalid_input"
    assert server.core is core
