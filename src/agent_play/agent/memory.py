"""Working memory: the task, a goal stack, notes, lessons learned from failures, recent events."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STATUS_MARK = {"pending": "[ ]", "active": "[>]", "done": "[x]", "blocked": "[!]"}


@dataclass
class Objective:
    text: str
    status: str = "pending"

    def to_dict(self) -> dict[str, str]:
        return {"text": self.text, "status": self.status}


@dataclass
class WorkingMemory:
    task: str
    objectives: list[Objective] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    lessons: list[str] = field(default_factory=list)
    recent: deque = field(default_factory=lambda: deque(maxlen=10))
    stale_by_name: dict[str, int] = field(default_factory=dict)
    unverified_by_name: dict[str, int] = field(default_factory=dict)
    steps: int = 0
    actions: int = 0

    def set_objectives(self, items: list[dict[str, str]]) -> None:
        self.objectives = [Objective(str(item.get("text", "")).strip(), str(item.get("status", "pending"))) for item in items if str(item.get("text", "")).strip()]

    def add_note(self, note: str) -> None:
        note = note.strip()
        if note and note not in self.notes:
            self.notes.append(note)
            if len(self.notes) > 20:
                self.notes.pop(0)

    def add_lesson(self, lesson: str) -> None:
        if lesson not in self.lessons:
            self.lessons.append(lesson)

    def record_event(self, line: str) -> None:
        self.recent.append(line)

    def record_action_result(self, action: str, target: str | None, delivery: str, reason: str | None) -> None:
        self.actions += 1
        key = f"{action}:{target or '-'}"
        self.record_event(f"{key} -> {delivery}" + (f" ({reason})" if reason else ""))
        if delivery == "delivered_unverified":
            count = self.unverified_by_name[key] = self.unverified_by_name.get(key, 0) + 1
            if count == 3:
                self.add_lesson(f"{key} has produced no visible change three times; the target may not react to this action, try another approach.")
        else:
            self.unverified_by_name.pop(key, None)

    def record_action_error(self, action: str, target: str | None, code: str) -> None:
        self.actions += 1
        key = f"{action}:{target or '-'}"
        self.record_event(f"{key} -> error {code}")
        if code == "STALE_REF":
            count = self.stale_by_name[target or "-"] = self.stale_by_name.get(target or "-", 0) + 1
            if count == 2:
                self.add_lesson(f"Refs for {target} go stale quickly; observe immediately before acting on it.")

    def render(self) -> str:
        lines = [f"Task: {self.task}"]
        if self.objectives:
            lines.append("Objectives:")
            lines.extend(f"  {STATUS_MARK.get(o.status, '[ ]')} {o.text}" for o in self.objectives)
        else:
            lines.append("Objectives: none yet (call set_objectives once you understand the screen).")
        if self.notes:
            lines.append("Notes:")
            lines.extend(f"  - {note}" for note in self.notes[-10:])
        if self.lessons:
            lines.append("Lessons:")
            lines.extend(f"  - {lesson}" for lesson in self.lessons[-6:])
        if self.recent:
            lines.append("Recent actions:")
            lines.extend(f"  - {line}" for line in list(self.recent)[-6:])
        lines.append(f"Progress: step {self.steps}, {self.actions} actions so far.")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "objectives": [o.to_dict() for o in self.objectives],
            "notes": list(self.notes),
            "lessons": list(self.lessons),
            "recent": list(self.recent),
            "steps": self.steps,
            "actions": self.actions,
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def load(path: Path) -> "WorkingMemory":
        data = json.loads(path.read_text(encoding="utf-8"))
        memory = WorkingMemory(task=data["task"])
        memory.set_objectives(data.get("objectives", []))
        memory.notes = list(data.get("notes", []))
        memory.lessons = list(data.get("lessons", []))
        for line in data.get("recent", []):
            memory.recent.append(line)
        memory.steps = int(data.get("steps", 0))
        memory.actions = int(data.get("actions", 0))
        return memory
