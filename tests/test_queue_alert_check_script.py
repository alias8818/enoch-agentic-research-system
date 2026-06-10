from __future__ import annotations

from io import BytesIO
from email.message import Message
import importlib.util
from pathlib import Path
from urllib import error

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "deploy" / "enoch_queue_alert_check.py"
spec = importlib.util.spec_from_file_location("enoch_queue_alert_check", MODULE_PATH)
assert spec and spec.loader
queue_alert_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(queue_alert_check)


def test_dispatch_error_summary_does_not_log_raw_response_body() -> None:
    secret_body = b'{"detail":"worker token secret-token leaked in nested preflight"}'
    exc = error.HTTPError(
        url="http://127.0.0.1:8787/control/dispatch-next",
        code=409,
        msg="Conflict",
        hdrs=Message(),
        fp=BytesIO(secret_body),
    )

    summary = queue_alert_check._dispatch_error_summary(exc)
    serialized = str(summary)

    assert summary["http_status"] == 409
    assert "response_body" not in summary
    assert summary["response_body_bytes"] == len(secret_body)
    assert "response_body_sha256" in summary
    assert "secret-token" not in serialized
    assert "nested preflight" not in serialized
