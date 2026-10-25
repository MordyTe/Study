from studio_transcribe.config import Config, LiveConfig
from studio_transcribe.live.captions import CaptionComposer, _tail
from studio_transcribe.live.sinks import FileSink, StdoutSink, build_sink


class _Clock:
    """Deterministic, monotonically increasing fake clock."""

    def __init__(self, step=1.0):
        self.t = 0.0
        self.step = step

    def __call__(self):
        self.t += self.step
        return self.t


def test_partial_is_replaced_by_final():
    # A partial tail is tentative; the matching final delta replaces it.
    c = CaptionComposer(throttle_ms=300, clock=_Clock())
    assert c.update(1, "מנחה", "של", is_final=False) == "מנחה: של"
    assert c.update(1, "מנחה", "שלום", is_final=True) == "מנחה: שלום"
    assert c.current() == "מנחה: שלום"


def test_final_deltas_accumulate():
    # Successive final deltas build up the running line.
    c = CaptionComposer(throttle_ms=300, clock=_Clock())
    c.update(1, "מנחה", "שלום", is_final=True)
    c.update(1, "מנחה", "עולם", is_final=True)
    assert c.current() == "מנחה: שלום עולם"


def test_throttle_suppresses_rapid_partials():
    t = [0.0]
    c = CaptionComposer(throttle_ms=300, clock=lambda: t[0])
    t[0] = 0.0
    assert c.update(1, "a", "x", False) is None      # 0 - 0 < 0.3
    t[0] = 0.1
    assert c.update(1, "a", "xy", False) is None     # 0.1 - 0 < 0.3
    t[0] = 0.4
    assert c.update(1, "a", "xyz", False) == "a: xyz"  # 0.4 - 0 >= 0.3


def test_final_always_emits_regardless_of_throttle():
    t = [0.0]
    c = CaptionComposer(throttle_ms=300, clock=lambda: t[0])
    assert c.update(1, "a", "done", True) == "a: done"


def test_max_chars_keeps_tail():
    c = CaptionComposer(throttle_ms=0, max_chars=10, clock=_Clock())
    c.update(1, "", "one two three four five", True)
    assert len(c.current()) <= 10


def test_two_speakers_most_recent_first():
    c = CaptionComposer(throttle_ms=0, max_lines=2, clock=_Clock())
    c.update(1, "A", "hi", True)
    out = c.update(2, "B", "yo", True)
    assert out.splitlines() == ["B: yo", "A: hi"]


def test_tail_cuts_on_word_boundary():
    assert _tail("one two three four five", 10) == "four five"


def test_file_sink_overwrites(tmp_path):
    p = tmp_path / "cap.txt"
    sink = FileSink(str(p))
    sink.emit("שלום")
    assert p.read_text(encoding="utf-8") == "שלום"
    sink.emit("world")
    assert p.read_text(encoding="utf-8") == "world"


def test_stdout_sink_flattens_newlines(capsys):
    StdoutSink().emit("a\nb")
    assert "a | b" in capsys.readouterr().out


def test_build_sink_file(tmp_path):
    sink = build_sink(LiveConfig(sink="file", file={"path": str(tmp_path / "c.txt")}))
    assert isinstance(sink, FileSink)


def test_config_live_section():
    cfg = Config.from_dict(
        {"live": {"enabled": True, "sink": "obs", "obs": {"source": "cap"}, "throttle_ms": 200}}
    )
    assert cfg.live.enabled is True
    assert cfg.live.sink == "obs"
    assert cfg.live.obs["source"] == "cap"
    assert cfg.live.throttle_ms == 200
