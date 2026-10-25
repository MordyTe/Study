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
    level,
    load_settings,
    mix_down,
    new_transcript_path,
    resample,
    save_settings,
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


def test_mix_down_stereo_averages():
    stereo = np.array([[1.0, 0.0], [0.5, 0.5]], dtype=np.float32)
    assert np.allclose(mix_down(stereo), [0.5, 0.5])


def test_mix_down_multichannel_keeps_single_mic_loud():
    # 32-channel mixer interface, only channel 3 has a mic signal.
    data = np.zeros((1000, 32), dtype=np.float32)
    data[:, 3] = 0.2
    assert np.allclose(mix_down(data), 0.2)  # averaging would give 0.00625


def test_mix_down_multichannel_clips():
    data = np.full((10, 8), 0.5, dtype=np.float32)
    assert mix_down(data).max() == 1.0


def test_level_scale():
    assert level(np.zeros(1000, np.float32)) == 0.0
    assert level(np.ones(1000, np.float32)) == 1.0
    mid = level(np.full(1000, 0.03, np.float32))  # about -30 dB
    assert 0.3 < mid < 0.7


def test_settings_roundtrip_and_corrupt_file(tmp_path):
    p = str(tmp_path / "settings.json")
    assert load_settings(p) == {}  # missing file -> defaults
    save_settings(p, {"source": "🎙️ מיקסר"})
    assert load_settings(p) == {"source": "🎙️ מיקסר"}
    with open(p, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert load_settings(p) == {}  # corrupt -> defaults, no crash
