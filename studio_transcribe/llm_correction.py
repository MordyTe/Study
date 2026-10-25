"""Gated LLM post-correction.

Only segments flagged *low confidence* (by avg log-prob / compression ratio)
are sent to the LLM, which is instructed to fix **only** spelling, punctuation,
English-term spelling and number formatting — never to rephrase. This caps the
main risk of LLM correction: "fixing" text that was already acoustically
correct (over-correction). A safety check rejects a correction whose length
deviates too far from the original.

The Anthropic SDK is imported lazily; if it (or the key) is missing, correction
is a no-op and the originals are returned unchanged.
"""

from __future__ import annotations

from typing import Callable, List, Optional

from .config import Config
from .models import Segment
from .normalize_he import normalize_for_wer

_SYSTEM_PROMPT = (
    "You are a transcript proofreader for Hebrew/English studio speech. "
    "Fix ONLY: spelling, punctuation, spelling of English brand/tech terms, and "
    "number formatting. Do NOT rephrase, translate, add, or remove words. "
    "If the text is already fine, return it unchanged. "
    "Return ONLY the corrected line, with no quotes or commentary."
)


def _length_ok(original: str, corrected: str, tolerance: float = 0.4) -> bool:
    """Reject corrections that change the word count too much (over-correction)."""

    o = len(normalize_for_wer(original).split())
    c = len(normalize_for_wer(corrected).split())
    if o == 0:
        return c == 0
    return abs(c - o) / o <= tolerance


def _default_anthropic_caller(model: str) -> Optional[Callable[[str, str], str]]:
    try:
        import anthropic  # type: ignore
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic()
    except Exception:
        return None

    def call(system: str, user: str) -> str:
        msg = client.messages.create(
            model=model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(
            block.text for block in msg.content if getattr(block, "type", "") == "text"
        ).strip()

    return call


def correct_segments(
    segments: List[Segment],
    config: Config,
    glossary_terms: Optional[List[str]] = None,
    caller: Optional[Callable[[str, str], str]] = None,
) -> List[Segment]:
    """Return segments with low-confidence ones corrected in place.

    ``caller(system, user) -> text`` lets callers inject any LLM (or a stub for
    testing). If not provided, the Anthropic SDK is used when available.
    """

    cfg = config.llm_correction
    if not cfg.enabled:
        return segments

    caller = caller or _default_anthropic_caller(cfg.model)
    if caller is None:
        return segments  # no LLM available -> leave transcript untouched

    glossary_line = ""
    if glossary_terms:
        glossary_line = "Known correct spellings: " + ", ".join(glossary_terms) + "\n"

    for seg in segments:
        if not seg.is_low_confidence(
            cfg.logprob_threshold, cfg.compression_ratio_threshold
        ):
            continue
        user = f"{glossary_line}Line: {seg.text}"
        try:
            corrected = caller(_SYSTEM_PROMPT, user)
        except Exception:
            continue  # never fail the pipeline on a correction error
        if corrected and _length_ok(seg.text, corrected):
            seg.text = corrected
    return segments
