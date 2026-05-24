from __future__ import annotations

import pytest

from enoch_control_plane.url_safety import (
    looks_like_external_source_reference,
    secure_default_service_url,
    validate_http_url,
)


def test_secure_default_service_url_uses_https_for_remote_hosts() -> None:
    assert (
        secure_default_service_url("worker.example", 8787)
        == "https://worker.example:8787"
    )


def test_secure_default_service_url_preserves_http_for_loopback() -> None:
    assert secure_default_service_url("127.0.0.1", 8787) == "http://127.0.0.1:8787"
    assert secure_default_service_url("localhost", 8787) == "http://localhost:8787"


@pytest.mark.parametrize(
    "value",
    [
        "https://arxiv.org/abs/2605.06546",
        "http://127.0.0.1:8787/path",
        "arxiv:2605.06546",
        "doi:10.1234/example",
    ],
)
def test_looks_like_external_source_reference_accepts_external_ids(
    value: str,
) -> None:
    assert looks_like_external_source_reference(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "file:///etc/passwd",
        "local-artifact.json",
        "source-id-without-scheme",
    ],
)
def test_looks_like_external_source_reference_rejects_non_external(
    value: str,
) -> None:
    assert looks_like_external_source_reference(value) is False


def test_validate_http_url_accepts_http_and_https() -> None:
    assert (
        validate_http_url("http://127.0.0.1:8787/path") == "http://127.0.0.1:8787/path"
    )
    assert (
        validate_http_url("https://example.com/callback")
        == "https://example.com/callback"
    )


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/a",
        "//example.com/a",
        "http:///missing-host",
        "http://example.com/\nInjected: yes",
        "http://example.com/\r\nInjected: yes",
        "",
        "   ",
    ],
)
def test_validate_http_url_rejects_non_http_or_malformed_urls(url: str) -> None:
    with pytest.raises(ValueError):
        validate_http_url(url)
