from __future__ import annotations

import hashlib
import hmac
import time

SIGNATURE_HEADER = "X-Enoch-Signature"
TIMESTAMP_HEADER = "X-Enoch-Timestamp"
SIGNATURE_PREFIX = "sha256="


def signature_headers(
    body: bytes, *, secret: str, timestamp: int | None = None
) -> dict[str, str]:
    """Return HMAC headers for callback payload bytes when a secret is configured."""
    if not secret:
        return {}
    ts = int(time.time() if timestamp is None else timestamp)
    signed = b".".join([str(ts).encode("ascii"), body])
    signature = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return {
        TIMESTAMP_HEADER: str(ts),
        SIGNATURE_HEADER: f"{SIGNATURE_PREFIX}{signature}",
    }
