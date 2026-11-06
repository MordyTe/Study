"""The observe, decide, act, verify loop that agent-desktop leaves to the calling agent.

Each model turn sees the tool results of the previous turn and a fresh observation in one user
message, so the model never reasons from a stale frame. Older frames are dropped from the history.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from typing import Any

from agent_play.actions.executor import ActionRequest
from agent_play.agent.memory import WorkingMemory
from agent_play.agent.model import ModelClient, ToolCall
from agent_play.agent.tools import ACTION_TOOLS, CONTROL_TOOLS, TOOLS
from agent_play.envelope import AgentPlayError, ErrorCode, Response
from agent_play.knowledge.anticheat import Assessment, assess
from agent_play.knowledge.store import KnowledgeStore
from agent_play.scene.snapshot import Snapshot
from agent_play.session import Session
from agent_play.skills import load_skill

OMITTED_FRAME = "[earlier frame omitted to keep the context small]"
DEFAULT_SKILLS = ["core", "anti_cheat"]


@dataclass
class AgentConfig:
    max_steps: int = 40
    max_tool_calls_per_turn: int = 6
    max_wall_s: float = 900.0
    include_image: bool = True
    image_history: int = 1
    image_max_side: int = 1280
    observe_after_actions: str = "full"
    interactive_only: bool = False
    max_text_turns: int = 2
    block_protected: bool = False


@dataclass
class RunResult:
    status: str
    summary: str
    steps: int
    actions: int
    memory: WorkingMemory
    question: str | None = None
    trace_path: str | None = None
    last_snapshot_id: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    assessment: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "status": self.status,
            "summary": self.summary,
            "steps": self.steps,
            "actions": self.actions,
            "objectives": [o.to_dict() for o in self.memory.objectives],
            "lessons": list(self.memory.lessons),
            "usage": self.usage,
            "anticheat": self.assessment,
        }
        if self.question:
            data["question"] = self.question
        if self.trace_path:
            data["trace_path"] = self.trace_path
        if self.last_snapshot_id:
            data["last_snapshot_id"] = self.last_snapshot_id
        return data


class GameAgent:
    def __init__(
        self,
        session: Session,
        model: ModelClient,
        config: AgentConfig | None = None,
        skills: list[str] | None = None,
        extra_instructions: str = "",
        log: Any | None = None,
        knowledge: KnowledgeStore | None = None,
    ) -> None:
        self.session = session
        self.model = model
        self.config = config or AgentConfig()
        self.skills = skills or list(DEFAULT_SKILLS)
        self.extra_instructions = extra_instructions
        self.log = log or (lambda _line: None)
        self.knowledge = knowledge or KnowledgeStore(session.root)
        self.usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}
        self._assessment: Assessment | None = None

    def system_prompt(self) -> str:
        parts = [load_skill(name) for name in self.skills]
        if self.extra_instructions.strip():
            parts.append("# Instructions for this run\n\n" + self.extra_instructions.strip())
        learned = self.knowledge.render()
        if learned.strip():
            parts.append("# Knowledge you kept from earlier runs\n\n" + learned)
        return "\n\n".join(parts)

    def run(self, task: str) -> RunResult:
        memory = WorkingMemory(task=task)
        system = self.system_prompt()
        trace = self.session.trace
        started = time.monotonic()
        trace.write("run.start", {"task": task, "max_steps": self.config.max_steps})
        self._assessment = assess(task)
        trace.write("anticheat.assess", self._assessment.to_dict())
        if self._assessment.policy in ("refuse", "warn"):
            memory.add_note("Anti-cheat risk: " + self._assessment.reason)
            self.log(f"anti-cheat {self._assessment.policy}: {self._assessment.reason}")
            if self._assessment.policy == "refuse" and self.config.block_protected:
                return self._finish("blocked_policy", self._assessment.reason, memory, None)
        messages: list[dict[str, Any]] = []
        snapshot = self.session.observe()
        messages.append({"role": "user", "content": self._observation_blocks(snapshot, memory, first=True)})
        text_only_turns = 0
        last_snapshot = snapshot

        for step in range(1, self.config.max_steps + 1):
            memory.steps = step
            if time.monotonic() - started > self.config.max_wall_s:
                return self._finish("budget_exhausted", f"Wall-clock budget of {self.config.max_wall_s:.0f}s spent", memory, last_snapshot)
            trace.write("step.start", {"step": step})
            turn = self.model.complete(system, messages, TOOLS)
            for key, value in turn.usage.items():
                self.usage[key] = self.usage.get(key, 0) + int(value)
            trace.write("model.turn", {"step": step, "stop_reason": turn.stop_reason, "tool_calls": [c.name for c in turn.tool_calls], "usage": turn.usage})
            self.log(f"step {step}: {turn.text[:160]!r} tools={[(c.name, c.input) for c in turn.tool_calls]}")
            if turn.stop_reason == "refusal":
                return self._finish("refused", f"The model declined to continue (category: {turn.refusal_category})", memory, last_snapshot)
            messages.append({"role": "assistant", "content": turn.raw_content})

            if not turn.tool_calls:
                text_only_turns += 1
                if text_only_turns > self.config.max_text_turns:
                    return self._finish("failed", "The model stopped calling tools: " + (turn.text or "no text"), memory, last_snapshot)
                messages.append({"role": "user", "content": [{"type": "text", "text": "Use a tool: act on a ref, observe, ask_user, or call done with an honest success flag."}]})
                continue
            text_only_turns = 0

            results: list[dict[str, Any]] = []
            control: tuple[str, dict[str, Any]] | None = None
            acted = False
            observed_in_turn: Snapshot | None = None
            for call in turn.tool_calls[: self.config.max_tool_calls_per_turn]:
                outcome, is_error, snapshot_from_call = self._dispatch(call, memory)
                self.log(f"  {call.name} -> {'ERROR ' if is_error else ''}{outcome[:200]}")
                results.append({"type": "tool_result", "tool_use_id": call.id, "content": outcome, "is_error": is_error})
                if snapshot_from_call is not None:
                    observed_in_turn = snapshot_from_call
                    last_snapshot = snapshot_from_call
                if call.name in ACTION_TOOLS and not is_error:
                    acted = True
                if call.name in CONTROL_TOOLS and not is_error:
                    control = (call.name, call.input)
                    break
            for skipped in turn.tool_calls[self.config.max_tool_calls_per_turn :]:
                results.append({"type": "tool_result", "tool_use_id": skipped.id, "content": "Skipped: too many tool calls in one turn. Observe, then continue.", "is_error": True})

            if control is not None:
                name, payload = control
                if name == "ask_user":
                    return self._finish("needs_input", "The agent needs an answer from the user", memory, last_snapshot, question=str(payload.get("question", "")))
                success = bool(payload.get("success"))
                summary = str(payload.get("summary", "")).strip()
                if success and acted and observed_in_turn is None:
                    return self._finish("success_unverified", summary + " [claimed in the same turn as an action, before observing the result]", memory, last_snapshot)
                return self._finish("success" if success else "failed", summary, memory, last_snapshot)

            if acted or observed_in_turn is None:
                fresh = self.session.observe(fast_only=self.config.observe_after_actions == "fast")
                last_snapshot = fresh
                results.extend(self._observation_blocks(fresh, memory))
            else:
                results.append({"type": "text", "text": memory.render()})
            messages.append({"role": "user", "content": results})
            self._prune_images(messages)

        return self._finish("budget_exhausted", f"Step budget of {self.config.max_steps} spent", memory, last_snapshot)

    def _dispatch(self, call: ToolCall, memory: WorkingMemory) -> tuple[str, bool, Snapshot | None]:
        name, args = call.name, call.input
        try:
            if name == "observe":
                detail = str(args.get("detail", "full"))
                snapshot = self.session.observe(fast_only=detail == "fast")
                shown = snapshot.skeleton(2) if detail == "skeleton" else snapshot
                return Response.to_json(Response.ok("observe", {"snapshot_id": snapshot.snapshot_id, "ref_count": snapshot.ref_count(), "scene": shown.compact_text(self.config.interactive_only)})), False, snapshot
            if name == "wait":
                data = self.session.wait(
                    text=str(args.get("text") or "") or None,
                    ref_id=str(args.get("ref_id") or "") or None,
                    gone=bool(args.get("gone")),
                    stable=bool(args.get("stable")),
                    timeout_ms=int(args.get("timeout_ms") or 5000),
                )
                return Response.to_json(Response.ok("wait", data)), False, None
            if name == "remember":
                memory.add_note(str(args.get("note", "")))
                return Response.to_json(Response.ok("remember", {"notes": len(memory.notes)})), False, None
            if name == "learn":
                topic = str(args.get("topic", "")).strip() or "notes"
                text = str(args.get("text", "")).strip()
                if not text:
                    raise AgentPlayError(ErrorCode.INVALID_ARGS, "learn needs text")
                slug = self.knowledge.add(topic, text)
                self.session.trace.write("knowledge.learn", {"topic": slug})
                return Response.to_json(Response.ok("learn", {"topic": slug, "topics": self.knowledge.topics()})), False, None
            if name == "set_objectives":
                memory.set_objectives(list(args.get("objectives", [])))
                return Response.to_json(Response.ok("set_objectives", {"objectives": [o.to_dict() for o in memory.objectives]})), False, None
            if name in CONTROL_TOOLS:
                return Response.to_json(Response.ok(name, {"acknowledged": True})), False, None
            if name in ACTION_TOOLS:
                request = _to_request(name, args)
                result = self.session.act(request)
                memory.record_action_result(name, request.ref_id or (f"({request.x},{request.y})" if request.x is not None else request.key or request.text), result.delivery.value, result.verification.get("reason"))
                return Response.to_json(Response.ok(name, result.to_dict())), False, None
            raise AgentPlayError(ErrorCode.INVALID_ARGS, f"Unknown tool {name!r}")
        except AgentPlayError as exc:
            if name in ACTION_TOOLS:
                memory.record_action_error(name, str(args.get("ref_id") or args.get("key") or ""), exc.code.value)
            self.session.trace.write("tool.error", {"tool": name, "code": exc.code.value})
            return Response.to_json(Response.err(name, exc)), True, None

    def _observation_blocks(self, snapshot: Snapshot, memory: WorkingMemory, first: bool = False) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        frame = self.session.last_frame
        if self.config.include_image and frame is not None:
            small, _ = frame.downscaled(self.config.image_max_side)
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.standard_b64encode(small.to_png_bytes()).decode("ascii")}})
        header = "First observation. " if first else "Observation after your last turn. "
        text = header + "Scene (act on refs from this snapshot only):\n" + snapshot.compact_text(self.config.interactive_only) + "\n\n" + memory.render()
        blocks.append({"type": "text", "text": text})
        return blocks

    def _prune_images(self, messages: list[dict[str, Any]]) -> None:
        keep = self.config.image_history
        seen = 0
        for message in reversed(messages):
            if message.get("role") != "user" or not isinstance(message.get("content"), list):
                continue
            has_image = any(isinstance(b, dict) and b.get("type") == "image" for b in message["content"])
            if not has_image:
                continue
            seen += 1
            if seen <= keep:
                continue
            message["content"] = [
                {"type": "text", "text": OMITTED_FRAME} if isinstance(b, dict) and b.get("type") == "image" else b for b in message["content"]
            ]

    def _finish(self, status: str, summary: str, memory: WorkingMemory, snapshot: Snapshot | None, question: str | None = None) -> RunResult:
        self.session.trace.write("run.end", {"status": status, "steps": memory.steps, "actions": memory.actions})
        if self.session.dir is not None:
            memory.save(self.session.dir / "memory.json")
        return RunResult(
            status=status,
            summary=summary,
            steps=memory.steps,
            actions=memory.actions,
            memory=memory,
            question=question,
            trace_path=str(self.session.trace.path) if self.session.trace.path else None,
            last_snapshot_id=snapshot.snapshot_id if snapshot else None,
            usage=dict(self.usage),
            assessment=self._assessment.to_dict() if self._assessment else {},
        )


def _to_request(name: str, args: dict[str, Any]) -> ActionRequest:
    ref = str(args.get("ref_id") or "") or None
    if name in ("click", "double_click", "right_click", "hover"):
        return ActionRequest(name, ref_id=ref)
    if name == "mouse_click":
        return ActionRequest("mouse_click", x=float(args["x"]), y=float(args["y"]), button=str(args.get("button") or "left"))
    if name == "press":
        return ActionRequest("press", key=str(args.get("key", "")))
    if name == "hold_key":
        return ActionRequest("hold_key", key=str(args.get("key", "")), duration_ms=int(args.get("duration_ms") or 100))
    if name == "type_text":
        return ActionRequest("type_text", text=str(args.get("text", "")))
    if name == "scroll":
        return ActionRequest("scroll", ref_id=ref, direction=str(args.get("direction") or "down"), amount=int(args.get("amount") or 3))
    if name == "drag":
        return ActionRequest("drag", ref_id=ref, to_ref=str(args.get("to_ref") or "") or None)
    raise AgentPlayError(ErrorCode.INVALID_ARGS, f"Unknown action tool {name!r}")
