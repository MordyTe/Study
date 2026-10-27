"""Tests for hebrew_text.core. Import ``core`` only — never ``server`` (needs mcp). No network."""
import pytest

from .. import core

FUNCS = [core.normalize, core.parse_hebrew_date, core.gematria]

# --------------------------------------------------------------------------- shared contract


@pytest.mark.parametrize("fn", FUNCS)
def test_empty_string_is_ok(fn):
    r = fn("")
    assert r["ok"] is True
    assert "error" not in r


def test_empty_results_are_empty():
    assert core.normalize("")["text"] == ""
    assert core.gematria("") == {"ok": True, "value": 0, "letters": 0, "ignored": []}
    d = core.parse_hebrew_date("")
    assert d["ok"] is True and d["day"] is None and d["month"] is None and d["year"] is None


@pytest.mark.parametrize("fn", FUNCS)
@pytest.mark.parametrize("bad", [None, 42, 1.5, b"\xd7\x90", ["a"], {"text": "a"}])
def test_none_and_non_str_are_invalid_input(fn, bad):
    r = fn(bad)
    assert r["ok"] is False
    assert r["error"] == "invalid_input"
    assert isinstance(r["message"], str)


@pytest.mark.parametrize("fn", FUNCS)
def test_input_too_large(fn):
    r = fn("א" * (core.MAX_INPUT_CHARS + 1))
    assert r["ok"] is False
    assert r["error"] == "input_too_large"
    assert r["limit"] == 100_000


@pytest.mark.parametrize("fn", FUNCS)
def test_input_at_limit_does_not_raise(fn):
    r = fn("א " * (core.MAX_INPUT_CHARS // 2))
    assert isinstance(r, dict) and "ok" in r


def test_never_raises_wrapper_converts_exceptions():
    @core.never_raises
    def boom(_):
        raise ZeroDivisionError("x")

    r = boom("y")
    assert r["ok"] is False and r["error"] == "internal_error" and "ZeroDivisionError" in r["message"]


# --------------------------------------------------------------------------- normalize


def test_normalize_strips_niqqud_and_teamim():
    # shin dot, qamats, dagesh, holam, cantillation (U+0596 tipeha)
    assert core.normalize("שָׁל֖וֹם")["text"] == "שלום"
    assert core.normalize("בְּרֵאשִׁ֖ית בָּרָ֣א")["text"] == "בראשית ברא"


def test_normalize_precomposed_presentation_form():
    # U+FB2A HEBREW LETTER SHIN WITH SHIN DOT -> plain shin
    assert core.normalize("שׁלום")["text"] == "שלום"


def test_normalize_hebrew_geresh_and_gershayim_to_ascii():
    assert core.normalize("צה״ל")["text"] == 'צה"ל'
    assert core.normalize("ח׳")["text"] == "ח'"


def test_normalize_curly_quotes_to_ascii():
    assert core.normalize("“שלום” ‘עולם’")["text"] == "\"שלום\" 'עולם'"


def test_normalize_ascii_quotes_are_untouched():
    assert core.normalize('צה"ל ח\'')["text"] == 'צה"ל ח\''


def test_normalize_removes_bidi_marks():
    assert core.normalize("‏שלום‎ ‫עולם‬")["text"] == "שלום עולם"


def test_normalize_collapses_whitespace():
    assert core.normalize("  שלום \t  עולם  ")["text"] == "שלום עולם"
    assert core.normalize("א  \n\n  ב")["text"] == "א\n\nב"


def test_normalize_mixed_hebrew_english():
    r = core.normalize("Hello  שָׁלוֹם, world! ״OK״")
    assert r == {"ok": True, "text": 'Hello שלום, world! "OK"'}


def test_normalize_keeps_maqaf_and_latin_accents():
    assert core.normalize("בית־ספר café")["text"] == "בית־ספר café"


# --------------------------------------------------------------------------- parse_hebrew_date


def test_parse_date_spec_example():
    r = core.parse_hebrew_date("כ״ג בתשרי תשפ״ו")
    assert r["ok"] is True
    assert (r["day"], r["month"], r["month_index"], r["year"]) == (23, "תשרי", 1, 5786)


def test_parse_date_ascii_gershayim_and_no_bet_prefix():
    r = core.parse_hebrew_date('כ"ג תשרי תשפ"ו')
    assert (r["day"], r["month"], r["month_index"], r["year"]) == (23, "תשרי", 1, 5786)


def test_parse_date_without_quotes_at_all():
    r = core.parse_hebrew_date("כג בתשרי תשפו")
    assert (r["day"], r["year"]) == (23, 5786)


def test_parse_date_year_without_thousands_gets_5000():
    assert core.parse_hebrew_date("א׳ בניסן תש״ם")["year"] == 5740
    assert core.parse_hebrew_date("א׳ בניסן ה׳תש״ם")["year"] == 5740
    assert core.parse_hebrew_date("א׳ בניסן התש״ם")["year"] == 5740


def test_parse_date_year_is_optional():
    r = core.parse_hebrew_date("ט״ו בשבט")
    assert r["ok"] is True and r["day"] == 15 and r["month"] == "שבט" and r["year"] is None


def test_parse_date_invalid_day_lamed_bet():
    r = core.parse_hebrew_date("ל״ב בתשרי")
    assert r["ok"] is False
    assert r["error"] == "invalid_date"


def test_parse_date_day_30_in_29_day_month_is_invalid():
    r = core.parse_hebrew_date("ל׳ בטבת תשפ״ו")
    assert r["ok"] is False and r["error"] == "invalid_date"


def test_parse_date_adar_ii():
    r = core.parse_hebrew_date("י״ד באדר ב׳ תשפ״ד")
    assert r["ok"] is True
    assert (r["day"], r["month"], r["month_index"], r["year"]) == (14, "אדר ב׳", 13, 5784)
    assert r["leap_year"] is True
    assert core.parse_hebrew_date("יד אדר ב תשפד")["month"] == "אדר ב׳"


def test_parse_date_adar_i_and_plain_adar():
    r1 = core.parse_hebrew_date("י״ד באדר א׳ תשפ״ד")
    assert (r1["month"], r1["month_index"]) == ("אדר א׳", 6)
    r2 = core.parse_hebrew_date("י״ד באדר תשפ״ו")
    assert (r2["month"], r2["month_index"], r2["leap_year"]) == ("אדר", 6, False)


@pytest.mark.parametrize(
    "text, month, index",
    [
        ("א׳ בחשון", "חשוון", 2),
        ("א׳ במרחשוון", "חשוון", 2),
        ("א׳ בכסלו", "כסלו", 3),
        ("א׳ באייר", "אייר", 8),
        ("א׳ בסיון", "סיוון", 9),
        ("א׳ במנחם־אב", "אב", 11),
        ("א׳ באלול", "אלול", 12),
    ],
)
def test_parse_date_month_aliases(text, month, index):
    r = core.parse_hebrew_date(text)
    assert (r["month"], r["month_index"]) == (month, index)


def test_parse_date_inside_sentence_with_niqqud():
    r = core.parse_hebrew_date("יום שלישי, כ״ג בְּתִשְׁרֵי תשפ״ו בבוקר")
    assert (r["day"], r["month"], r["year"]) == (23, "תשרי", 5786)


def test_parse_date_no_date_found():
    r = core.parse_hebrew_date("hello world")
    assert r["ok"] is False and r["error"] == "invalid_date"


def test_parse_date_digits():
    r = core.parse_hebrew_date("23 תשרי 5786")
    assert (r["day"], r["year"]) == (23, 5786)


def test_leap_year_cycle():
    assert [y for y in range(5782, 5801) if core.is_leap_year(y)] == [5782, 5784, 5787, 5790, 5793, 5795, 5798]


# --------------------------------------------------------------------------- gematria


def test_gematria_spec_example():
    r = core.gematria("תשפ״ו")
    assert r["ok"] is True and r["value"] == 786


def test_gematria_final_letters_equal_regular():
    assert core.gematria("ך")["value"] == core.gematria("כ")["value"] == 20
    assert core.gematria("שלום")["value"] == core.gematria("שלומ")["value"] == 376


def test_gematria_ignores_and_reports_non_hebrew():
    r = core.gematria("חי = 18!")
    assert r["value"] == 18
    assert r["letters"] == 2
    assert r["ignored"] == ["=", "1", "8", "!"]


def test_gematria_mixed_hebrew_english():
    r = core.gematria("abc אב")
    assert r["value"] == 3 and set(r["ignored"]) == {"a", "b", "c"}


def test_gematria_skips_niqqud_quotes_and_spaces_silently():
    r = core.gematria("שָׁלוֹם  צה״ל ח' ‏")
    assert r["value"] == 376 + 125 + 8  # שלום + צה"ל + ח
    assert r["ignored"] == []
