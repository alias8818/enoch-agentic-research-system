import pytest

from enoch_control_plane.control_plane.idempotency import (
    WORKER_CALLBACK_AUDIT_KEYS,
    assert_same_worker_callback_payload,
    parse_event_payload_object,
    worker_callback_identity_payload,
)
from enoch_control_plane.enoch_core.store import IdempotencyConflict


def test_worker_callback_identity_ignores_shared_audit_keys() -> None:
    payload = {
        "run_id": "run-1",
        "status": "wake_ready",
        "applied_status": "completed",
        "received_by": "control-plane",
    }

    assert "applied_status" in WORKER_CALLBACK_AUDIT_KEYS
    assert worker_callback_identity_payload(payload) == {
        "run_id": "run-1",
        "status": "wake_ready",
    }


def test_worker_callback_identity_comparison_rejects_real_payload_drift() -> None:
    assert_same_worker_callback_payload(
        idempotency_key="callback:run-1",
        existing_payload={"run_id": "run-1", "status": "wake_ready"},
        incoming_payload={
            "run_id": "run-1",
            "status": "wake_ready",
            "received_by": "later-audit-surface",
        },
    )

    with pytest.raises(IdempotencyConflict, match="different callback payload"):
        assert_same_worker_callback_payload(
            idempotency_key="callback:run-1",
            existing_payload={"run_id": "run-1", "status": "wake_ready"},
            incoming_payload={"run_id": "run-1", "status": "failed"},
        )


def test_parse_event_payload_object_accepts_dict_or_json_and_rejects_arrays() -> None:
    assert parse_event_payload_object({"ok": True}, idempotency_key="k") == {"ok": True}
    assert parse_event_payload_object('{"ok": true}', idempotency_key="k") == {
        "ok": True
    }

    with pytest.raises(IdempotencyConflict, match="non-object payload"):
        parse_event_payload_object("[]", idempotency_key="k")
