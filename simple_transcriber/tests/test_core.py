import os
import sys
from datetime import datetime

import pytest

np = pytest.importorskip("numpy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import (  # noqa: E402
    TARGET_SR,
    Chunker,
    channel_levels,
    channels_for,
    TranscriptWriter,
    build_device_list,
    collapse_repeats,
    is_loopback_name,
    keep_segment,
    normalize_gain,
    pick_default,
    format_line,
    level,
    load_settings,
    mix_down,
    new_transcript_path,
    resample,
    save_settings,
    select_channels,
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


def test_select_channels_picks_1_based_and_ignores_out_of_range():
    data = np.arange(12, dtype=np.float32).reshape(3, 4)  # 4 channels
    out = select_channels(data, [2, 4, 9])
    assert out.shape == (3, 2)
    assert np.allclose(out[:, 0], data[:, 1]) and np.allclose(out[:, 1], data[:, 3])


def test_channel_levels_per_channel():
    data = np.zeros((1000, 3), np.float32)
    data[:, 1] = 0.2
    lv = channel_levels(data)
    assert lv[0] == 0.0 and lv[2] == 0.0 and lv[1] > 0.5


def test_channels_for_defaults_and_saved_choice():
    assert channels_for({}, "mixer", 4) == [1, 2, 3, 4]
    s = {"channels": {"mixer": [3, 1, 99]}}
    assert channels_for(s, "mixer", 32) == [1, 3]       # 99 dropped, sorted
    assert channels_for(s, "other", 2) == [1, 2]        # other device -> all
    assert channels_for({"channels": {"m": [7]}}, "m", 2) == [1, 2]  # nothing valid -> all


def test_format_line_with_speaker():
    assert format_line("שלום", datetime(2026, 1, 1, 9, 5, 7), "ערוץ 3") == "[09:05:07] ערוץ 3: שלום"


HOSTAPIS = [
    {"name": "MME", "default_input_device": 0},
    {"name": "Windows DirectSound", "default_input_device": 3},
    {"name": "Windows WASAPI", "default_input_device": 5},
    {"name": "ASIO", "default_input_device": 8},
]


def _dev(index, name, api, ins, sr=48000):
    return {"index": index, "name": name, "hostapi": api, "max_input_channels": ins,
            "default_samplerate": sr}


DEVICES = [
    _dev(0, "Microsoft Sound Mapper - Input", 0, 2),
    _dev(1, "Microphone (Realtek(R) Audio)", 0, 2),      # MME duplicate of WASAPI 5
    _dev(2, "Stereo Mix (Realtek(R) Audio)", 0, 2),      # = the speakers
    _dev(3, "Primary Sound Capture Driver", 1, 2),
    _dev(4, "Microphone (Realtek(R) Audio)", 1, 2),      # DirectSound duplicate
    _dev(5, "Microphone (Realtek(R) Audio)", 2, 2),
    _dev(6, "Stereo Mix (Realtek(R) Audio)", 2, 2),
    _dev(7, "Speakers (Realtek(R) Audio)", 2, 0),        # output only
    _dev(8, "X-USB ASIO Driver", 3, 32),
    _dev(9, "Line (USB Audio CODEC)", 0, 2),             # MME-only device -> kept
]


def test_device_list_inputs_only_no_speakers_no_duplicates():
    entries = build_device_list(DEVICES, HOSTAPIS)
    keys = [e["key"] for e in entries]
    assert keys == [
        "ASIO|X-USB ASIO Driver",                  # ASIO first: all 32 channels
        "WASAPI|Microphone (Realtek(R) Audio)",
        "MME|Line (USB Audio CODEC)",
    ]
    assert entries[0]["channels"] == 32
    assert all("Stereo Mix" not in k for k in keys)


def test_is_loopback_name():
    assert is_loopback_name("Stereo Mix (Realtek)")
    assert is_loopback_name("מיקס סטריאו (Realtek)")
    assert not is_loopback_name("Microphone (USB)")


def test_pick_default_saved_then_windows_default_then_first():
    entries = build_device_list(DEVICES, HOSTAPIS)
    assert pick_default(entries, "MME|Line (USB Audio CODEC)", HOSTAPIS)["index"] == 9
    assert pick_default(entries, "gone", HOSTAPIS)["index"] == 5  # WASAPI default input
    assert pick_default([], None, HOSTAPIS) is None


def test_keep_segment_drops_invented_text():
    assert keep_segment("שלום לכולם", avg_logprob=-0.2, no_speech_prob=0.05)
    assert not keep_segment("...", avg_logprob=-0.1)
    assert not keep_segment("משהו", avg_logprob=-1.3)                       # very unsure
    assert not keep_segment("משהו", avg_logprob=-0.6, no_speech_prob=0.8)   # silence
    assert not keep_segment("א א א א א א", compression_ratio=3.0)          # loop
    assert not keep_segment("תודה שצפיתם!", avg_logprob=-0.5, no_speech_prob=0.3)
    # a real, confidently heard "תודה רבה" is kept
    assert keep_segment("תודה רבה", avg_logprob=-0.15, no_speech_prob=0.02)


def test_collapse_repeats():
    assert collapse_repeats("שלום שלום שלום שלום שלום עולם") == "שלום עולם"
    assert collapse_repeats("לא לא לא") == "לא לא לא"
    assert collapse_repeats("אני חושב אני חושב אני חושב אני חושב ש") == "אני חושב ש"


def test_normalize_gain_boosts_quiet_never_attenuates():
    quiet = np.full(100, 0.05, np.float32)
    assert abs(float(normalize_gain(quiet).max()) - 0.4) < 1e-6   # capped at 8x
    loud = np.full(100, 0.9, np.float32)
    assert float(normalize_gain(loud).max()) == np.float32(0.9)
    assert normalize_gain(np.zeros(10, np.float32)).max() == 0.0
