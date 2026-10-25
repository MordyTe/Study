import os
import sys
from datetime import datetime

import pytest

np = pytest.importorskip("numpy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import (  # noqa: E402
    TARGET_SR,
    Chunker,
    TranscriptWriter,
    format_line,
    new_transcript_path,
    resample,
    to_mono,
)


def _tone(seconds, amp=0.2):
    return np.full(int(seconds * TARGET_SR), amp, dtype=np.float32)


def _silence(seconds):
    return np.zeros(int(seconds * TARGET_SR), dtype=np.float32)


def test_to_mono_averages_channels():
    stereo = np.array([[1.0, 0.0], [0.5, 0.5]], dtype=np.float32)
    assert np.allclose(to_mono(stereo), [0.5, 0.5])


def test_resample_48k_to_16k_length():
    out = resample(np.ones(48000, np.float32), 48000, 16000)
    assert out.size == 16000


def test_resample_non_integer_ratio_length():
    out = resample(np.ones(44100, np.float32), 44100, 16000)
    assert out.size == 16000


def test_chunker_cuts_on_pause():
    c = Chunker()
    chunks = c.feed(np.concatenate([_tone(2.0), _silence(1.0)]))
    assert len(chunks) == 1
    assert chunks[0].size >= 2 * TARGET_SR


def test_chunker_ignores_pure_silence():
    c = Chunker()
    assert c.feed(_silence(10.0)) == []
    assert c.flush() is None


def test_chunker_caps_long_speech():
    c = Chunker(max_s=5.0)
    chunks = c.feed(_tone(12.0))
    assert len(chunks) == 2  # 2 x 5s emitted, 2s still buffered
    assert c.flush() is not None


def test_chunker_handles_small_pieces():
    c = Chunker()
    out = []
    audio = np.concatenate([_tone(1.5), _silence(1.0)])
    for i in range(0, audio.size, 1600):  # 100 ms blocks, like the capture loop
        out += c.feed(audio[i : i + 1600])
    assert len(out) == 1


def test_short_word_is_not_lost():
    # A short answer like "כן" followed by a pause must still be transcribed.
    c = Chunker(min_s=1.0)
    chunks = c.feed(np.concatenate([_tone(0.3), _silence(1.0)]))
    assert len(chunks) == 1


def test_short_word_waits_for_pause():
    # No pause yet -> keep buffering, don't cut mid-sentence.
    c = Chunker()
    assert c.feed(_tone(0.5)) == []


def test_format_line():
    assert format_line(" שלום ", datetime(2026, 1, 1, 9, 5, 7)) == "[09:05:07] שלום"


def test_writer_appends(tmp_path):
    path = new_transcript_path(str(tmp_path / "t"), datetime(2026, 1, 1, 9, 5))
    assert os.path.basename(path).endswith("2026-01-01_09-05.txt")
    w = TranscriptWriter(path)
    w.write_line("א")
    w.write_line("ב")
    with open(path, encoding="utf-8") as f:
        assert f.read() == "א\nב\n"
