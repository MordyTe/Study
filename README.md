# agent-play

סוכן AI שמשחק במשחקי מחשב ומפעיל אפליקציות דסקטופ. נבנה מניתוח מעמיק (reverse engineering) של
`agent-desktop` ו-`agent-browser` של Vercel Labs, ומרחיב את העיצוב שלהם למסכים שאין להם עץ נגישות:
משחקים, ממשקים מצוירים, ו-UI שמרונדר ב-GPU.

- `docs/REVERSE_ENGINEERING.md` – מה למדנו מהקוד המקורי, חוזה אחר חוזה, ואיפה הוא נעצר.
- `docs/ARCHITECTURE.md` – העיצוב של agent-play: תפיסה היברידית, refs, אימות פעולות, לולאת הסוכן.
- `docs/GAME_PLAYING.md` – איך הסוכן מבין משימה במשחק, מגבלות זמן תגובה, ואיפה זה לא מתאים.

---

**agent-play** is a computer-use agent for games and desktop applications. It keeps the contracts that
make Vercel's `agent-desktop` reliable (one JSON envelope per command, snapshot-qualified refs,
re-identification before every action, honest delivery semantics, traces) and adds what a game needs:

- **Vision-first perception.** A screenshot becomes a structured scene with refs, from three sources that
  are fused: template matching (fast, deterministic), a vision model (Claude, for anything unknown), and
  OCR. When an accessibility tree exists, `agent-desktop` is used through a bridge and wins.
- **An agent loop inside.** `agent-desktop` is a tool with no model. `agent-play` carries the
  observe-decide-act-verify loop, task understanding, a goal stack, memory, and skills per genre.
- **Game-grade input.** Keys can be held for a duration, Windows uses scancode `SendInput`, and every
  backend is swappable with a dry-run backend for tests.
- **A built-in simulator.** A tiny grid game exercises the whole pipeline offline, so the agent is tested
  end to end without an API key or a screen.

## Install

```bash
pip install -e ".[dev]"      # core, offline tests
pip install -e ".[all]"      # screen capture (mss), input (pynput), OpenCV, OCR
agent-play status
```

## Quick start

```bash
export ANTHROPIC_API_KEY=...                   # or `ant auth login`
agent-play sim play "reach the star"           # the agent plays the simulator with Claude
agent-play snapshot --compact                  # scene of the current screen with refs
agent-play click @s8f3k2p9:e3                  # act on a ref from that snapshot
agent-play run "open the inventory and equip the sword" --headed
```

Every command prints one JSON line. `--headed` enables real input; without it, actions are dry-run.

## What it cannot do

- It cannot see faster than a screenshot plus a model call. Real-time twitch gameplay needs a local
  reflex policy; the loop here is for turn-based, puzzle, strategy, adventure, and menu-driven play.
- It will not read game memory or inject into a process. Only use it on games you are allowed to automate.
- A vision detection is a hypothesis with a confidence, never a fact. The agent re-checks before it acts.

## Development

```bash
python -m pytest             # 60+ offline tests
python -m pytest -k live     # live Claude run on the simulator, skipped without a key
```

## License

Apache-2.0. The studied projects are also Apache-2.0; no code was copied from them.
