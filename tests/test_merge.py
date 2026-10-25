from studio_transcribe.merge import (
    default_speaker_name,
    merge_timeline,
    speaker_totals,
    tag_speakers,
)
from studio_transcribe.models import ChannelResult, Segment


def _seg(start, end, text):
    return Segment(start=start, end=end, text=text)


def test_tag_speakers_uses_map_then_default():
    results = [
        ChannelResult(channel=1, segments=[_seg(0, 1, "a")]),
        ChannelResult(channel=2, segments=[_seg(0, 1, "b")]),
    ]
    tagged = tag_speakers(results, {1: "מנחה"})
    by_channel = {s.channel: s.speaker for s in tagged}
    assert by_channel[1] == "מנחה"
    assert by_channel[2] == default_speaker_name(2)


def test_merge_timeline_sorted_by_start():
    results = [
        ChannelResult(channel=1, segments=[_seg(5, 6, "late"), _seg(0, 1, "early")]),
        ChannelResult(channel=2, segments=[_seg(2, 3, "mid")]),
    ]
    merged = merge_timeline(results)
    assert [s.text for s in merged] == ["early", "mid", "late"]


def test_merge_joins_same_speaker_within_gap():
    results = [
        ChannelResult(
            channel=1,
            segments=[_seg(0.0, 1.0, "שלום"), _seg(1.3, 2.0, "עולם")],
        )
    ]
    merged = merge_timeline(results, {1: "מנחה"}, join_gap=0.8)
    assert len(merged) == 1
    assert merged[0].text == "שלום עולם"
    assert merged[0].start == 0.0
    assert merged[0].end == 2.0


def test_merge_does_not_join_across_speakers():
    results = [
        ChannelResult(channel=1, segments=[_seg(0.0, 1.0, "a")]),
        ChannelResult(channel=2, segments=[_seg(1.1, 2.0, "b")]),
    ]
    merged = merge_timeline(results, {1: "x", 2: "y"}, join_gap=0.8)
    assert len(merged) == 2


def test_merge_does_not_join_beyond_gap():
    results = [
        ChannelResult(channel=1, segments=[_seg(0.0, 1.0, "a"), _seg(3.0, 4.0, "b")])
    ]
    merged = merge_timeline(results, {1: "x"}, join_gap=0.8)
    assert len(merged) == 2


def test_speaker_totals():
    results = [
        ChannelResult(channel=1, segments=[_seg(0, 2, "a"), _seg(4, 5, "b")]),
        ChannelResult(channel=2, segments=[_seg(0, 1, "c")]),
    ]
    totals = speaker_totals(merge_timeline(results, {1: "x", 2: "y"}))
    assert totals["x"] == 3.0
    assert totals["y"] == 1.0
