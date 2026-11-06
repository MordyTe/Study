"""Interaction policy: what the executor may do and how carefully it must check first."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from agent_play.envelope import AgentPlayError, ErrorCode


@dataclass
class InteractionPolicy:
    headed: bool = False
    allow_coordinates: bool = True
    require_reidentify: bool = True
    fingerprint_threshold: float = 0.6
    twin_max_distance_px: float = 64.0
    settle_ms: int = 250
    max_actions_per_minute: int = 120
    blocked_actions: set[str] = field(default_factory=set)
    _recent: deque = field(default_factory=deque, repr=False)

    def check_action(self, action: str) -> None:
        if action in self.blocked_actions:
            raise AgentPlayError(ErrorCode.POLICY_DENIED, f"Action {action!r} is blocked by policy", details={"action": action})
        if action in ("mouse_click",) and not self.allow_coordinates:
            raise AgentPlayError(ErrorCode.POLICY_DENIED, "Coordinate clicks are disabled by policy", "Act on a ref from a snapshot instead")
        now = time.monotonic()
        while self._recent and now - self._recent[0] > 60.0:
            self._recent.popleft()
        if len(self._recent) >= self.max_actions_per_minute:
            raise AgentPlayError(
                ErrorCode.POLICY_DENIED,
                f"Rate limit of {self.max_actions_per_minute} actions per minute reached",
                "Wait, then continue; raise max_actions_per_minute if the game needs it",
            )
        self._recent.append(now)
