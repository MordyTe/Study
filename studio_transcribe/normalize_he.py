"""Hebrew (and mixed Hebrew/English) text normalization.

Two jobs:

1. **Display normalization** (:func:`normalize_display`) — clean text for the
   archive/export without destroying meaning: strip bidi control marks, map the
   Hebrew geresh/gershayim to ASCII quotes, collapse whitespace. Niqqud is kept
   only if present (it rarely is in ASR output).

2. **WER normalization** (:func:`normalize_for_wer`) — reproduce the ivrit.ai
   leaderboard normalization so measured WER is comparable to published
   numbers: strip niqqud + cantillation, strip bidi marks, map geresh/gershayim,
   lowercase, drop punctuation, collapse whitespace. **Both the reference and
   the hypothesis must go through this** or the error rate is inflated by
   formatting-only mismatches.

Pure stdlib (``re`` + ``unicodedata``).
"""

from __future__ import annotations

import re
import unicodedata

# Hebrew niqqud (vowel points) and cantillation marks occupy U+0591–U+05C7.
_NIQQUD_RE = re.compile(r"[֑-ׇ]")

# Bidirectional formatting control characters that leak into RTL text.
_BIDI_RE = re.compile(r"[‎‏‪-‮⁦-⁩؜]")

_GERESH = "׳"  # ׳  Hebrew punctuation geresh
_GERSHAYIM = "״"  # ״  Hebrew punctuation gershayim

_WS_RE = re.compile(r"\s+")


def strip_niqqud(text: str) -> str:
    """Remove Hebrew vowel points and cantillation marks."""

    return _NIQQUD_RE.sub("", text)


def strip_bidi(text: str) -> str:
    """Remove Unicode bidirectional formatting control characters."""

    return _BIDI_RE.sub("", text)


def normalize_quotes(text: str) -> str:
    """Map Hebrew geresh/gershayim and common curly quotes to ASCII ``'`` / ``"``."""

    return (
        text.replace(_GERSHAYIM, '"')
        .replace(_GERESH, "'")
        .replace("‘", "'")
        .replace("’", "'")
        .replace("“", '"')
        .replace("”", '"')
    )


def collapse_whitespace(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def normalize_display(text: str) -> str:
    """Light cleanup suitable for the stored/exported transcript."""

    text = strip_bidi(text)
    text = normalize_quotes(text)
    return collapse_whitespace(text)


def _strip_punctuation(text: str) -> str:
    """Replace every Unicode punctuation/symbol code point with a space."""

    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat.startswith("P") or cat.startswith("S"):
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def normalize_for_wer(text: str) -> str:
    """Aggressive normalization for WER/CER measurement (ivrit.ai style)."""

    text = strip_bidi(text)
    text = normalize_quotes(text)
    text = strip_niqqud(text)
    text = text.lower()
    text = _strip_punctuation(text)
    return collapse_whitespace(text)
