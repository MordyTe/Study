from studio_transcribe.normalize_he import (
    collapse_whitespace,
    normalize_display,
    normalize_for_wer,
    normalize_quotes,
    strip_bidi,
    strip_niqqud,
)


def test_strip_niqqud_removes_vowel_points():
    # "שָׁלוֹם" (with niqqud) -> "שלום"
    assert strip_niqqud("שָׁלוֹם") == "שלום"


def test_strip_bidi_removes_control_marks():
    assert strip_bidi("‏שלום‎") == "שלום"


def test_normalize_quotes_maps_geresh_and_gershayim():
    assert normalize_quotes("צ׳ ר״ל") == "צ' ר\"ל"
    assert normalize_quotes("“hi” ’x‘") == '"hi" \'x\''


def test_collapse_whitespace():
    assert collapse_whitespace("  a\t b\n c ") == "a b c"


def test_normalize_display_keeps_letters_drops_bidi():
    assert normalize_display("‏שלום   עולם‎") == "שלום עולם"


def test_normalize_for_wer_drops_punctuation_and_lowercases():
    assert normalize_for_wer("Hello, WORLD!") == "hello world"


def test_normalize_for_wer_hebrew_is_comparable():
    # Same words, one side has niqqud, bidi marks, and punctuation.
    ref = "‏שָׁלום, עולם!"
    hyp = "שלום עולם"
    assert normalize_for_wer(ref) == normalize_for_wer(hyp)
