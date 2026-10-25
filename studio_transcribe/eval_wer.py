"""Word Error Rate / Character Error Rate measurement.

The whole accuracy strategy rests on *measuring* accuracy on the studio's own
audio, not on vendor claims. This module implements a dependency-free
Levenshtein alignment over tokens, with the ivrit.ai-style normalization applied
to both reference and hypothesis (see :mod:`studio_transcribe.normalize_he`).

Usage::

    from studio_transcribe.eval_wer import wer
    result = wer(reference_text, hypothesis_text)
    print(result["wer"], result["substitutions"], ...)
"""

from __future__ import annotations

from typing import Callable, Dict, List

from .normalize_he import normalize_for_wer


def _align_counts(ref: List[str], hyp: List[str]) -> Dict[str, int]:
    """Return substitution/deletion/insertion counts via edit-distance backtrace."""

    n, m = len(ref), len(hyp)
    # d[i][j] = edit distance between ref[:i] and hyp[:j]
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        ref_i = ref[i - 1]
        row = d[i]
        prev = d[i - 1]
        for j in range(1, m + 1):
            if ref_i == hyp[j - 1]:
                row[j] = prev[j - 1]
            else:
                row[j] = 1 + min(prev[j - 1], prev[j], row[j - 1])

    i, j = n, m
    sub = dele = ins = 0
    while i > 0 and j > 0:
        if ref[i - 1] == hyp[j - 1] and d[i][j] == d[i - 1][j - 1]:
            i -= 1
            j -= 1
        elif d[i][j] == d[i - 1][j - 1] + 1:
            sub += 1
            i -= 1
            j -= 1
        elif d[i][j] == d[i - 1][j] + 1:
            dele += 1
            i -= 1
        else:
            ins += 1
            j -= 1
    dele += i  # remaining reference tokens are deletions
    ins += j  # remaining hypothesis tokens are insertions
    return {"substitutions": sub, "deletions": dele, "insertions": ins}


def _error_rate(
    reference: str,
    hypothesis: str,
    tokens: Callable[[str], List[str]],
    normalizer: Callable[[str], str],
) -> Dict[str, float]:
    ref = tokens(normalizer(reference))
    hyp = tokens(normalizer(hypothesis))
    counts = _align_counts(ref, hyp)
    errors = counts["substitutions"] + counts["deletions"] + counts["insertions"]
    ref_len = len(ref)
    rate = errors / ref_len if ref_len else (0.0 if not hyp else 1.0)
    return {
        "wer": rate,
        "errors": errors,
        "ref_len": ref_len,
        "hyp_len": len(hyp),
        **counts,
    }


def wer(
    reference: str,
    hypothesis: str,
    normalizer: Callable[[str], str] = normalize_for_wer,
) -> Dict[str, float]:
    """Word Error Rate between ``reference`` and ``hypothesis`` (0.0 = perfect)."""

    return _error_rate(reference, hypothesis, str.split, normalizer)


def cer(
    reference: str,
    hypothesis: str,
    normalizer: Callable[[str], str] = normalize_for_wer,
) -> Dict[str, float]:
    """Character Error Rate (whitespace collapsed to single spaces)."""

    result = _error_rate(reference, hypothesis, list, normalizer)
    result["cer"] = result.pop("wer")
    return result


def corpus_wer(
    pairs,
    normalizer: Callable[[str], str] = normalize_for_wer,
) -> Dict[str, float]:
    """Aggregate WER over many ``(reference, hypothesis)`` pairs.

    Errors and reference lengths are summed before dividing, which is the
    correct way to combine WER across files (not an average of per-file rates).
    """

    tot_err = tot_ref = tot_hyp = tot_sub = tot_del = tot_ins = 0
    for reference, hypothesis in pairs:
        r = wer(reference, hypothesis, normalizer)
        tot_err += r["errors"]
        tot_ref += r["ref_len"]
        tot_hyp += r["hyp_len"]
        tot_sub += r["substitutions"]
        tot_del += r["deletions"]
        tot_ins += r["insertions"]
    return {
        "wer": tot_err / tot_ref if tot_ref else 0.0,
        "errors": tot_err,
        "ref_len": tot_ref,
        "hyp_len": tot_hyp,
        "substitutions": tot_sub,
        "deletions": tot_del,
        "insertions": tot_ins,
    }
