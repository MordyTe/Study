from studio_transcribe.export import _fmt_timestamp, to_srt, to_txt, to_vtt
from studio_transcribe.models import Segment


def _segs():
    return [
        Segment(start=0.0, end=1.5, text="שלום", speaker="מנחה"),
        Segment(start=2.0, end=3.25, text="hello", speaker="אורח"),
    ]


def test_fmt_timestamp_srt_and_vtt():
    assert _fmt_timestamp(3661.5, ",") == "01:01:01,500"
    assert _fmt_timestamp(3661.5, ".") == "01:01:01.500"
    assert _fmt_timestamp(-1, ",") == "00:00:00,000"


def test_to_srt_structure():
    out = to_srt(_segs())
    lines = out.strip().splitlines()
    assert lines[0] == "1"
    assert lines[1] == "00:00:00,000 --> 00:00:01,500"
    assert lines[2] == "מנחה: שלום"
    assert "2" in out
    assert "00:00:02,000 --> 00:00:03,250" in out


def test_to_vtt_has_header():
    out = to_vtt(_segs())
    assert out.startswith("WEBVTT")
    assert "00:00:02.000 --> 00:00:03.250" in out


def test_to_txt_speaker_lines():
    out = to_txt(_segs())
    assert out.splitlines() == ["מנחה: שלום", "אורח: hello"]


def test_to_txt_without_speaker():
    out = to_txt(_segs(), with_speaker=False)
    assert out.splitlines() == ["שלום", "hello"]


def test_empty_exports_do_not_crash():
    assert to_srt([]) == ""
    assert to_vtt([]).startswith("WEBVTT")
    assert to_txt([]) == ""
