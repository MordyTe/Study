"""Durable knowledge: notes the agent keeps across runs and sessions, loaded into its prompt.

Working memory (`agent/memory.py`) lives for one run. This store lives under the state root and
holds what the agent learned for good: a rule of a game, a lesson, a fact the user taught it.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

MAX_PROMPT_CHARS = 8000


def _slug(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.strip().lower()).strip("-")
    return slug[:60] or "notes"


class KnowledgeStore:
    def __init__(self, root: Path | None) -> None:
        self.dir = (root / "knowledge") if root else None
        self._memory: dict[str, str] = {}
        if self.dir is not None:
            self.dir.mkdir(parents=True, exist_ok=True)

    def add(self, topic: str, text: str) -> str:
        slug = _slug(topic)
        stamp = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
        entry = f"- ({stamp}) {text.strip()}\n"
        if self.dir is None:
            self._memory[slug] = self._memory.get(slug, f"# {topic.strip()}\n\n") + entry
            return slug
        path = self.dir / f"{slug}.md"
        if not path.exists():
            path.write_text(f"# {topic.strip()}\n\n", encoding="utf-8")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(entry)
        return slug

    def topics(self) -> list[str]:
        if self.dir is None:
            return sorted(self._memory)
        return sorted(path.stem for path in self.dir.glob("*.md"))

    def read(self, topic: str) -> str | None:
        slug = _slug(topic)
        if self.dir is None:
            return self._memory.get(slug)
        path = self.dir / f"{slug}.md"
        return path.read_text(encoding="utf-8") if path.exists() else None

    def render(self, max_chars: int = MAX_PROMPT_CHARS) -> str:
        """Newest notes first, cut at max_chars so the prompt stays bounded."""
        parts: list[str] = []
        if self.dir is None:
            items = sorted(self._memory.items())
        else:
            paths = sorted(self.dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
            items = [(path.stem, path.read_text(encoding="utf-8")) for path in paths]
        total = 0
        for _, text in items:
            if total + len(text) > max_chars:
                parts.append(text[: max(0, max_chars - total)] + "\n[knowledge truncated]")
                break
            parts.append(text.rstrip())
            total += len(text)
        return "\n\n".join(parts)
