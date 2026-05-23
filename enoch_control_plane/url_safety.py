from __future__ import annotations

from urllib.parse import urlparse

_LOCAL_HTTP_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_EXTERNAL_SOURCE_ID_PREFIXES = ("arxiv:", "doi:")


def secure_default_service_url(host: str, port: int, *, path: str = "") -> str:
    """Return a placeholder service URL defaulting to HTTPS except on loopback."""
    normalized_host = host.strip().lower()
    scheme = "http" if normalized_host in _LOCAL_HTTP_HOSTS else "https"
    normalized_path = path if not path or path.startswith("/") else f"/{path}"
    return f"{scheme}://{host.strip()}:{port}{normalized_path}"


def looks_like_external_source_reference(value: str) -> bool:
    """Return True when a persisted source id or URL points outside local-only artifacts."""
    text = str(value or "").strip().lower()
    if not text:
        return False
    if text.startswith(_EXTERNAL_SOURCE_ID_PREFIXES):
        return True
    parsed = urlparse(text)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


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
