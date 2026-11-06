# Reverse engineering: agent-desktop and agent-browser

Source studied on 2026-11-06, read directly from the repositories (both Apache-2.0):

| Project | Commit | Size | What it is |
|---|---|---|---|
| `vercel-labs/agent-desktop` | `b43ac4f` (v1.2.0) | ~350K lines of Rust: core 88K, linux 124K, windows 79K, macos 45K, ffi 15K, binary 14K | Computer use through the OS accessibility tree. CLI and C library. Docs served at agent-browser.dev/desktop |
| `vercel-labs/agent-browser` | `71850a0` | ~134K lines of Rust in `cli/` | Browser automation over CDP with the same snapshot-and-ref idea |

Local clones for further reading: `/home/user/vercel-labs/agent-desktop`, `/home/user/vercel-labs/agent-browser`.
Nothing here was copied; this document records the design so that `agent-play` can keep what works and
replace what does not apply to games.

## 1. The idea in one paragraph

Both tools refuse to give the model pixels and coordinates. They read a **structured tree** of the UI
(the accessibility tree), give every actionable element a short **ref**, and let the agent act on refs.
The tool then **re-identifies** the element before acting, checks that it is actionable, acts through the
platform's semantic API, reads the state back, and reports exactly how sure it is that the action landed.
Neither tool contains a model: "the loop lives in your agent". Skills, compiled into the binary, teach the
calling agent the loop.

## 2. Contracts worth keeping

### 2.1 One JSON envelope per command

Every command prints exactly one JSON object on stdout (logs go to stderr). Shape (`crates/core/src/response/output.rs`):

```json
{ "version": "2.6", "ok": true,  "command": "click", "data": { ... } }
{ "version": "2.6", "ok": false, "command": "click", "error": {
    "code": "STALE_REF", "message": "...", "suggestion": "...",
    "recovery": { "strategy": "refresh_snapshot_then_retry_original", "retryable": true,
                  "requires_fresh_snapshot": true },
    "details": { "kind": "saved_ref_absent" },
    "disposition": { "delivery": "not_delivered", "retry": "safe" } } }
```

Error codes: `PERM_DENIED`, `ELEMENT_NOT_FOUND`, `APP_NOT_FOUND`, `ACTION_FAILED`, `ACTION_NOT_SUPPORTED`,
`STALE_REF`, `AMBIGUOUS_TARGET`, `WINDOW_NOT_FOUND`, `PLATFORM_NOT_SUPPORTED`, `TIMEOUT`, `INVALID_ARGS`,
`SNAPSHOT_NOT_FOUND`, `POLICY_DENIED`, `APP_UNRESPONSIVE`, `NOTIFICATION_NOT_FOUND`, `INTERNAL`.
The skill tells agents to branch on `code` and `disposition`, never on message text.

### 2.2 Snapshots and qualified refs

`snapshot` observes one window (or one *surface*) and returns a tree of `AccessibilityNode`
(`crates/core/src/tree/node.rs`): `role`, `name`, `description`, `value`, `states`, `bounds`,
`available_actions`, `native_id`, `children_count`, `subtree_truncated`, `children`, and `ref_id`.

- Refs are **qualified**: `@<snapshot_id>:e<N>` (`@s26u7pv9qta5g4:e6`). A bare `@e1` is rejected. The
  snapshot id scopes the ref to one observation and one session namespace.
- Only addressable elements get refs. Static text and inert containers do not.
- The ref map is persisted on disk (`RefMap`, `RefEntry`: process, identity, geometry, capabilities,
  source, scope). Each entry stores enough identity to find the element again later.
- **Re-identification before acting.** A command resolves the ref against the live tree. On macOS the
  entry carries the element's own address. On Windows and Linux the element must have been the only one
  in the window with its `(role, native_id, name, description)` at capture, and exactly one live element
  must match now. Zero matches is `STALE_REF`, two or more is `AMBIGUOUS_TARGET`. Identical twins (a
  "Delete" button in every row) have no ref path; only `--headed mouse-click --xy` can choose one.
- `agent-browser` uses the same idea with bare `@eN` refs per page and a persistent daemon per session.

### 2.3 Skeleton and drill-down (token budget as a first-class concern)

A dense app (Electron, IDE) has thousands of nodes. `snapshot --skeleton` reads to depth 3 and marks cut
containers with `children_count`. `snapshot --root <ref>` drills one region and adds its refs to the
**same** snapshot id; refs outside the drilled subtree stay valid, refs inside it are replaced
(`RefMap::remove_by_root_ref`). `-i` keeps interactive nodes only; `--compact` drops empty structure.
The skill's first anti-pattern is "full snapshots of a dense app".

### 2.4 Surfaces

Menus, sheets, alerts, popovers and OS shell areas (taskbar, dock, notification center) are observed
separately with `--surface`. Actions that may open an overlay (`click`, `press`, `expand`, ...) return
`data.surfaces`; a `menu`/`sheet`/`alert` entry means "answer this overlay next". Snapshotting the window
while an overlay is open is an anti-pattern.

### 2.5 Actionability gates (fail closed)

Before dispatch (`crates/core/src/actionability/`), per action: `visible`, `stable` (bounds sampled
twice), `enabled`, `editable`, `receives_events` (hit test at the center point; an occluder is reported by
name). A click that would land on a covering banner fails instead of "succeeding". `agent-browser` does
the same: "A click fails, instead of reporting success, when the target is hidden, disabled, outside the
viewport, or covered".

### 2.6 Delivery semantics and post-action verification

`DeliverySemantics` (`crates/core/src/actions/delivery_semantics.rs`) is serialized as
`{ "delivery": ..., "retry": ... }`:

| delivery | retry | meaning |
|---|---|---|
| `not_delivered` | `safe` | nothing reached the app; retry or substitute freely |
| `delivery_uncertain` | `unsafe` | it may have landed |
| `delivered_unverified` | `unsafe` | it landed; the outcome was not read back |
| `delivered_verified` | `unsafe` | it landed and a fresh read shows the expected state |

`execute_verified_action` (`actions/post_action.rs`) reads the element before, acts, then polls the live
element for up to 400 ms until the postcondition holds (value set, text inserted, checked toggled,
expanded). A mismatch is `ACTION_FAILED` with `details.post_state`; a state it cannot read becomes
`delivered_unverified` with `verification_reason`. Even a verified `set-value` says
`application_commit: not_verified`: the field holds the text, the app may still reject it.

### 2.7 Waits over sleeps

`wait --text`, `--element <ref> --predicate actionable`, `--window`, `--menu`, `--menu-closed`,
`--event window-opened|app-terminated|...`. Events come from a pure baseline diff of windows, apps and
surfaces (`wait/signals.rs`: `diff_signals(baseline, current)`), unit-tested with fixtures. "A fixed sleep is
a race."

### 2.8 Headless by default, headed by consent

Ref actions use semantic calls (AXPress, UIA Invoke, AT-SPI actions): no cursor move, no focus steal, no
synthesized keys. If no semantic path exists the action **fails closed**. `--headed` enables physical
input for double-click, hover, drag, coordinate clicks. The skill forbids switching to headed to recover
from a headless failure. `--xy` never implies focus.

### 2.9 Sessions, traces, redaction

A session is an on-disk namespace (`sessions/<id>/` with `session.json`, `snapshots/`, `trace/`). The trace
is append-only JSONL: `trace.meta`, `command.start/end` (with `ok`, `duration_ms`, `code`),
`snapshot.saved`, `ref.resolve.ok/error`, `actionability.check.ok/error`, `action.artifacts`. Trace lines
redact `text`, `value`, `name`, `title`, `url`, `label`, `description`, `password`. Screenshots are opt-in
(`session start --screenshots`) and never redacted. Budgets: 32 MiB, 100,000 events per session.

### 2.10 Skills, MCP, batch

- Skills are versioned markdown shipped in the binary (`skills get desktop`, `skills get platform`,
  `--ref workflows`). The core skill is short: the loop, refs, delivery and retry rules, headless vs headed,
  and a routing table to references loaded on demand. `agent-browser`'s installed skill is a thin stub that
  says "run `agent-browser skills get core`" so instructions always match the installed CLI.
- `agent-desktop mcp` derives one MCP tool per CLI leaf command from the clap tree at runtime and runs the
  binary as a child process; there is no second command surface.
- `batch` deserializes entries into the same `Commands` enum and the same `dispatch()`; it is not a
  transaction.

### 2.11 Engineering rules that keep it honest (from `AGENTS.md`)

- `PlatformAdapter` dependency inversion: core defines the trait and every type; platform crates implement
  it; CI fails if core depends on a platform crate. Every adapter method defaults to `not_supported`.
- One command per file, 400 lines per file, no inline comments, at most 7 fields per struct.
- "Fixes must be application-agnostic": never branch on an app name, bundle id or window title.
- Raw platform measurements live in `probes/**/FINDINGS.md`; a plan that contradicts the code is corrected
  with a citation to a probe row or a source line.
- "Build it; do not defer it. Reducing scope is the owner's call."

## 3. Where it stops: the gap for games

The README is explicit: *"agent-desktop gives an AI agent computer use without screenshots or pixel
matching"* and *"It cannot see UIs that expose no accessibility tree."* That is the whole problem for games:

1. **Games expose no tree.** DirectX, Vulkan, OpenGL, Unity, Unreal, Godot and most custom engines render
   their UI themselves. The accessibility API sees one opaque window. `snapshot` returns an empty tree
   with `complete: true`, which the skill warns "looks like a missing permission".
2. **The only remaining path is discouraged.** `screenshot` returns base64 PNG and `--headed mouse-click
   --xy X,Y` clicks a coordinate, but nothing turns the image into refs, nothing re-identifies a pixel
   target, and "coordinates when a ref exists" is anti-pattern number two.
3. **Semantic input does not reach a game.** AXPress and UIA Invoke drive widgets, not a game loop. Games
   poll raw input, and on Windows many read DirectInput scancodes, so a virtual-key `SendInput` is ignored.
   There is no "hold W for 400 ms" primitive.
4. **Process per command.** Each `agent-desktop` call is a new process that reloads the ref map from disk.
   This is fine for forms and fatal for anything that must react within a frame.
5. **No loop, no memory, no plan.** By design. A game task ("finish the quest") needs task decomposition,
   a goal stack, a memory of what was tried, and a stop condition. `agent-browser` has `flow` (recorded
   HTTP flows) and `chat`, but no planner either.
6. **Verification assumes a readable element.** `delivered_verified` means "the element's state matches".
   In a game, the evidence is the next frame.

`agent-browser` shares the same limits for canvas and WebGL pages: the snapshot of a `<canvas>` game is one
node.

## 4. What `agent-play` keeps and what it changes

| Concern | agent-desktop | agent-play |
|---|---|---|
| Output | one JSON envelope, versioned | same shape, version `1.0`, same error codes plus `PERCEPTION_FAILED`, `MODEL_REFUSED`, `BUDGET_EXHAUSTED` |
| Perception | accessibility tree only | fused scene from template matching, a vision model, OCR, and the accessibility tree through an `agent-desktop` bridge; every node carries `source` and `confidence` |
| Refs | `@<snapshot>:e<N>`, identity = role + native id + name + description, unique in window | same syntax; identity adds bounds and a pixel fingerprint of the element so twins (five identical enemies) can be told apart by position |
| Re-identification | live tree resolve, `STALE_REF` / `AMBIGUOUS_TARGET` | fast re-perceive (templates, a11y) plus a fingerprint check of the stored crop against a fresh frame; same error codes |
| Actionability | visible, stable, enabled, editable, receives events | visible on screen, stable across two frames, enabled state when known; occlusion from the fused scene |
| Delivery semantics | four levels, retry safety | identical vocabulary; verification evidence is a frame diff (`scene_change`) or a text/ref wait |
| Input | semantic headless, physical headed | always physical (a game reads nothing else), behind `InputBackend`; dry-run by default, `--headed` for real input; key hold with duration; Windows scancodes |
| Waits | text, element, window, menu, event | text, ref appeared/disappeared, scene stable, frame changed |
| Sessions and traces | JSONL, redacted | same event names where they apply, plus `model.turn` with token usage |
| Skills | compiled into the binary | markdown in the package, loaded into the system prompt; genre skills |
| Loop | in the calling agent | inside: observe, decide (Claude with strict tools), act, verify, remember; budgets and stop conditions |
| Rules | adapter inversion, one command per file, app-agnostic | perceiver and backend protocols, no game-specific branches in the core, game knowledge only in skills and templates |

## 5. Code map for further reading

| Topic | File in the clone |
|---|---|
| Envelope and recovery hints | `crates/core/src/response/output.rs` |
| Node, state, presentation | `crates/core/src/tree/{node,element_state,node_presentation,role}.rs` |
| Ref map and drill replacement | `crates/core/src/refs/mod.rs`, `refs/ref_entry.rs` |
| Actionability requirements per action | `crates/core/src/actionability/requirements.rs` |
| Post-action verification | `crates/core/src/actions/post_action.rs` |
| Delivery semantics | `crates/core/src/actions/delivery_semantics.rs` |
| Wait event diff | `crates/core/src/wait/signals.rs` |
| Coordinate click and point resolution | `crates/core/src/commands/{mouse_click,point_resolve,screenshot}.rs` |
| Agent-facing skill | `skills/agent-desktop/SKILL.md`, `references/workflows.md` |
| Vocabulary | `CONCEPTS.md`; engineering rules `AGENTS.md` |
| Docs | `apps/docs/content/docs/*.mdx` (snapshots-and-refs, skeleton-and-drill-down, surfaces, json-output, errors-and-recovery, guides/traces) |
| agent-browser loop and refs | `skill-data/core/SKILL.md`, `cli/src/native/snapshot.rs`, `cli/src/native/actions.rs` |
