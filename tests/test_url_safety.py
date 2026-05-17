from __future__ import annotations

import pytest

from enoch_control_plane.url_safety import validate_http_url


def test_validate_http_url_accepts_http_and_https() -> None:
    assert validate_http_url("http://127.0.0.1:8787/path") == "http://127.0.0.1:8787/path"
    assert validate_http_url("https://example.com/callback") == "https://example.com/callback"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/a", "//example.com/a", "http:///missing-host", "", "   "])
def test_validate_http_url_rejects_non_http_or_missing_host(url: str) -> None:
    with pytest.raises(ValueError):
        validate_http_url(url)
