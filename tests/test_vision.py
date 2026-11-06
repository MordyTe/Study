from types import SimpleNamespace

import pytest
from PIL import Image

from agent_play.envelope import AgentPlayError, ErrorCode
from agent_play.perception.capture import Frame
from agent_play.perception.vision_llm import (
    REPORT_SCENE_TOOL,
    AnthropicVisionModel,
    SceneReport,
    VisionPerceiver,
)


class FakeVisionModel:
    def __init__(self, elements, surfaces=(), summary="a screen"):
        self.elements, self.surfaces, self.summary = elements, list(surfaces), summary
        self.calls = []

    def describe(self, png, width, height, hints):
        self.calls.append((width, height, hints))
        return SceneReport(self.summary, self.surfaces, self.elements)


def test_boxes_map_back_to_screen_pixels_after_downscale():
    frame = Frame(Image.new("RGB", (3200, 1600), "black"))
    model = FakeVisionModel([{"role": "button", "name": "Play", "text": "PLAY", "box": [100, 50, 200, 100], "interactive": True, "states": [], "confidence": 0.8}], surfaces=["menu"])
    perceiver = VisionPerceiver(model, hints="main menu", max_side=1600)
    perception = perceiver.perceive(frame)
    assert model.calls == [(1600, 800, "main menu")]
    (node,) = perception.nodes
    assert node.bounds.x == 200 and node.bounds.y == 100 and node.bounds.width == 200 and node.bounds.height == 100
    assert node.source == "vision" and node.confidence == 0.8 and node.value == "PLAY" and node.interactive
    assert perception.surfaces == ["menu"] and perception.summary == "a screen"


def test_degenerate_boxes_are_dropped():
    frame = Frame(Image.new("RGB", (100, 100), "black"))
    model = FakeVisionModel([{"role": "text", "name": "", "text": "", "box": [5, 5, 5, 5], "interactive": False, "states": [], "confidence": 0.9}, {"role": "x", "name": "", "text": "", "box": [1, 2], "interactive": False, "states": [], "confidence": 0.9}])
    assert VisionPerceiver(model).perceive(frame).nodes == []


def test_tool_schema_is_strict():
    schema = REPORT_SCENE_TOOL["input_schema"]
    assert REPORT_SCENE_TOOL["strict"] is True
    assert schema["additionalProperties"] is False and set(schema["required"]) == set(schema["properties"])
    element = schema["properties"]["elements"]["items"]
    assert element["additionalProperties"] is False and set(element["required"]) == set(element["properties"])


class _FakeMessages:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def _client(response):
    return SimpleNamespace(messages=_FakeMessages(response))


def _response(content, stop_reason="tool_use", category=None):
    return SimpleNamespace(content=content, stop_reason=stop_reason, stop_details=SimpleNamespace(category=category), usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def test_anthropic_vision_model_parses_tool_call_and_sends_strict_tool():
    block = SimpleNamespace(type="tool_use", name="report_scene", input={"summary": "menu", "surfaces": [], "elements": [{"role": "button", "name": "x", "text": "", "box": [0, 0, 1, 1], "interactive": True, "states": [], "confidence": 1}]})
    client = _client(_response([block]))
    report = AnthropicVisionModel(client=client, model="claude-opus-5-5").describe(b"png", 10, 10, "")
    assert report.summary == "menu" and len(report.elements) == 1 and report.usage["input_tokens"] == 10
    kwargs = client.messages.kwargs
    assert kwargs["model"] == "claude-opus-5-5" and kwargs["tool_choice"] == {"type": "auto"}
    assert kwargs["tools"][0]["strict"] is True and kwargs["output_config"] == {"effort": "low"}
    assert kwargs["messages"][0]["content"][0]["type"] == "image"


def test_refusal_and_missing_tool_call_become_errors():
    with pytest.raises(AgentPlayError) as refused:
        AnthropicVisionModel(client=_client(_response([], "refusal", "cyber"))).describe(b"png", 10, 10, "")
    assert refused.value.code is ErrorCode.MODEL_REFUSED and refused.value.details["category"] == "cyber"
    text = SimpleNamespace(type="text", text="I see a menu")
    with pytest.raises(AgentPlayError) as missing:
        AnthropicVisionModel(client=_client(_response([text], "end_turn"))).describe(b"png", 10, 10, "")
    assert missing.value.code is ErrorCode.PERCEPTION_FAILED
