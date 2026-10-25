from studio_transcribe.config import Config
from studio_transcribe.llm_correction import _length_ok, correct_segments
from studio_transcribe.models import Segment


def _cfg(enabled=True):
    return Config.from_dict({"llm_correction": {"enabled": enabled}})


def test_disabled_is_noop():
    segs = [Segment(0, 1, "raw", avg_logprob=-2.0)]
    out = correct_segments(segs, _cfg(enabled=False), caller=lambda s, u: "CHANGED")
    assert out[0].text == "raw"


def test_only_low_confidence_segments_corrected():
    good = Segment(0, 1, "good text here", avg_logprob=-0.1, compression_ratio=1.2)
    bad = Segment(1, 2, "bad text here", avg_logprob=-2.0)
    calls = []

    def caller(system, user):
        calls.append(user)
        return "fixed text here"

    correct_segments([good, bad], _cfg(), caller=caller)
    assert good.text == "good text here"  # untouched
    assert bad.text == "fixed text here"  # corrected
    assert len(calls) == 1


def test_overcorrection_rejected_by_length_guard():
    bad = Segment(0, 1, "one two three", avg_logprob=-2.0)
    # Caller tries to balloon the line — should be rejected, original kept.
    correct_segments([bad], _cfg(), caller=lambda s, u: "a b c d e f g h i j")
    assert bad.text == "one two three"


def test_length_ok_helper():
    assert _length_ok("a b c", "a b c")
    assert _length_ok("a b c", "a b c d")  # within 40% tolerance
    assert not _length_ok("a b c", "a b c d e f")  # +100% -> rejected


def test_caller_exception_keeps_original():
    bad = Segment(0, 1, "keep me", avg_logprob=-2.0)

    def boom(system, user):
        raise RuntimeError("api down")

    correct_segments([bad], _cfg(), caller=boom)
    assert bad.text == "keep me"
