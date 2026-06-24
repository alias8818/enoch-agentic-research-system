from __future__ import annotations

import io
import urllib.error
from email.message import Message
from typing import Any

import pytest
from pytest import MonkeyPatch

from deploy import enoch_paper_drain_until_noop as paper_drain
from enoch_control_plane.http_redaction import (
    redact_headers,
    redact_secrets,
    redact_text,
    redact_url,
)
from scripts import reconcile_paper_ledgers, sync_sonarqube_linear


class _HTTPError(urllib.error.HTTPError):
    def __init__(self, url: str, body: bytes) -> None:
        super().__init__(url, 403, "Forbidden", hdrs=Message(), fp=io.BytesIO(body))


def test_redact_url_removes_query_and_userinfo_secrets() -> None:
    redacted = redact_url(
        "https://user:secret@example.supabase.co/rest/v1?apikey=jwt-token&safe=ok&token=abc"
    )

    assert "secret" not in redacted
    assert "jwt-token" not in redacted
    assert "token=abc" not in redacted
    assert "apikey=REDACTED" in redacted
    assert "safe=ok" in redacted


def test_redact_headers_and_nested_payloads() -> None:
    assert redact_headers({"Authorization": "Bearer secret", "Accept": "json"}) == {
        "Authorization": "REDACTED",
        "Accept": "json",
    }
    payload = {
        "error": "bad Bearer abc.def",
        "nested": {"apikey": "jwt-token", "url": "https://x.test?a=1&token=abc"},
    }

    redacted = redact_secrets(payload)

    assert redacted["nested"]["apikey"] == "REDACTED"
    assert "abc.def" not in redacted["error"]
    assert "token=abc" not in redacted["nested"]["url"]


def test_sync_sonarqube_http_error_redacts_url_and_body(
    monkeypatch: MonkeyPatch,
) -> None:
    secret_url = "https://sonar.example/api?apikey=jwt-token&component=x"
    body = json_body = {"message": "token=jwt-token"}
    del body

    def raise_http_error(*_args: Any, **_kwargs: Any) -> None:
        raise _HTTPError(secret_url, str(json_body).encode("utf-8"))

    monkeypatch.setattr(sync_sonarqube_linear, "urlopen_validated", raise_http_error)

    with pytest.raises(RuntimeError) as exc_info:
        sync_sonarqube_linear.request_json(
            secret_url, headers={"Authorization": "Bearer jwt-token"}
        )

    text = str(exc_info.value)
    assert "jwt-token" not in text
    assert "apikey=REDACTED" in text
    assert "REDACTED" in text


def test_reconcile_paper_ledgers_http_error_redacts_url_and_body(
    monkeypatch: MonkeyPatch,
) -> None:
    def raise_http_error(*_args: Any, **_kwargs: Any) -> None:
        raise _HTTPError(
            "http://127.0.0.1/control?token=secret",
            b"failure apikey=jwt-token",
        )

    monkeypatch.setattr(reconcile_paper_ledgers, "urlopen_validated", raise_http_error)

    with pytest.raises(RuntimeError) as exc_info:
        reconcile_paper_ledgers.request_json(
            "http://127.0.0.1?token=secret", "jwt-token", "/control?apikey=jwt-token"
        )

    text = str(exc_info.value)
    assert "jwt-token" not in text
    assert "token=secret" not in text
    assert "apikey=REDACTED" in text


def test_paper_drain_control_client_redacts_error_payload(
    monkeypatch: MonkeyPatch,
) -> None:
    def raise_http_error(*_args: Any, **_kwargs: Any) -> None:
        raise _HTTPError(
            "http://127.0.0.1/control",
            b'{"detail":"Bearer jwt-token","apikey":"jwt-token","url":"https://x.test?token=abc"}',
        )

    monkeypatch.setattr(paper_drain, "urlopen_validated", raise_http_error)
    client = paper_drain.ControlClient("http://127.0.0.1", "jwt-token", 5)

    status, payload = client.get("/control/api/status")

    assert status == 403
    assert payload["apikey"] == "REDACTED"
    assert "jwt-token" not in str(payload)
    assert "token=abc" not in str(payload)


def test_redact_text_handles_key_value_forms() -> None:
    text = redact_text("Authorization: Bearer *** token=def; apikey=ghi; API Key: jkl")

    assert "def" not in text
    assert "ghi" not in text
    assert "jkl" not in text
    assert "REDACTED" in text


def test_redact_text_redacts_authorization_bearer_value_before_key_value_rewrite() -> (
    None
):
    text = redact_text("upstream echoed Authorization: Bearer abcdef123")

    assert "abcdef123" not in text
    assert "Authorization" in text
    assert "REDACTED" in text


def test_redact_secrets_handles_malformed_url_strings() -> None:
    payload = {
        "bad_port": "http://example.com:bad/path?key=operator-token",
        "bad_ipv6": "http://[::1/path?authorization=secret",
    }

    redacted = redact_secrets(payload)

    assert "operator-token" not in str(redacted)
    assert "secret" not in str(redacted)
    assert "REDACTED" in str(redacted)
