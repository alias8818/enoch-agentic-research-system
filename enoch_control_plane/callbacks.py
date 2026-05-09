from __future__ import annotations

import json
from urllib import request

from .config import GateConfig
from .models import GateCallback


class CallbackSender:
    def __init__(self, config: GateConfig) -> None:
        self.config = config

    def send(self, callback: GateCallback) -> tuple[int, str]:
        body = json.dumps(callback.model_dump()).encode("utf-8")
        req = request.Request(
            self.config.completion_callback_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.completion_callback_token}",
                "X-Run-Id": callback.run_id,
                "X-Session-Id": callback.session_id,
                "X-Idempotency-Key": callback.idempotency_key,
            },
        )
        with request.urlopen(req, timeout=self.config.completion_callback_timeout_sec) as resp:  # noqa: S310 - explicit operator URL
            text = resp.read().decode("utf-8", errors="replace")
            return resp.status, text
