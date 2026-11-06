# Playing games: how the agent understands what to do

## From a task to actions

1. **Read the task.** "Reach the star", "finish the tutorial quest", "equip the best sword".
2. **Observe.** One fused snapshot: template matches (known sprites), vision model nodes (dialogs, quest
   text, buttons, entities), OCR text, and, for native launchers, the accessibility tree.
3. **Decompose.** The model writes objectives with `set_objectives`: `["dismiss the welcome dialog",
   "walk to the star", "confirm the win screen"]`. They live in memory and are shown every turn.
4. **Act on refs.** `click @s..:e3`, `press right`, `hold_key w 400`. Coordinates only when no ref
   exists, and the result says so.
5. **Verify.** The executor diffs the scene after every action. The model sees the events
   (`node_moved player`, `surface_appeared dialog`) and the next frame.
6. **Remember.** `remember("the door needs the red key")`. Repeated failures become lessons automatically.
7. **Stop.** `done(success, summary)` or `ask_user(question)` when the task is ambiguous or needs a
   decision the user must make (spend currency, delete a save).

## Reading quests and objectives

- Quest logs, dialog boxes and HUD text are read by OCR when available and by the vision model always.
  Text nodes have role `text`, `dialog` or `objective` and carry the text in `value`.
- The model is told to quote the objective text it is following, so the trace shows what it believed
  the task was.

## Which games fit

| Fits well | Fits with templates | Does not fit |
|---|---|---|
| Turn-based strategy, card games, puzzles, point-and-click adventures, visual novels, menu-driven RPGs, idle games, management sims | Platformers and action-adventure at a slow pace, grid roguelikes, farming sims | Real-time shooters, rhythm games, racing, fighting games, anything online with anti-cheat |

## Input notes per platform

- **Windows games** often ignore virtual-key input. `Win32SendInputBackend` sends scancodes with
  `KEYEVENTF_SCANCODE`, which DirectInput games read. Some games need the window focused and a short
  hold (`hold_key` with 50 to 100 ms) instead of a tap.
- **macOS** needs the Accessibility permission for synthesized input (`pynput`).
- **Linux** X11 works with `pynput`; Wayland sessions refuse synthesized input without a portal.

## What it refuses to do

- Read or write game memory, hook the process, or bypass anti-cheat.
- Play online competitive games. Use it on single-player, offline, or games whose terms allow bots.
- Claim a win it did not observe.
