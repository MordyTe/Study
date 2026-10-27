# Creating a new tool from `_template`

Every Makor tool lives in `product/tools/<name>/` with exactly this layout:

```
<name>/
  __init__.py        # keep (makes test module names unique across tools)
  core.py            # pure functions: dict in, dict out, never raise, no I/O, no network
  server.py          # thin MCP wrapper: one @server.tool() per core function
  README.md          # English first, then Hebrew (same sections)
  tests/
    __init__.py      # keep
    test_core.py     # pytest; imports core only (`from .. import core`), never server
```

## Steps

1. `cp -r product/tools/_template product/tools/<name>` and delete `TEMPLATE_GUIDE.md` from the copy.
2. `core.py`: replace `count_words` with your functions. Keep the helpers (`ok`, `err`, `check_text`, `never_raises`)
   and the contract: `{"ok": true, ...}` / `{"ok": false, "error": <code>, "message": ...}`; `""` -> ok with an empty
   result; `None`/non-str -> `invalid_input`; > `MAX_INPUT_CHARS` (100,000) -> `input_too_large`; nothing ever raises.
3. `server.py`: set `TOOL_NAME`, and register one tool per core function with a docstring that says what it returns.
   Keep both guarded imports (`mcp` and `core`) exactly as they are.
4. `tests/test_core.py`: at least one test per function plus the contract tests (empty, None, too large).
   No network, no fixtures fetched at test time — if the tool talks to an API, record fixtures to `tests/fixtures/`
   and note the source URL and capture date in the README.
5. `README.md`: fill both halves — what it does (one sentence), install, tools + parameters, example call and output,
   limits and sources. Write every assumption you made where the spec was unclear.
6. Run: `python -m pytest -q product/tools/<name>/tests` from the repo root. Exit code 0 is the proof `verify` checks.

Allowed dependencies: Python stdlib + `mcp` only. Do not scrape sources that forbid it (robots.txt / ToS).
