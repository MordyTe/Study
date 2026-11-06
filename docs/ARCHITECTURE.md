# Architecture

`agent-play` keeps the contracts that make `agent-desktop` reliable and adds the three things a game
needs: perception from pixels, an agent loop with a plan, and game-grade input.

```
                 ┌───────────────────────────── agent/ ─────────────────────────────┐
  task ────────▶ │ loop.py: observe ─▶ decide (Claude, strict tools) ─▶ act ─▶ verify │ ──▶ RunResult
                 │ memory.py (goal stack, notes, lessons)   trace.py (JSONL)          │
                 └───────────┬──────────────────────────────────┬──────────────────┘
                             │ Snapshot (+refs)                  │ ActionRequest
                 ┌───────────▼──────────── scene/ ───────────────▼──────────────────┐
                 │ snapshot.py  refs.py (RefStore)  node.py  diff.py                 │
                 └───────────▲──────────────────────────────────┬──────────────────┘
          ┌──────────────────┴────── perception/ ──────┐  ┌──────▼──────── actions/ ───────┐
          │ capture.py  template.py  vision_llm.py      │  │ executor.py (re-identify, gate, │
          │ ocr.py  a11y_bridge.py  fusion.py           │  │ dispatch, verify)  backend.py   │
          └──────────────────▲─────────────────────────┘  └──────┬──────────────────────────┘
                             │ pixels                             │ input events
                        ┌────┴─────────────── screen / game / sim ┴────┐
```

## Layers

### scene: the shared contract

- `SceneNode`: `role`, `name`, `bounds`, `source` (`a11y`, `template`, `vision`, `ocr`, `sim`),
  `confidence`, `states`, `value`, `description`, `native_id`, `interactive`, `children`, `ref_id`.
  The role vocabulary covers widgets (`button`, `text_field`, `menu_item`, ...) and game entities
  (`player`, `enemy`, `npc`, `item`, `hud`, `minimap`, `dialog`, `objective`, `region`).
- `Snapshot`: one observation. `snapshot_id`, roots, `screen`, `frame_hash`, `surfaces`, `complete`.
  `compact_text()` renders the agent-browser style line per node:
  `@s8f3k2p9:e3 [button] "Start" @(120,80 200x40) src=template c=0.98`.
  `skeleton(depth)` cuts deep trees and marks `children_count`, as agent-desktop does.
- `RefStore`: allocates `@<snapshot_id>:e<N>` for interactive nodes, stores a `RefEntry` (identity,
  bounds, source, confidence, `identity_unique`, a grayscale fingerprint of the element crop), persists
  per session on disk, and resolves a ref later or raises `SNAPSHOT_NOT_FOUND` / `STALE_REF`.
- `diff_snapshots()`: pure function, fixtures-tested, producing `node_appeared`, `node_disappeared`,
  `node_moved`, `value_changed`, `surface_appeared`, `surface_dismissed`. This is the evidence base for
  verification and waits, mirroring `wait/signals.rs`.

### perception: pixels to nodes

`Perceiver.perceive(frame) -> list[SceneNode]`. Providers are independent and composable:

| Provider | Cost | Use |
|---|---|---|
| `TemplatePerceiver` | ~ms, deterministic | known sprites, icons, buttons; normalized cross-correlation in numpy (OpenCV when installed); non-maximum suppression; twins allowed |
| `VisionPerceiver` | one model call | anything unknown; Claude returns a strict `report_scene` tool call with elements, boxes, roles, text, surfaces; boxes are mapped back from the downscaled image to screen pixels |
| `OcrPerceiver` | ~100 ms, optional | quest text, HUD numbers, dialogs; absent dependency means `available() == False`, never an import error |
| `AccessibilityPerceiver` | one `agent-desktop` process | native apps; the bridge maps agent-desktop's tree to `SceneNode` and keeps its qualified ref in `native_id` so actions can be delegated semantically |

`fuse()` merges provider outputs. Two nodes from different sources that overlap (IoU above threshold)
with compatible roles become one node: identity comes from the highest-priority source
(`a11y > template > ocr > vision`), confidence is the maximum, and `corroborated_by` lists the others.
A lower-priority source never overwrites a name a higher one supplied.

`Session.observe()` runs the full set; `Session.observe_fast()` runs only cheap providers for
re-identification. When only the vision model is configured, re-identification falls back to the
fingerprint check, so acting never silently skips the check.

### actions: act only on evidence

`ActionExecutor.execute(request)`:

1. **Policy.** Dry-run unless `headed`; action allowed; rate limit.
2. **Resolve.** Parse and load the ref. Missing snapshot: `SNAPSHOT_NOT_FOUND`.
3. **Re-identify.** Fresh fast observation. Candidates share the entry's identity key. Zero: `STALE_REF`
   (`details.kind: saved_ref_absent`). Several: pick the one whose bounds overlap the stored bounds; if
   none overlaps: `AMBIGUOUS_TARGET` (`identity_not_unique`). No fast perceiver: compare the stored
   fingerprint with the same region of a fresh frame; below threshold: `STALE_REF`
   (`fingerprint_mismatch`).
4. **Gate.** On screen, enabled, stable (bounds equal across two frames when `stable` is required).
5. **Dispatch** through `InputBackend`. An exception before the first event is `not_delivered`
   (`retry: safe`); after it, `delivery_uncertain`.
6. **Verify.** Settle, observe again, diff. A change that matches the action's expectation
   (`scene_change`, `text_appeared`, `surface_appeared`) gives `delivered_verified`; otherwise
   `delivered_unverified` with `verification_reason`. The result also returns `surfaces` so the agent
   answers a dialog next, as agent-desktop does.

Input backends: `DryRunBackend` (records), `PynputBackend` (cross-platform), `Win32SendInputBackend`
(scancodes, for games that ignore virtual keys), `SimBackend` (the simulator). Keys use one vocabulary
(`enter`, `escape`, `space`, `up`, `w`, `ctrl+s`, `shift+click`). `hold_key(key, ms)` exists because games
read held keys, not key taps.

### agent: the loop that agent-desktop leaves to you

- **Model.** `ModelClient` protocol. `AnthropicModelClient` calls `client.messages.create` with
  `claude-opus-5-5`, adaptive thinking (default), `output_config.effort`, strict tools, `tool_choice`
  auto, and the system prompt under `cache_control`. A `refusal` stop reason ends the run as `refused`.
  `ScriptedModelClient` replays turns for tests.
- **Tools** (strict schemas): `observe`, `click`, `double_click`, `right_click`, `hover`, `press`,
  `hold_key`, `type_text`, `scroll`, `drag`, `mouse_click` (coordinates, last resort), `wait`,
  `remember`, `set_objectives`, `ask_user`, `done`.
- **Turn shape.** Each user message carries the tool results of the previous turn **and** a fresh
  observation (compact scene text, the memory block, and the latest frame as an image). Older images are
  dropped from history so the context holds one or two frames, never a film strip.
- **Memory.** Task, objectives with status, notes, lessons (automatic: repeated `STALE_REF` on a name,
  repeated unverified clicks), recent events. Rendered into every observation; persisted per session.
- **Budgets.** Steps, tool calls per turn, wall time. Exhaustion ends the run as `budget_exhausted`
  with the trace path, never as success.
- **Trace.** JSONL with `trace.meta`, `step.start`, `observe`, `model.turn` (usage), `action.start`,
  `action.end`, `action.error`, `done`. Text values redacted by default.

### skills

`skills/core.md` is the loop as the model sees it (short, like agent-desktop's SKILL.md). `skills/genres/`
holds what differs per genre: turn-based, puzzle, action-adventure, menus and inventories. Game-specific
knowledge belongs in a skill or a template set, never in the core code.

## Latency tiers

| Tier | Loop | Fits |
|---|---|---|
| Plan | observe with vision, think, act: 2 to 10 s | quests, menus, dialogs, inventory, strategy turns, puzzles |
| Fast | template perceive and act: 20 to 100 ms, scripted | repeated known moves, waiting for a sprite, simple reactions |
| Reflex | not provided | real-time combat, rhythm, racing |

The agent chooses the tier per objective: a plan step can hand a fast loop a template and a rule
("press space when `enemy_projectile` enters region R") through `fast_policy`. The reflex tier is out of
scope and the docs say so.

## Honesty rules

- `delivered_verified` requires a fresh observation that shows the expected change.
- A detection carries its source and confidence; fusion keeps provenance.
- An empty scene is a valid result. The threshold is not lowered to make the scene look populated.
- The run status is `success` only when the model called `done` with `success: true` **and** the last
  observation did not contradict the claim (a `done` without a prior observation is downgraded to
  `unverified`).

## Extension points

- New perceiver: implement `Perceiver`, register in `Session`. Keep it app-agnostic.
- New input backend: implement `InputBackend`; add to `default_backend()`.
- New genre: add `skills/genres/<name>.md` and templates under a user directory; no code change.
