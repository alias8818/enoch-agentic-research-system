from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping

SIGNATURE_HEADER = "X-Enoch-Signature"
TIMESTAMP_HEADER = "X-Enoch-Timestamp"
SIGNATURE_VERSION_HEADER = "X-Enoch-Signature-Version"
SIGNATURE_PREFIX = "sha256="
SIGNATURE_VERSION = "v1"
MAX_SECRET_BYTES = 256


def _secret_bytes(secret: str) -> bytes:
    if secret != secret.strip():
        raise ValueError(
            "callback signing secret must not have leading/trailing whitespace"
        )
    encoded = secret.encode("utf-8")
    if len(encoded) > MAX_SECRET_BYTES:
        raise ValueError("callback signing secret must be at most 256 bytes")
    return encoded


def _signed_payload(body: bytes, *, timestamp: int, version: str) -> bytes:
    return b".".join([version.encode("ascii"), str(timestamp).encode("ascii"), body])


def signature_headers(
    body: bytes, *, secret: str, timestamp: int | None = None
) -> dict[str, str]:
    """Return HMAC headers for callback payload bytes when a secret is configured."""
    if not secret:
        return {}
    ts = int(time.time() if timestamp is None else timestamp)
    signed = _signed_payload(body, timestamp=ts, version=SIGNATURE_VERSION)
    signature = hmac.new(_secret_bytes(secret), signed, hashlib.sha256).hexdigest()
    return {
        SIGNATURE_VERSION_HEADER: SIGNATURE_VERSION,
        TIMESTAMP_HEADER: str(ts),
        SIGNATURE_HEADER: f"{SIGNATURE_PREFIX}{signature}",
    }


def verify_signature(
    body: bytes,
    *,
    headers: Mapping[str, str],
    secret: str,
    max_age_sec: int = 300,
    now: int | None = None,
) -> bool:
    """Verify callback HMAC headers for payload bytes.

    Empty secrets preserve the optional-signing deployment mode: when no secret
    is configured, callers can skip signature enforcement by passing an empty
    secret and this returns True.
    """

    if not secret:
        return True
    try:
        key = _secret_bytes(secret)
    except ValueError:
        return False
    version = headers.get(SIGNATURE_VERSION_HEADER, "")
    if version != SIGNATURE_VERSION:
        return False
    observed = headers.get(SIGNATURE_HEADER, "")
    if not observed.startswith(SIGNATURE_PREFIX):
        return False
    try:
        timestamp = int(headers.get(TIMESTAMP_HEADER, ""))
    except (TypeError, ValueError):
        return False
    current = int(time.time() if now is None else now)
    if timestamp > current or current - timestamp > max_age_sec:
        return False
    signed = _signed_payload(body, timestamp=timestamp, version=version)
    expected = SIGNATURE_PREFIX + hmac.new(key, signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(observed, expected)
