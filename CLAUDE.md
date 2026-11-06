# Working in this repository

`agent-play` is a computer-use agent that plays games and operates desktop apps. It is built from a
source study of Vercel Labs' `agent-desktop` and `agent-browser` (`docs/REVERSE_ENGINEERING.md`) and
extends their design to screens that expose no accessibility tree (`docs/ARCHITECTURE.md`).

The previous project in this repository lives untouched under `bybit-pattern-scanner/`.

## Commands

```bash
pip install -e ".[dev]"          # core + tests (no screen capture or input injection)
pip install -e ".[all]"          # adds mss, pynput, opencv, OCR
python -m pytest                 # full test suite, offline, no API key needed
python -m pytest -k live         # live Claude test, skipped without ANTHROPIC_API_KEY
agent-play status                # what this machine can do
agent-play sim play "reach the star"   # watch the agent play the built-in simulator
```

## Invariants

| Invariant | Where enforced |
|---|---|
| Every command prints one JSON envelope (`version`, `ok`, `command`, `data` or `error`) | `envelope.py`, `tests/test_envelope.py` |
| Refs are qualified (`@s<id>:e<N>`) and valid for one snapshot | `scene/refs.py`, `tests/test_refs.py` |
| An action re-identifies its target before it acts; a missing or changed target is `STALE_REF`, never a blind click | `actions/executor.py`, `tests/test_executor.py` |
| Every action result carries `disposition.delivery` and `disposition.retry`; only `not_delivered` is `safe` | `envelope.py`, `actions/executor.py` |
| `delivered_verified` requires a fresh observation that shows the expected change | `actions/executor.py` |
| Vision nodes are hypotheses: they carry `confidence` and `source`, and fusion never silently overwrites a higher-priority source | `perception/fusion.py` |
| The agent loop observes after every action; it never reasons from a stale frame | `agent/loop.py`, `tests/test_agent_loop.py` |
| Input injection is behind `InputBackend`; tests use `DryRunBackend` or the simulator | `actions/backend.py` |
| The simulator and the real pipeline share the same code path | `sim/`, `tests/test_sim_end_to_end.py` |

## Safety and honesty rules

- Never read game memory, inject into a game process, or bypass anti-cheat. Screen in, input out, nothing else.
- Only automate games and apps the user is allowed to automate. Online competitive games with anti-cheat are out of scope; say so instead of working around it.
- Never report success without a verifying observation. `delivered_unverified` is a valid and common result.
- Never claim a detection is certain. Confidence comes from the perceiver and is shown as-is.
- Dry-run is the default when no input backend is configured. Real input requires an explicit choice.
- Traces redact text values by default. Screenshots are stored only when asked.

## Style

Python 3.11+, type hints everywhere, dataclasses for data, `Protocol` for seams. Comments explain why,
not what. One concept per module. Optional dependencies are imported lazily inside the function that
needs them and reported through `agent-play status`, never at import time.
