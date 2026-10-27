"""hebrew_text.core — pure functions for Hebrew text. Stdlib only, no network, no I/O.

Public API (each returns a dict and never raises):
* normalize(text)          -> {"ok": True, "text": str}
* parse_hebrew_date(text)  -> {"ok": True, "day", "month", "month_index", "month_en", "year", "leap_year"}
* gematria(text)           -> {"ok": True, "value": int, "letters": int, "ignored": [str]}

Failure shape: {"ok": False, "error": <code>, "message": <text>, ...}
Error codes: invalid_input, input_too_large, invalid_date, internal_error.
"""
from __future__ import annotations

import functools
import re
import unicodedata

MAX_INPUT_CHARS = 100_000

# --------------------------------------------------------------------------- result helpers


def ok(**fields) -> dict:
    result = {"ok": True}
    result.update(fields)
    return result


def err(code: str, message: str, **fields) -> dict:
    result = {"ok": False, "error": code, "message": message}
    result.update(fields)
    return result


def check_text(text) -> dict | None:
    """Return an error dict if ``text`` is not acceptable input, otherwise None."""
    if not isinstance(text, str):
        return err("invalid_input", f"expected str, got {type(text).__name__}")
    if len(text) > MAX_INPUT_CHARS:
        return err(
            "input_too_large",
            f"input has {len(text)} characters; the limit is {MAX_INPUT_CHARS}",
            limit=MAX_INPUT_CHARS,
        )
    return None


def never_raises(fn):
    """Last line of defence: turn an unexpected exception into an error result."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - the contract is "no exceptions"
            return err("internal_error", f"{type(exc).__name__}: {exc}")

    return wrapper


# --------------------------------------------------------------------------- unicode tables

# Hebrew points and accents (niqqud + te'amim), U+0591..U+05C7.
# Assumption: U+05BE MAQAF (the Hebrew hyphen) is *kept* — it is punctuation, not a mark,
# and stripping it would glue words together ("בית־ספר" -> "ביתספר").
_MARKS_RE = re.compile(r"[֑-ֽֿ-ׇ]")

# Directional formatting characters: LRM/RLM, LRE/RLE/PDF/LRO/RLO, plus the
# isolates (U+2066..U+2069) and the Arabic letter mark, which serve the same purpose.
_BIDI_RE = re.compile(r"[‎‏‪-‮⁦-⁩؜]")

# Hebrew geresh/gershayim and typographic quotes -> ASCII ' and ".
_QUOTE_MAP = str.maketrans({
    "׳": "'",  # ׳ HEBREW PUNCTUATION GERESH
    "״": '"',  # ״ HEBREW PUNCTUATION GERSHAYIM
    "‘": "'", "’": "'", "‚": "'", "‛": "'",  # ‘ ’ ‚ ‛
    "“": '"', "”": '"', "„": '"', "‟": '"',  # “ ” „ ‟
})

_HSPACE_RE = re.compile(r"[^\S\n]+")        # any whitespace except newline
_NEWLINE_EDGE_RE = re.compile(r" *\n *")    # spaces around a newline

# Standard gematria (mispar hechrechi). Final letters equal their regular forms.
_LETTER_VALUES = {
    "א": 1, "ב": 2, "ג": 3, "ד": 4, "ה": 5, "ו": 6, "ז": 7, "ח": 8, "ט": 9,
    "י": 10, "כ": 20, "ל": 30, "מ": 40, "נ": 50, "ס": 60, "ע": 70, "פ": 80, "צ": 90,
    "ק": 100, "ר": 200, "ש": 300, "ת": 400,
    "ך": 20, "ם": 40, "ן": 50, "ף": 80, "ץ": 90,
}
_FINALS = str.maketrans({"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"})

# Characters that gematria skips silently (part of Hebrew writing, not "foreign"):
# whitespace, points/accents, geresh/gershayim (Hebrew and ASCII), maqaf, bidi marks.
_SILENT_IN_GEMATRIA = set("׳״'\"־‎‏‪‫‬‭‮⁦⁧⁨⁩؜")

# --------------------------------------------------------------------------- hebrew calendar tables

# Tishrei-first numbering with a *stable* index per month (same scheme as pyluach):
# Adar / Adar I = 6, Nisan is always 7, Adar II = 13.
_MONTHS = [
    # canonical, index, english, aliases (already normalized, no quotes)
    ("תשרי", 1, "Tishrei", ("תשרי",)),
    ("חשוון", 2, "Cheshvan", ("חשוון", "חשון", "מרחשוון", "מרחשון")),
    ("כסלו", 3, "Kislev", ("כסלו", "כסליו")),
    ("טבת", 4, "Tevet", ("טבת",)),
    ("שבט", 5, "Shevat", ("שבט",)),
    ("אדר", 6, "Adar", ("אדר",)),
    ("ניסן", 7, "Nisan", ("ניסן",)),
    ("אייר", 8, "Iyar", ("אייר", "איר")),
    ("סיוון", 9, "Sivan", ("סיוון", "סיון")),
    ("תמוז", 10, "Tammuz", ("תמוז",)),
    ("אב", 11, "Av", ("אב",)),
    ("אלול", 12, "Elul", ("אלול",)),
    ("אדר א׳", 6, "Adar I", ()),
    ("אדר ב׳", 13, "Adar II", ()),
]
_MONTH_INFO = {name: (index, english) for name, index, english, _ in _MONTHS}
_MONTH_ALIASES = {alias: name for name, _, _, aliases in _MONTHS for alias in aliases}
# Two-token month names: ("מנחם", "אב"), ("מר", "חשוון")
_MONTH_PAIRS = {("מנחם", "אב"): "אב", ("מר", "חשוון"): "חשוון", ("מר", "חשון"): "חשוון"}
_ADAR_I_SUFFIXES = {"א", "ראשון"}
_ADAR_II_SUFFIXES = {"ב", "שני"}
# Months that always have 29 days. Cheshvan/Kislev vary (29/30) and are not checked.
_ALWAYS_29 = {"טבת", "אייר", "תמוז", "אלול", "אדר ב׳"}

_TENS = {10: "י", 20: "כ", 30: "ל"}
_UNITS = {1: "א", 2: "ב", 3: "ג", 4: "ד", 5: "ה", 6: "ו", 7: "ז", 8: "ח", 9: "ט"}


def _day_numerals() -> dict:
    table = {}
    for n in range(1, 31):
        tens, units = divmod(n, 10)
        table[_TENS.get(tens * 10, "") + _UNITS.get(units, "")] = n
    table["טו"] = 15  # ט״ו, ט״ז are written this way to avoid spelling the divine name
    table["טז"] = 16
    return table


_DAY_NUMERALS = _day_numerals()

# Strict Hebrew numeral: hundreds (ת* then one of ק/ר/ש), tens, units — or ט״ו/ט״ז.
_NUMERAL_RE = re.compile(r"^(ת*[קרש]?)(?:([יכלמנסעפצ]?)([אבגדהוזחט]?)|(טו|טז))$")
_TOKEN_RE = re.compile(r"[א-ת'\"0-9]+")
_THOUSANDS_RE = re.compile(r"^([א-ט])'(.*)$")


def _strip_quotes(token: str) -> str:
    return token.replace("'", "").replace('"', "")


def _numeral_value(letters: str) -> int | None:
    """Value of a strictly-formed Hebrew numeral (finals already mapped), or None."""
    if not letters or not _NUMERAL_RE.match(letters):
        return None
    return sum(_LETTER_VALUES[ch] for ch in letters)


def is_leap_year(year: int) -> bool:
    """Hebrew leap year test (19-year Metonic cycle)."""
    return (7 * year + 1) % 19 < 7


def _parse_day(token: str) -> int | None:
    if token.isdigit():
        n = int(token)
        return n if 1 <= n <= 30 else None
    return _DAY_NUMERALS.get(_strip_quotes(token))


def _parse_month(tokens: list, i: int) -> tuple[str, int] | None:
    """Try to read a month name at tokens[i]. Returns (canonical_name, tokens_consumed)."""
    raw = _strip_quotes(tokens[i])
    candidates = [raw]
    if len(raw) > 1 and raw[0] in "בל":  # ב' / ל' prepositions: בתשרי, לתשרי
        candidates.append(raw[1:])
    nxt = _strip_quotes(tokens[i + 1]) if i + 1 < len(tokens) else None
    for cand in candidates:
        name, used = None, 1
        if cand in _MONTH_ALIASES:
            name = _MONTH_ALIASES[cand]
        elif nxt is not None and (cand, nxt) in _MONTH_PAIRS:
            name, used = _MONTH_PAIRS[(cand, nxt)], 2
        if name is None:
            continue
        if name == "אדר" and nxt is not None:
            if nxt in _ADAR_I_SUFFIXES:
                name, used = "אדר א׳", 2
            elif nxt in _ADAR_II_SUFFIXES:
                name, used = "אדר ב׳", 2
        return name, used
    return None


def _parse_year(tokens: list, i: int) -> tuple[int, int] | None:
    """Try to read a year at tokens[i]. Returns (year, tokens_consumed)."""
    token = tokens[i]
    if token.isdigit():
        n = int(token)
        if 1 <= n < 1000:
            return n + 5000, 1
        if 1000 <= n <= 9999:
            return n, 1
        return None
    used = 1
    thousands = None
    m = _THOUSANDS_RE.match(token)  # ה'תשפ"ו  /  ה' תשפ"ו
    if m:
        thousands, rest = _LETTER_VALUES[m.group(1)], m.group(2)
        if rest == "":
            if i + 1 >= len(tokens):
                return None
            rest, used = tokens[i + 1], 2
    else:
        rest = token
    letters = _strip_quotes(rest).translate(_FINALS)
    if thousands is None and len(letters) >= 2 and letters[0] == "ה":
        # "התשפו": a numeral never *starts* with ה unless it is the thousands prefix.
        thousands, letters = 5, letters[1:]
    value = _numeral_value(letters)
    if not value:
        return None
    return (thousands if thousands is not None else 5) * 1000 + value, used


# --------------------------------------------------------------------------- public API


@never_raises
def normalize(text: str) -> dict:
    """Strip niqqud/te'amim and bidi marks, unify quotes to ASCII, collapse whitespace."""
    bad = check_text(text)
    if bad:
        return bad
    s = unicodedata.normalize("NFD", text)   # splits precomposed forms such as U+FB2A שׁ
    s = _MARKS_RE.sub("", s)
    s = _BIDI_RE.sub("", s)
    s = s.translate(_QUOTE_MAP)
    s = unicodedata.normalize("NFC", s)      # recompose non-Hebrew accents (é) we split above
    s = _HSPACE_RE.sub(" ", s)
    s = _NEWLINE_EDGE_RE.sub("\n", s)
    return ok(text=s.strip())


@never_raises
def parse_hebrew_date(text: str) -> dict:
    """Parse the first "day month [year]" Hebrew date found in ``text``."""
    bad = check_text(text)
    if bad:
        return bad
    if not text.strip():
        return ok(day=None, month=None, month_index=None, month_en=None, year=None, leap_year=None)
    s = normalize(text)["text"].replace("־", " ").replace("-", " ")
    tokens = _TOKEN_RE.findall(s)
    bad_day = None
    for i in range(len(tokens) - 1):
        month = _parse_month(tokens, i + 1)
        if month is None:
            continue
        day = _parse_day(tokens[i])
        if day is None:
            bad_day = bad_day or tokens[i]
            continue
        name, used = month
        j = i + 1 + used
        year = None
        if j < len(tokens):
            parsed = _parse_year(tokens, j)
            if parsed:
                year = parsed[0]
        leap = is_leap_year(year) if year is not None else None
        max_day = 29 if name in _ALWAYS_29 or (name == "אדר" and leap is False) else 30
        if day > max_day:
            return err("invalid_date", f"{name} has at most {max_day} days, got {day}")
        index, english = _MONTH_INFO[name]
        return ok(day=day, month=name, month_index=index, month_en=english, year=year, leap_year=leap)
    if bad_day is not None:
        return err("invalid_date", f"'{bad_day}' is not a valid day of month (1-30)")
    return err("invalid_date", "no Hebrew date (day, month[, year]) found in the input")


@never_raises
def gematria(text: str) -> dict:
    """Standard gematria of the Hebrew letters in ``text``; non-Hebrew characters are ignored."""
    bad = check_text(text)
    if bad:
        return bad
    total = letters = 0
    ignored: list[str] = []
    seen: set[str] = set()
    for ch in text:
        value = _LETTER_VALUES.get(ch)
        if value is not None:
            total += value
            letters += 1
            continue
        if ch.isspace() or ch in _SILENT_IN_GEMATRIA or "֑" <= ch <= "ׇ":
            continue
        if ch not in seen:
            seen.add(ch)
            ignored.append(ch)
    return ok(value=total, letters=letters, ignored=ignored)
