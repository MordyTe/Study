"""_template.server — thin MCP wrapper around ``core``.

Run over stdio:  ``python server.py``  (needs ``pip install mcp``).
The ``mcp`` import is guarded so this module can be imported and inspected
without the package; only ``main()`` / ``build_server()`` require it.
Tests must import ``core`` only, never this module.
"""
from __future__ import annotations

import sys

try:  # the MCP SDK is optional at import time
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - exercised only without the package
    FastMCP = None

try:  # imported as a package (python -m <tool>.server) ...
    from . import core
except ImportError:  # ... or run as a plain script from the tool directory
    import core  # type: ignore[no-redef]

TOOL_NAME = "_template"


def build_server():
    """Create the FastMCP server and register one MCP tool per core function."""
    if FastMCP is None:
        raise RuntimeError("the 'mcp' package is not installed: pip install mcp")
    server = FastMCP(TOOL_NAME)

    @server.tool()
    def count_words(text: str) -> dict:
        """Count whitespace-separated words in ``text``.

        Returns {"ok": true, "words": n, "characters": n} or {"ok": false, "error": code}.
        """
        return core.count_words(text)

    return server


def main() -> int:
    if FastMCP is None:
        print("the 'mcp' package is not installed: pip install mcp", file=sys.stderr)
        return 1
    build_server().run()  # stdio transport
    return 0


if __name__ == "__main__":
    sys.exit(main())
