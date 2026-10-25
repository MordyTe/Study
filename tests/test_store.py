from studio_transcribe.models import Segment
from studio_transcribe.store import TranscriptStore, _fts_match_query


def _seg(channel, speaker, start, end, text):
    return Segment(start=start, end=end, text=text, speaker=speaker, channel=channel)


def _populate(store):
    sid = store.create_session("פרק 1", source="rec/")
    store.add_segments(
        sid,
        [
            _seg(1, "מנחה", 0.0, 1.5, "שלום וברוכים הבאים לתוכנית"),
            _seg(2, "אורח", 1.6, 3.0, "hello everyone welcome"),
            _seg(1, "מנחה", 3.1, 4.0, "נדבר היום על Dante"),
        ],
    )
    return sid


def test_create_and_search_text(tmp_path):
    with TranscriptStore(str(tmp_path / "s.db")) as store:
        _populate(store)
        hits = store.search("Dante")
        assert len(hits) == 1
        assert hits[0]["speaker"] == "מנחה"
        assert "Dante" in hits[0]["text"]


def test_search_hebrew_term(tmp_path):
    with TranscriptStore(str(tmp_path / "s.db")) as store:
        _populate(store)
        hits = store.search("שלום")
        assert len(hits) == 1
        assert hits[0]["channel"] == 1


def test_search_filter_by_speaker(tmp_path):
    with TranscriptStore(str(tmp_path / "s.db")) as store:
        _populate(store)
        hits = store.search("welcome", speaker="אורח")
        assert len(hits) == 1
        assert store.search("welcome", speaker="מנחה") == []


def test_get_session_segments_ordered(tmp_path):
    with TranscriptStore(str(tmp_path / "s.db")) as store:
        sid = _populate(store)
        segs = store.get_session_segments(sid)
        assert [s["start"] for s in segs] == [0.0, 1.6, 3.1]


def test_like_fallback_path(tmp_path):
    """Force the non-FTS path and confirm search still works."""

    store = TranscriptStore(str(tmp_path / "s.db"))
    store.fts_enabled = False
    sid = store.create_session("x")
    store.add_segments(sid, [_seg(1, "a", 0, 1, "unique_token_here")])
    hits = store.search("unique_token_here")
    assert len(hits) == 1
    store.close()


def test_fts_match_query_quoting():
    assert _fts_match_query("a b") == '"a" "b"'
    assert _fts_match_query('say "hi"') == '"say" """hi"""'
    assert _fts_match_query("   ") == '""'
