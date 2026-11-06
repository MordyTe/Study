"""Skills: the instructions the model reads. Markdown files in this package, loaded by name."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from agent_play.envelope import AgentPlayError, ErrorCode


def _root() -> Path:
    return Path(str(resources.files("agent_play.skills")))


def list_skills() -> list[str]:
    root = _root()
    names = [p.stem for p in root.glob("*.md")]
    names += [f"genres/{p.stem}" for p in (root / "genres").glob("*.md")]
    return sorted(names)


def load_skill(name: str) -> str:
    path = _root() / f"{name}.md"
    if not path.exists():
        raise AgentPlayError(ErrorCode.INVALID_ARGS, f"Unknown skill {name!r}", f"Available: {', '.join(list_skills())}")
    return path.read_text(encoding="utf-8")
