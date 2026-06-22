from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "REDACTED"
_SECRET_QUERY_KEYS = {
    "apikey",
    "api_key",
    "access_token",
    "auth",
    "authorization",
    "bearer",
    "jwt",
    "key",
    "password",
    "secret",
    "token",
}
_SECRET_HEADER_KEYS = {
    "apikey",
    "api-key",
    "authorization",
    "proxy-authorization",
    "x-api-key",
}
_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(apikey|api[._\s-]?key|access[._\s-]?token|auth|authorization|bearer|jwt|key|token|secret|password)"
    r"\s*[:=]\s*"
    r"([^\s,;&\"'{}\[\]<>]+)"
)
_BEARER_VALUE_RE = re.compile(r"(?i)\bbearer\s+([^\s,;&\"'{}\[\]<>]+)")


def redact_url(url: str) -> str:
    raw = str(url)
    try:
        parts = urlsplit(raw)
        query = urlencode(
            [
                (key, REDACTED if key.lower() in _SECRET_QUERY_KEYS else value)
                for key, value in parse_qsl(parts.query, keep_blank_values=True)
            ],
            doseq=True,
        )
        # Accessing hostname/port can validate malformed netlocs and raise
        # ValueError, for example on bad ports or unmatched IPv6 brackets.
        netloc = parts.hostname or ""
        if parts.port is not None:
            netloc = f"{netloc}:{parts.port}"
        if parts.username or parts.password:
            user = parts.username or ""
            if parts.password:
                user = f"{user}:{REDACTED}"
            netloc = f"{user}@{netloc}"
        return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))
    except ValueError:
        return redact_text(raw)


def redact_headers(headers: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: REDACTED if str(key).lower() in _SECRET_HEADER_KEYS else value
        for key, value in headers.items()
    }


def redact_text(text: str) -> str:
    redacted = _SECRET_VALUE_RE.sub(
        lambda match: f"{match.group(1)}={REDACTED}", str(text)
    )
    redacted = _BEARER_VALUE_RE.sub(f"Bearer {REDACTED}", redacted)
    return redacted


def redact_secrets(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: REDACTED
            if str(key).lower() in _SECRET_QUERY_KEYS
            else redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value)
    if isinstance(value, str):
        return redact_text(redact_url(value) if "://" in value else value)
    return value
