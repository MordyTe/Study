"""Thin MCP wrapper around ``core``.

The ``mcp`` package is optional: importing this module never fails without it,
so the offline test-suite can import ``server`` and exercise the tool
functions directly. Run ``python server.py`` (with ``mcp`` installed) to serve
over stdio.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402

try:  # guarded import - the package may be absent in test / CI environments
    from mcp.server.fastmcp import FastMCP  # type: ignore
    MCP_AVAILABLE = True
except Exception:  # pragma: no cover - depends on the environment
    FastMCP = None  # type: ignore
    MCP_AVAILABLE = False

SERVER_NAME = "il_open_data"


def search_datasets(query: str, limit: int = 10) -> dict:
    """Search data.gov.il datasets (CKAN package_search). Hebrew OK."""
    return core.search_datasets(query, limit)


def get_dataset(dataset_id: str) -> dict:
    """Get one data.gov.il dataset with its resources (CKAN package_show)."""
    return core.get_dataset(dataset_id)


def search_records(resource_id: str, query: str = "", limit: int = 20) -> dict:
    """Search rows of a DataStore resource (CKAN datastore_search)."""
    return core.search_records(resource_id, query, limit)


TOOLS = (search_datasets, get_dataset, search_records)


def build_server():
    """Create the FastMCP server, or return None when ``mcp`` is missing."""
    if not MCP_AVAILABLE:
        return None
    server = FastMCP(SERVER_NAME)
    for fn in TOOLS:
        server.tool()(fn)
    return server


def main() -> int:
    server = build_server()
    if server is None:
        sys.stderr.write("il_open_data: the 'mcp' package is not installed; "
                         "install it to run the MCP server (core still works).\n")
        return 1
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
