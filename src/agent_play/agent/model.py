"""Model clients. The loop talks to `ModelClient`; Anthropic is the real one, Scripted is for tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from agent_play.envelope import AgentPlayError, ErrorCode

DEFAULT_MODEL = "claude-opus-5-5"


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ModelTurn:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: str
    raw_content: list[Any]
    usage: dict[str, int] = field(default_factory=dict)
    refusal_category: str | None = None


class ModelClient(Protocol):
    def complete(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelTurn: ...


class AnthropicModelClient:
    """`messages.create` with strict tools, adaptive thinking (the model default) and effort control."""

    def __init__(self, model: str = DEFAULT_MODEL, effort: str = "medium", max_tokens: int = 16000, client: Any | None = None) -> None:
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def complete(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelTurn:
        import anthropic

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                output_config={"effort": self.effort},
                tools=tools,
                tool_choice={"type": "auto"},
                messages=messages,
            )
        except anthropic.RateLimitError as exc:
            raise AgentPlayError(ErrorCode.TIMEOUT, "Rate limited by the model API", "Retry after the retry-after delay", {"status": 429}) from exc
        except anthropic.APIStatusError as exc:
            raise AgentPlayError(ErrorCode.INTERNAL, f"Model request failed: {exc.message}", details={"status": exc.status_code}) from exc
        except anthropic.APIConnectionError as exc:
            raise AgentPlayError(ErrorCode.INTERNAL, "Model API unreachable", details={"cause": str(exc)}) from exc
        text = " ".join(block.text for block in response.content if block.type == "text").strip()
        calls = [ToolCall(block.id, block.name, dict(block.input)) for block in response.content if block.type == "tool_use"]
        category = None
        if response.stop_reason == "refusal":
            category = getattr(getattr(response, "stop_details", None), "category", None)
        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        }
        return ModelTurn(text, calls, response.stop_reason or "end_turn", list(response.content), usage, category)


ScriptFn = Callable[[list[dict[str, Any]], int], "ModelTurn | list[ToolCall] | None"]


class ScriptedModelClient:
    """Replays a script of turns. Each entry is a list of tool calls, a ModelTurn, or a function."""

    def __init__(self, script: list[Any] | ScriptFn) -> None:
        self.script = script
        self.turn_index = 0
        self.seen: list[list[dict[str, Any]]] = []
        self.systems: list[str] = []

    def complete(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelTurn:
        self.seen.append([dict(m) for m in messages])
        self.systems.append(system)
        index = self.turn_index
        self.turn_index += 1
        entry: Any
        if callable(self.script):
            entry = self.script(messages, index)
        else:
            entry = self.script[index] if index < len(self.script) else None
        if entry is None:
            entry = [ToolCall(f"toolu_{index}_0", "done", {"success": False, "summary": "script exhausted"})]
        if isinstance(entry, ModelTurn):
            return entry
        calls = [c if isinstance(c, ToolCall) else ToolCall(f"toolu_{index}_{i}", c[0], dict(c[1])) for i, c in enumerate(entry)]
        for i, call in enumerate(calls):
            if not call.id:
                call.id = f"toolu_{index}_{i}"
        raw: list[Any] = [{"type": "tool_use", "id": call.id, "name": call.name, "input": call.input} for call in calls]
        return ModelTurn("", calls, "tool_use" if calls else "end_turn", raw)
