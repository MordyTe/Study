"""The JSON envelope every command prints, and the error and delivery vocabulary.

Mirrors agent-desktop's contract (docs/REVERSE_ENGINEERING.md §2.1, §2.6): callers branch on `code`
and `disposition`, never on message text. Only `not_delivered` is safe to retry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

ENVELOPE_VERSION = "1.0"


class ErrorCode(str, Enum):
    PERM_DENIED = "PERM_DENIED"
    ELEMENT_NOT_FOUND = "ELEMENT_NOT_FOUND"
    APP_NOT_FOUND = "APP_NOT_FOUND"
    ACTION_FAILED = "ACTION_FAILED"
    ACTION_NOT_SUPPORTED = "ACTION_NOT_SUPPORTED"
    STALE_REF = "STALE_REF"
    AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"
    WINDOW_NOT_FOUND = "WINDOW_NOT_FOUND"
    PLATFORM_NOT_SUPPORTED = "PLATFORM_NOT_SUPPORTED"
    TIMEOUT = "TIMEOUT"
    INVALID_ARGS = "INVALID_ARGS"
    SNAPSHOT_NOT_FOUND = "SNAPSHOT_NOT_FOUND"
    POLICY_DENIED = "POLICY_DENIED"
    PERCEPTION_FAILED = "PERCEPTION_FAILED"
    MODEL_REFUSED = "MODEL_REFUSED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    INTERNAL = "INTERNAL"


class Delivery(str, Enum):
    """How far an action got. The retry disposition is derived, never set independently."""

    UNKNOWN = "unknown"
    NOT_DELIVERED = "not_delivered"
    DELIVERY_UNCERTAIN = "delivery_uncertain"
    DELIVERED_UNVERIFIED = "delivered_unverified"
    DELIVERED_VERIFIED = "delivered_verified"

    @property
    def retry(self) -> str:
        if self is Delivery.NOT_DELIVERED:
            return "safe"
        if self is Delivery.UNKNOWN:
            return "unknown"
        return "unsafe"

    def to_dict(self) -> dict[str, str]:
        return {"delivery": self.value, "retry": self.retry}


RECOVERY_BY_CODE: dict[ErrorCode, dict[str, Any]] = {
    ErrorCode.STALE_REF: {
        "strategy": "refresh_snapshot_then_retry_original",
        "retryable": True,
        "requires_fresh_snapshot": True,
    },
    ErrorCode.SNAPSHOT_NOT_FOUND: {
        "strategy": "refresh_snapshot_then_retry_original",
        "retryable": True,
        "requires_fresh_snapshot": True,
    },
    ErrorCode.AMBIGUOUS_TARGET: {
        "strategy": "choose_a_unique_target_or_use_coordinates",
        "retryable": False,
        "requires_fresh_snapshot": True,
    },
    ErrorCode.POLICY_DENIED: {
        "strategy": "request_explicit_policy_then_retry_original",
        "retryable": True,
        "requires_fresh_snapshot": False,
    },
    ErrorCode.TIMEOUT: {
        "strategy": "inspect_state_then_retry_original",
        "retryable": True,
        "requires_fresh_snapshot": True,
        "retry_after_ms": 250,
    },
    ErrorCode.PERCEPTION_FAILED: {
        "strategy": "observe_again",
        "retryable": True,
        "requires_fresh_snapshot": True,
    },
}


@dataclass
class AgentPlayError(Exception):
    """An error with the fields the envelope needs. Raised anywhere, rendered once in the CLI."""

    code: ErrorCode
    message: str
    suggestion: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    delivery: Delivery = Delivery.NOT_DELIVERED

    def __str__(self) -> str:
        return f"{self.code.value}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code.value, "message": self.message}
        if self.suggestion:
            payload["suggestion"] = self.suggestion
        recovery = RECOVERY_BY_CODE.get(self.code)
        if recovery and self.delivery is Delivery.NOT_DELIVERED:
            payload["recovery"] = dict(recovery)
        if self.details:
            payload["details"] = dict(self.details)
        payload["disposition"] = self.delivery.to_dict()
        return payload


class Response:
    """Builds the one-line envelope. `data` and `error` are mutually exclusive."""

    @staticmethod
    def ok(command: str, data: dict[str, Any]) -> dict[str, Any]:
        return {"version": ENVELOPE_VERSION, "ok": True, "command": command, "data": data}

    @staticmethod
    def err(command: str, error: AgentPlayError) -> dict[str, Any]:
        return {"version": ENVELOPE_VERSION, "ok": False, "command": command, "error": error.to_dict()}

    @staticmethod
    def to_json(envelope: dict[str, Any]) -> str:
        return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=False)


def invalid_args(message: str, suggestion: str | None = None, **details: Any) -> AgentPlayError:
    return AgentPlayError(ErrorCode.INVALID_ARGS, message, suggestion, details)
