from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from enoch_control_plane.callback_signing import (
    SIGNATURE_HEADER,
    SIGNATURE_NONCE_HEADER,
    SIGNATURE_PREFIX,
    SIGNATURE_VERSION,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
    signature_headers,
    verify_signature,
)


def test_signature_headers_emit_expected_versioned_hmac_timestamp_and_nonce() -> None:
    body = b'{"run_id":"run-1","gate_state":"wake_ready"}'
    timestamp = 1_718_888_123

    headers = signature_headers(
        body, secret="callback-secret", timestamp=timestamp, nonce="nonce-1"
    )

    signed = b".".join(
        [
            SIGNATURE_VERSION.encode("ascii"),
            str(timestamp).encode("ascii"),
            b"nonce-1",
            body,
        ]
    )
    expected_digest = hmac.new(b"callback-secret", signed, hashlib.sha256).hexdigest()
    assert headers == {
        SIGNATURE_VERSION_HEADER: SIGNATURE_VERSION,
        SIGNATURE_NONCE_HEADER: "nonce-1",
        TIMESTAMP_HEADER: str(timestamp),
        SIGNATURE_HEADER: f"{SIGNATURE_PREFIX}{expected_digest}",
    }


def test_signature_headers_are_absent_without_secret() -> None:
    assert signature_headers(b"{}", secret="", timestamp=1_718_888_123) == {}


def test_signature_verifier_allows_optional_no_secret_mode() -> None:
    assert verify_signature(b"{}", headers={}, secret="")


@pytest.mark.parametrize("secret", [" padded", "padded ", "x" * 257])
def test_signature_headers_reject_misconfigured_secrets(secret: str) -> None:
    with pytest.raises(ValueError, match="callback signing secret"):
        signature_headers(b"{}", secret=secret, timestamp=1_718_888_123)


def test_signature_round_trip_accepts_original_body_and_rejects_tampering() -> None:
    payload = {"run_id": "run-1", "gate_state": "wake_ready"}
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    headers = signature_headers(
        body, secret="callback-secret", timestamp=1_718_888_123, nonce="nonce-1"
    )

    assert verify_signature(
        body,
        headers=headers,
        secret="callback-secret",
        now=1_718_888_133,
        max_age_sec=300,
    )

    tampered_body = json.dumps(
        {**payload, "gate_state": "gate_error"}, sort_keys=True
    ).encode("utf-8")
    assert not verify_signature(
        tampered_body,
        headers=headers,
        secret="callback-secret",
        now=1_718_888_133,
        max_age_sec=300,
    )
    assert not verify_signature(
        body,
        headers=headers,
        secret="wrong-secret",
        now=1_718_888_133,
        max_age_sec=300,
    )


def test_signature_verifier_rejects_missing_prefix_timestamp_version_or_nonce() -> None:
    body = b'{"run_id":"run-1"}'
    headers = signature_headers(
        body, secret="callback-secret", timestamp=1_718_888_123, nonce="nonce-1"
    )

    without_prefix = dict(headers)
    without_prefix[SIGNATURE_HEADER] = without_prefix[SIGNATURE_HEADER].removeprefix(
        SIGNATURE_PREFIX
    )
    assert not verify_signature(
        body,
        headers=without_prefix,
        secret="callback-secret",
        now=1_718_888_133,
        max_age_sec=300,
    )

    without_timestamp = dict(headers)
    without_timestamp.pop(TIMESTAMP_HEADER)
    assert not verify_signature(
        body,
        headers=without_timestamp,
        secret="callback-secret",
        now=1_718_888_133,
        max_age_sec=300,
    )

    without_version = dict(headers)
    without_version.pop(SIGNATURE_VERSION_HEADER)
    assert not verify_signature(
        body,
        headers=without_version,
        secret="callback-secret",
        now=1_718_888_133,
        max_age_sec=300,
    )

    without_nonce = dict(headers)
    without_nonce.pop(SIGNATURE_NONCE_HEADER)
    assert not verify_signature(
        body,
        headers=without_nonce,
        secret="callback-secret",
        now=1_718_888_133,
        max_age_sec=300,
    )


def test_signature_verifier_rejects_non_ascii_nonce_without_crashing() -> None:
    body = b'{"run_id":"run-1"}'
    headers = signature_headers(
        body, secret="callback-secret", timestamp=1_718_888_123, nonce="nonce-1"
    )
    headers[SIGNATURE_NONCE_HEADER] = "nonce-é"

    assert not verify_signature(
        body,
        headers=headers,
        secret="callback-secret",
        now=1_718_888_133,
        max_age_sec=300,
    )


def test_signature_verifier_rejects_stale_or_future_timestamps() -> None:
    body = b'{"run_id":"run-1"}'
    headers = signature_headers(
        body, secret="callback-secret", timestamp=1_718_888_123, nonce="nonce-1"
    )

    assert not verify_signature(
        body,
        headers=headers,
        secret="callback-secret",
        now=1_718_888_424,
        max_age_sec=300,
    )
    assert not verify_signature(
        body,
        headers=headers,
        secret="callback-secret",
        now=1_718_888_000,
        max_age_sec=300,
    )


def test_signature_verifier_rejects_misconfigured_receiver_secret() -> None:
    body = b'{"run_id":"run-1"}'
    headers = signature_headers(
        body, secret="callback-secret", timestamp=1_718_888_123, nonce="nonce-1"
    )

    assert not verify_signature(
        body,
        headers=headers,
        secret=" callback-secret",
        now=1_718_888_133,
        max_age_sec=300,
    )


def test_signature_verifier_rejects_replayed_nonce_when_cache_is_supplied() -> None:
    body = b'{"run_id":"run-1"}'
    headers = signature_headers(
        body, secret="callback-secret", timestamp=1_718_888_123, nonce="nonce-1"
    )
    seen_nonces: set[str] = set()

    assert verify_signature(
        body,
        headers=headers,
        secret="callback-secret",
        now=1_718_888_133,
        max_age_sec=300,
        seen_nonces=seen_nonces,
    )
    assert seen_nonces == {"nonce-1"}
    assert not verify_signature(
        body,
        headers=headers,
        secret="callback-secret",
        now=1_718_888_134,
        max_age_sec=300,
        seen_nonces=seen_nonces,
    )
