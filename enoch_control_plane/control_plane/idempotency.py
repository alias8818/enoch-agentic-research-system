from __future__ import annotations

import json
from typing import Any, Mapping

from ..enoch_core.store import IdempotencyConflict

WORKER_CALLBACK_AUDIT_KEYS = frozenset(
    {
        "delivered_at",
        "received_by",
        "seen_at",
        "applied_status",
        "applied_next_action_hint",
        "stale_callback_ignored",
        "late_callback_ignored",
        "ignore_reason",
        "current_run_id",
        "current_last_run_state",
    }
)


def worker_callback_identity_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return callback payload fields that define retry identity.

    Store backends append audit/state fields to callback events. Those fields can
    legitimately differ when the same worker callback is replayed later, so the
    replay comparison must ignore them consistently across SQLite and Supabase.
    """

    return {
        key: value
        for key, value in payload.items()
        if key not in WORKER_CALLBACK_AUDIT_KEYS
    }


def parse_event_payload_object(
    raw_payload: Any, *, idempotency_key: str
) -> dict[str, Any]:
    if isinstance(raw_payload, dict):
        return raw_payload
    try:
        parsed = json.loads(raw_payload or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise IdempotencyConflict(
            f"idempotency key {idempotency_key!r} has unreadable payload"
        ) from exc
    if not isinstance(parsed, dict):
        raise IdempotencyConflict(
            f"idempotency key {idempotency_key!r} has non-object payload"
        )
    return parsed


def assert_same_worker_callback_payload(
    *,
    idempotency_key: str,
    existing_payload: Mapping[str, Any],
    incoming_payload: Mapping[str, Any],
) -> None:
    if worker_callback_identity_payload(
        existing_payload
    ) != worker_callback_identity_payload(incoming_payload):
        raise IdempotencyConflict(
            f"idempotency key {idempotency_key!r} was reused with different callback payload"
        )
