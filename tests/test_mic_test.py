import pytest

np = pytest.importorskip("numpy")

from studio_transcribe.config import Config
from studio_transcribe.live.mic_test import MicTestRunner
from studio_transcribe.models import Segment


class _FakeEngine:
    def __init__(self, text="שלום בדיקה"):
        self.text = text
        self.calls = 0

    def transcribe(self, audio, language="he", initial_prompt=None):
        self.calls += 1
        return [Segment(0.0, 1.0, self.text)]


def _runner(engine):
    events = []
    cfg = Config.from_dict({})
    r = MicTestRunner(cfg, on_event=events.append, engine=engine)
    return r, events


def test_flush_emits_text_for_speech():
    engine = _FakeEngine("שלום בדיקה")
    r, events = _runner(engine)
    r.feed(np.full(16000, 0.2, dtype=np.float32))  # 1s of non-silence
    r.flush_once()
    texts = [e for e in events if e["kind"] == "text"]
    assert texts and texts[0]["text"] == "שלום בדיקה"
    assert engine.calls == 1


def test_flush_skips_silence():
    engine = _FakeEngine()
    r, events = _runner(engine)
    r.feed(np.zeros(16000, dtype=np.float32))  # silence
    r.flush_once()
    assert engine.calls == 0
    assert not [e for e in events if e["kind"] == "text"]


def test_flush_noop_when_buffer_empty():
    engine = _FakeEngine()
    r, _ = _runner(engine)
    r.flush_once()  # nothing fed
    assert engine.calls == 0


def test_buffer_cleared_after_flush():
    engine = _FakeEngine()
    r, _ = _runner(engine)
    r.feed(np.full(8000, 0.2, dtype=np.float32))
    r.flush_once()
    r.flush_once()  # buffer should be empty now -> no second call
    assert engine.calls == 1
