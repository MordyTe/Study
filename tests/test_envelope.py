import json

from agent_play.envelope import (
    ENVELOPE_VERSION,
    AgentPlayError,
    Delivery,
    ErrorCode,
    Response,
)


def test_ok_envelope_shape():
    envelope = Response.ok("click", {"action": "click"})
    assert envelope == {"version": ENVELOPE_VERSION, "ok": True, "command": "click", "data": {"action": "click"}}
    line = Response.to_json(envelope)
    assert "\n" not in line
    assert json.loads(line)["ok"] is True


def test_error_envelope_carries_code_disposition_and_recovery():
    error = AgentPlayError(ErrorCode.STALE_REF, "gone", "snapshot again", {"kind": "saved_ref_absent"})
    envelope = Response.err("click", error)
    assert envelope["ok"] is False and "data" not in envelope
    payload = envelope["error"]
    assert payload["code"] == "STALE_REF"
    assert payload["suggestion"] == "snapshot again"
    assert payload["details"] == {"kind": "saved_ref_absent"}
    assert payload["disposition"] == {"delivery": "not_delivered", "retry": "safe"}
    assert payload["recovery"]["requires_fresh_snapshot"] is True


def test_retry_is_derived_from_delivery():
    assert Delivery.NOT_DELIVERED.retry == "safe"
    assert Delivery.DELIVERED_UNVERIFIED.retry == "unsafe"
    assert Delivery.DELIVERED_VERIFIED.retry == "unsafe"
    assert Delivery.DELIVERY_UNCERTAIN.retry == "unsafe"
    assert Delivery.UNKNOWN.retry == "unknown"


def test_recovery_hint_absent_when_action_may_have_landed():
    error = AgentPlayError(ErrorCode.TIMEOUT, "slow", delivery=Delivery.DELIVERY_UNCERTAIN)
    payload = error.to_dict()
    assert "recovery" not in payload
    assert payload["disposition"]["retry"] == "unsafe"
