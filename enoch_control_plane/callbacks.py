from __future__ import annotations

import json
import logging
from urllib import request
from urllib.error import URLError

from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
    retry_if_exception_type,
)

from .url_safety import urlopen_validated, validate_http_url
from .callback_signing import signature_headers
from .config import GateConfig
from .models import GateCallback

logger = logging.getLogger("enoch.callbacks")

# Idempotent callbacks are safe to retry on transient network errors.
# The downstream consumer deduplicates by idempotency_key.
_CALLBACK_RETRY_WAIT = wait_random_exponential(multiplier=0.5, min=0.5, max=8)
_RETRY_ON_NETWORK = retry(
    retry=retry_if_exception_type((URLError, OSError, TimeoutError)),
    stop=stop_after_attempt(3),
    wait=_CALLBACK_RETRY_WAIT,
    before_sleep=lambda retry_state: logger.warning(
        "callback send attempt %d failed (%s), retrying in %.1fs",
        retry_state.attempt_number,
        retry_state.outcome.exception(),
        retry_state.next_action.sleep,
    ),
)


class CallbackSender:
    def __init__(self, config: GateConfig) -> None:
        self.config = config

    @_RETRY_ON_NETWORK
    def send(self, callback: GateCallback) -> tuple[int, str]:
        body = json.dumps(callback.model_dump()).encode("utf-8")
        safe_url = validate_http_url(
            self.config.completion_callback_url, field_name="completion callback url"
        )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.completion_callback_token}",
            "X-Run-Id": callback.run_id,
            "X-Session-Id": callback.session_id,
            "X-Idempotency-Key": callback.idempotency_key,
        }
        headers.update(
            signature_headers(body, secret=self.config.completion_callback_hmac_secret)
        )
        req = request.Request(
            safe_url,
            data=body,
            method="POST",
            headers=headers,
        )
        with urlopen_validated(
            req,
            timeout=float(self.config.completion_callback_timeout_sec),
            field_name="completion callback url",
        ) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return resp.status, text
