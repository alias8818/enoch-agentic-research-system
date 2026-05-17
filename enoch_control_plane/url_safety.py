from __future__ import annotations

from urllib.parse import urlparse


def validate_http_url(url: str, *, field_name: str = "url") -> str:
    """Return a stripped URL only when it targets HTTP(S).

    urllib accepts local schemes such as file://. Enoch operator URLs are
    configuration inputs, but they still cross a high-agency boundary: callback
    delivery and control-plane helpers should never turn a malformed or poisoned
    URL into local-file reads or non-HTTP requests.
    """
    value = str(url or "").strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError(f"{field_name} must not contain control characters")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"{field_name} must use http or https")
    if not parsed.netloc:
        raise ValueError(f"{field_name} must include a host")
    return value
