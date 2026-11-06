"""Session: one frame source, a set of perceivers, a ref store, an executor, a trace.

`observe()` runs every available perceiver (slow ones included) and allocates refs; `observe_fast()`
runs only the cheap ones for re-identification and verification. The two share one code path.
"""

from __future__ import annotations

import os
import secrets
import time
from pathlib import Path
from typing import Any, Callable

from agent_play.actions.backend import BaseBackend, DryRunBackend
from agent_play.actions.executor import ActionExecutor, ActionRequest, ActionResult
from agent_play.actions.policy import InteractionPolicy
from agent_play.envelope import AgentPlayError, ErrorCode
from agent_play.perception.base import Perceiver, Perception
from agent_play.perception.capture import Frame, FrameSource
from agent_play.perception.fusion import fuse
from agent_play.scene.refs import RefStore
from agent_play.scene.snapshot import Snapshot


def default_state_root() -> Path:
    return Path(os.environ.get("AGENT_PLAY_HOME", Path.home() / ".agent-play"))


def new_session_id() -> str:
    return f"run-{int(time.time() * 1000)}-{os.getpid()}-{secrets.token_hex(2)}"


class Session:
    def __init__(
        self,
        source: FrameSource,
        perceivers: list[Perceiver],
        backend: BaseBackend | None = None,
        policy: InteractionPolicy | None = None,
        root: Path | None = None,
        session_id: str | None = None,
        a11y_click: Callable[[str], dict[str, Any]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        redact_trace: bool = True,
    ) -> None:
        from agent_play.trace import Trace

        self.source = source
        self.perceivers = list(perceivers)
        self.policy = policy or InteractionPolicy()
        self.backend = backend or DryRunBackend()
        self.session_id = session_id or new_session_id()
        self.root = root
        self.dir = (root / "sessions" / self.session_id) if root else None
        if self.dir is not None:
            self.dir.mkdir(parents=True, exist_ok=True)
        self.refs = RefStore(self.dir)
        self.trace = Trace(self.dir / "trace.jsonl" if self.dir else None, self.session_id, redact=redact_trace)
        self.sleep = sleep
        self.last_frame: Frame | None = None
        self.last_snapshot: Snapshot | None = None
        self.executor = ActionExecutor(
            refs=self.refs,
            backend=self.backend,
            policy=self.policy,
            capture=self.capture,
            observe_fast=self.observe_fast,
            screen=self.screen,
            a11y_click=a11y_click,
            sleep=sleep,
            on_event=self.trace.write,
        )

    def capture(self) -> Frame:
        frame = self.source.capture()
        self.last_frame = frame
        return frame

    def screen(self) -> tuple[int, int]:
        if self.last_frame is not None:
            return self.last_frame.size
        return self.capture().size

    def available_perceivers(self, fast_only: bool = False) -> list[Perceiver]:
        chosen = []
        for perceiver in self.perceivers:
            if fast_only and not perceiver.fast:
                continue
            try:
                if perceiver.available():
                    chosen.append(perceiver)
            except Exception:
                continue
        return chosen

    def _perceive(self, frame: Frame, perceivers: list[Perceiver]) -> Snapshot:
        per_source: list[tuple[str, list]] = []
        surfaces: list[str] = []
        summary: str | None = None
        complete = True
        failures: list[dict[str, str]] = []
        for perceiver in perceivers:
            started = time.monotonic()
            try:
                perception: Perception = perceiver.perceive(frame)
            except AgentPlayError as exc:
                if exc.code is ErrorCode.MODEL_REFUSED:
                    raise
                failures.append({"perceiver": perceiver.name, "code": exc.code.value, "message": exc.message})
                complete = False
                continue
            self.trace.write("perceive", {"perceiver": perceiver.name, "nodes": len(perception.nodes), "duration_ms": int((time.monotonic() - started) * 1000)})
            per_source.append((perceiver.name, perception.nodes))
            for surface in perception.surfaces:
                if surface not in surfaces:
                    surfaces.append(surface)
            summary = summary or perception.summary
            complete = complete and perception.complete
        snapshot = Snapshot(
            roots=fuse(per_source),
            captured_at_ms=frame.captured_at_ms,
            screen=frame.size,
            frame_hash=frame.hash(),
            surfaces=surfaces,
            complete=complete,
            sources=[name for name, _ in per_source],
            summary=summary,
        )
        if failures:
            snapshot.summary = (snapshot.summary or "") + " [perception failures: " + "; ".join(f"{f['perceiver']}={f['code']}" for f in failures) + "]"
        return snapshot

    def observe(self, fast_only: bool = False) -> Snapshot:
        frame = self.capture()
        perceivers = self.available_perceivers(fast_only=fast_only)
        snapshot = self._perceive(frame, perceivers)
        self.refs.allocate(snapshot, fingerprint_fn=frame.fingerprint)
        self.last_snapshot = snapshot
        self.trace.write("snapshot.saved", {"snapshot_id": snapshot.snapshot_id, "ref_count": snapshot.ref_count(), "sources": snapshot.sources})
        return snapshot

    def observe_fast(self) -> Snapshot | None:
        perceivers = self.available_perceivers(fast_only=True)
        if not perceivers:
            return None
        frame = self.capture()
        return self._perceive(frame, perceivers)

    def act(self, request: ActionRequest) -> ActionResult:
        return self.executor.execute(request)

    def wait(self, text: str | None = None, ref_id: str | None = None, gone: bool = False, stable: bool = False, timeout_ms: int = 5000, poll_ms: int = 200) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_ms / 1000.0
        last_hash = None
        stable_count = 0
        while True:
            snapshot = self.observe_fast()
            frame = self.last_frame if snapshot is not None else self.capture()
            assert frame is not None
            if stable:
                current = frame.hash()
                stable_count = stable_count + 1 if current == last_hash else 0
                last_hash = current
                if stable_count >= 2:
                    return {"satisfied": True, "condition": "stable"}
            elif text is not None:
                present = snapshot is not None and any(text.lower() in ((n.value or "") + " " + (n.name or "")).lower() for n in snapshot.nodes())
                if present != gone:
                    return {"satisfied": True, "condition": "text_gone" if gone else "text_present", "text": text}
            elif ref_id is not None:
                entry = self.refs.resolve(ref_id)
                from agent_play.scene.refs import match_candidates

                present = snapshot is not None and bool(match_candidates(entry, snapshot.nodes()))
                if present != gone:
                    return {"satisfied": True, "condition": "ref_gone" if gone else "ref_present", "ref_id": ref_id}
            else:
                raise AgentPlayError(ErrorCode.INVALID_ARGS, "wait needs text, ref_id or stable")
            if time.monotonic() >= deadline:
                raise AgentPlayError(
                    ErrorCode.TIMEOUT,
                    f"Wait condition not met within {timeout_ms} ms",
                    "Observe the screen and decide from what is there.",
                    {"text": text, "ref_id": ref_id, "gone": gone, "stable": stable, "retryable": False},
                )
            self.sleep(poll_ms / 1000.0)

    def status(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "session_dir": str(self.dir) if self.dir else None,
            "backend": self.backend.name,
            "headed": self.policy.headed,
            "perceivers": [{"name": p.name, "fast": p.fast, "available": _safe_available(p)} for p in self.perceivers],
            "screen": list(self.screen()),
        }


def _safe_available(perceiver: Perceiver) -> bool:
    try:
        return bool(perceiver.available())
    except Exception:
        return False
