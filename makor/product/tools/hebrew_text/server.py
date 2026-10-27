"""hebrew_text.server — thin MCP wrapper around ``core``.

Run over stdio:  ``python server.py``  (needs ``pip install mcp``).
The ``mcp`` import is guarded so this module can be imported without the package;
only ``main()`` / ``build_server()`` require it. Tests import ``core`` only.
"""
from __future__ import annotations

import sys

try:  # the MCP SDK is optional at import time
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - exercised only without the package
    FastMCP = None

try:  # imported as a package (python -m hebrew_text.server) ...
    from . import core
except ImportError:  # ... or run as a plain script from the tool directory
    import core  # type: ignore[no-redef]

TOOL_NAME = "hebrew_text"


def build_server():
    """Create the FastMCP server and register one MCP tool per core function."""
    if FastMCP is None:
        raise RuntimeError("the 'mcp' package is not installed: pip install mcp")
    server = FastMCP(TOOL_NAME)

    @server.tool()
    def normalize(text: str) -> dict:
        """Normalize Hebrew text: strip niqqud and cantillation marks, remove directional
        marks, unify Hebrew geresh/gershayim and curly quotes to ASCII ' and ", collapse
        repeated whitespace. Returns {"ok": true, "text": str} or {"ok": false, "error": code}.
        """
        return core.normalize(text)

    @server.tool()
    def parse_hebrew_date(text: str) -> dict:
        """Parse a Hebrew date such as "כ״ג בתשרי תשפ״ו" into its parts.
        Returns {"ok": true, "day": 23, "month": "תשרי", "month_index": 1, "month_en": "Tishrei",
        "year": 5786, "leap_year": false}; year is null when absent. Adar I/II supported.
        No Gregorian conversion. Errors: invalid_date, invalid_input, input_too_large.
        """
        return core.parse_hebrew_date(text)

    @server.tool()
    def gematria(text: str) -> dict:
        """Standard gematria (mispar hechrechi) of the Hebrew letters in text; final letters
        equal regular ones. Returns {"ok": true, "value": int, "letters": int, "ignored": [chars]}
        where ignored lists non-Hebrew characters that were skipped.
        """
        return core.gematria(text)

    return server


def main() -> int:
    if FastMCP is None:
        print("the 'mcp' package is not installed: pip install mcp", file=sys.stderr)
        return 1
    build_server().run()  # stdio transport
    return 0


if __name__ == "__main__":
    sys.exit(main())
