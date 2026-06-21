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


@pytest.mark.parametrize(
    "value",
    [
        "http://[",
        "http://[::1",
        "http://exa[mple.com",
    ],
)
def test_looks_like_external_source_reference_rejects_malformed_urls(
    value: str,
) -> None:
    assert looks_like_external_source_reference(value) is False


def test_validate_http_url_accepts_http_and_https() -> None:
    assert (
        validate_http_url("https://example.com/callback")
        == "https://example.com/callback"
    )


def test_validate_http_url_allows_private_addresses_only_when_explicit() -> None:
    assert (
        validate_http_url("http://127.0.0.1:8787/path", allow_private=True)
        == "http://127.0.0.1:8787/path"
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
        "http://example.com\\@127.0.0.1/admin",
        "http://user:password@example.com/callback",
        "http://127.0.0.1:8787/path",
        "http://[::1]/callback",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/admin",
        "http://172.16.0.10/admin",
        "http://192.168.1.1/admin",
        "http://2130706433/admin",
        "",
        "   ",
    ],
)
def test_validate_http_url_rejects_non_http_or_malformed_urls(url: str) -> None:
    with pytest.raises(ValueError):
        validate_http_url(url)
