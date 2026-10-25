"""Custom vocabulary / glossary handling.

A glossary is a plain-text file, one term per line (host and guest names,
show names, Hebrew spellings, and English brand/tech terms). It feeds two
accuracy mechanisms:

* Whisper ``initial_prompt`` biasing (see
  :func:`build_initial_prompt`) — nudges the decoder toward the right spelling
  of names and English terms without any training.
* The gated LLM post-correction pass, which is told the house spelling of these
  terms so it restores them instead of inventing plausible-but-wrong Hebrew.

Pure stdlib.
"""

from __future__ import annotations

from typing import List


def load_glossary(path: str) -> List[str]:
    """Load terms from a file, skipping blanks and ``#`` comment lines.

    Order is preserved and duplicates are removed (case-insensitively).
    """

    terms: List[str] = []
    seen = set()
    with open(path, "r", encoding="utf-8") as handle:
        for raw in handle:
            term = raw.strip()
            if not term or term.startswith("#"):
                continue
            key = term.lower()
            if key in seen:
                continue
            seen.add(key)
            terms.append(term)
    return terms


def build_initial_prompt(terms: List[str], max_chars: int = 800) -> str:
    """Join glossary terms into a Whisper ``initial_prompt``.

    Whisper's prompt has a limited window (~224 tokens); an over-long prompt
    hurts more than it helps, so the list is truncated at a term boundary to at
    most ``max_chars`` characters.
    """

    prompt = ""
    for term in terms:
        candidate = term if not prompt else f"{prompt}, {term}"
        if len(candidate) > max_chars:
            break
        prompt = candidate
    return prompt
