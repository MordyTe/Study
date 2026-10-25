from studio_transcribe.eval_wer import cer, corpus_wer, wer


def test_perfect_match_is_zero():
    assert wer("the cat sat", "the cat sat")["wer"] == 0.0


def test_single_substitution():
    r = wer("the cat sat", "the dog sat")
    assert r["substitutions"] == 1
    assert r["deletions"] == 0
    assert r["insertions"] == 0
    assert r["ref_len"] == 3
    assert abs(r["wer"] - 1 / 3) < 1e-9


def test_deletion_and_insertion():
    assert wer("a b c", "a c")["deletions"] == 1
    assert wer("a c", "a b c")["insertions"] == 1


def test_wer_applies_normalization():
    # Punctuation/case differences must not count as errors.
    assert wer("Shalom, Olam!", "shalom olam")["wer"] == 0.0


def test_hebrew_niqqud_does_not_count_as_error():
    r = wer("שָׁלוֹם עולם", "שלום עולם")
    assert r["wer"] == 0.0


def test_empty_reference_with_hypothesis_is_full_error():
    assert wer("", "something here")["wer"] == 1.0


def test_cer_counts_characters():
    r = cer("abc", "abd")
    assert r["ref_len"] == 3
    assert abs(r["cer"] - 1 / 3) < 1e-9


def test_corpus_wer_sums_before_dividing():
    pairs = [("a b", "a b"), ("c d e f", "c x e f")]
    r = corpus_wer(pairs)
    # 1 error out of 6 reference words total.
    assert r["errors"] == 1
    assert r["ref_len"] == 6
    assert abs(r["wer"] - 1 / 6) < 1e-9
