from __future__ import annotations

import hashlib
import hmac
import json

from enoch_control_plane.callback_signing import (
    SIGNATURE_HEADER,
    SIGNATURE_PREFIX,
    TIMESTAMP_HEADER,
    signature_headers,
)


def _verify_signature(body: bytes, *, secret: str, headers: dict[str, str]) -> bool:
    observed = headers.get(SIGNATURE_HEADER, "")
    timestamp = headers.get(TIMESTAMP_HEADER, "")
    if not observed.startswith(SIGNATURE_PREFIX) or not timestamp:
        return False
    signed = b".".join([timestamp.encode("ascii"), body])
    expected = (
        SIGNATURE_PREFIX
        + hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    )
    return hmac.compare_digest(observed, expected)


def test_signature_headers_emit_expected_hmac_and_timestamp() -> None:
    body = b'{"run_id":"run-1","gate_state":"wake_ready"}'
    timestamp = 1_718_888_123

    headers = signature_headers(body, secret="callback-secret", timestamp=timestamp)

    signed = b".".join([str(timestamp).encode("ascii"), body])
    expected_digest = hmac.new(b"callback-secret", signed, hashlib.sha256).hexdigest()
    assert headers == {
        TIMESTAMP_HEADER: str(timestamp),
        SIGNATURE_HEADER: f"{SIGNATURE_PREFIX}{expected_digest}",
    }


def test_signature_headers_are_absent_without_secret() -> None:
    assert signature_headers(b"{}", secret="", timestamp=1_718_888_123) == {}


def test_signature_round_trip_accepts_original_body_and_rejects_tampering() -> None:
    payload = {"run_id": "run-1", "gate_state": "wake_ready"}
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    headers = signature_headers(body, secret="callback-secret", timestamp=1_718_888_123)

    assert _verify_signature(body, secret="callback-secret", headers=headers)

    tampered_body = json.dumps(
        {**payload, "gate_state": "gate_error"}, sort_keys=True
    ).encode("utf-8")
    assert not _verify_signature(
        tampered_body, secret="callback-secret", headers=headers
    )
    assert not _verify_signature(body, secret="wrong-secret", headers=headers)


def test_signature_verifier_rejects_missing_prefix_or_timestamp() -> None:
    body = b'{"run_id":"run-1"}'
    headers = signature_headers(body, secret="callback-secret", timestamp=1_718_888_123)

    without_prefix = dict(headers)
    without_prefix[SIGNATURE_HEADER] = without_prefix[SIGNATURE_HEADER].removeprefix(
        SIGNATURE_PREFIX
    )
    assert not _verify_signature(body, secret="callback-secret", headers=without_prefix)

    without_timestamp = dict(headers)
    without_timestamp.pop(TIMESTAMP_HEADER)
    assert not _verify_signature(
        body, secret="callback-secret", headers=without_timestamp
    )
