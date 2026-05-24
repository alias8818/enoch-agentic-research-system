from __future__ import annotations

import logging
import math
import os
import re
from urllib.parse import ParseResult, parse_qsl, urlencode, urlparse, urlunparse
from typing import Any

try:  # pragma: no cover - import availability is environment-specific.
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
except ImportError:  # pragma: no cover - optional dependency fallback.
    sentry_sdk = None  # type: ignore[assignment]
    FastApiIntegration = None  # type: ignore[assignment]

logger = logging.getLogger("enoch.error_tracking")

_FILTERED = "[Filtered]"
_SENSITIVE_KEY_RE = re.compile(
    r"(token|bearer|password|secret|credential|authorization|cookie|api[_-]?key|dsn)",
    re.IGNORECASE,
)
_PRIVATE_PAYLOAD_KEY_RE = re.compile(
    r"(payload|prompt|artifact|evidence|paper|draft|claim|ledger|content|body|"
    r"request_data|response_data|project_decision|run_notes)",
    re.IGNORECASE,
)
_SAFE_EXTRA_KEYS = {
    "component",
    "lane",
    "operation",
    "project_id",
    "run_id",
    "paper_id",
    "event_id",
    "request_id",
    "route",
    "status",
    "status_code",
    "error_type",
    "machine_target",
}
_TAG_CONTEXT_KEYS = {"component", "lane", "operation", "machine_target"}
_sentry_initialized = False


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _sentry_dsn() -> str:
    return _env("SENTRY_DSN")


def _bounded_float_env(
    name: str, default: float, minimum: float, maximum: float
) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if not math.isfinite(value):
        return default
    return min(max(value, minimum), maximum)


def _is_sensitive_key(key: str) -> bool:
    return bool(_SENSITIVE_KEY_RE.search(key))


def _is_private_payload_key(key: str) -> bool:
    return bool(_PRIVATE_PAYLOAD_KEY_RE.search(key))


def _sanitize_value(key: str, value: Any) -> Any:
    if _is_sensitive_key(key) or _is_private_payload_key(key):
        return _FILTERED
    if isinstance(value, dict):
        return {
            str(child_key): _sanitize_value(str(child_key), child_value)
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_value(key, item) for item in value[:20]]
    return value


def _sanitize_context(context: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in context.items():
        key_text = str(key)
        if key_text in _SAFE_EXTRA_KEYS:
            sanitized[key_text] = value
        else:
            sanitized[key_text] = _sanitize_value(key_text, value)
    return sanitized


def _sanitize_headers(headers: Any) -> Any:
    if not isinstance(headers, dict):
        return headers
    return {
        str(key): _FILTERED if _is_sensitive_key(str(key)) else value
        for key, value in headers.items()
    }


def _sanitize_url(raw_url: Any) -> Any:
    if not isinstance(raw_url, str):
        return raw_url
    try:
        parsed = urlparse(raw_url)
    except Exception:
        return _FILTERED
    if not parsed.query:
        return raw_url
    redacted_pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        redacted_pairs.append((key, _FILTERED if _is_sensitive_key(key) else value))
    redacted_query = urlencode(redacted_pairs, doseq=True)
    return urlunparse(
        ParseResult(
            scheme=parsed.scheme,
            netloc=parsed.netloc,
            path=parsed.path,
            params=parsed.params,
            query=redacted_query,
            fragment=parsed.fragment,
        )
    )


def _sanitize_breadcrumbs(event: dict[str, Any]) -> None:
    breadcrumbs = event.get("breadcrumbs")
    if not isinstance(breadcrumbs, dict):
        return
    values = breadcrumbs.get("values")
    if not isinstance(values, list):
        return
    for item in values:
        if not isinstance(item, dict):
            continue
        data = item.get("data")
        if isinstance(data, dict) and "url" in data:
            data["url"] = _sanitize_url(data.get("url"))


def before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Sentry before_send hook that prevents private research/secrets leakage.

    Enoch Sentry events are for operational exceptions only. Request bodies,
    cookies, query strings, prompts, paper/evidence payloads, and secrets are
    filtered before leaving the control plane.
    """

    del hint
    request = event.get("request")
    if isinstance(request, dict):
        if "url" in request:
            request["url"] = _sanitize_url(request.get("url"))
        request["headers"] = _sanitize_headers(request.get("headers"))
        if "data" in request:
            request["data"] = _FILTERED
        if "cookies" in request:
            request["cookies"] = _FILTERED
        if "query_string" in request:
            request["query_string"] = _FILTERED
        if "env" in request:
            request["env"] = _FILTERED
    extra = event.get("extra")
    if isinstance(extra, dict):
        event["extra"] = _sanitize_context(extra)
    contexts = event.get("contexts")
    if isinstance(contexts, dict):
        event["contexts"] = {
            str(key): value
            if str(key) in {"trace", "runtime", "os", "device"}
            else _sanitize_value(str(key), value)
            for key, value in contexts.items()
        }
    tags = event.setdefault("tags", {})
    if isinstance(tags, dict):
        tags.setdefault("component", _env("ENOCH_SENTRY_COMPONENT", "control_plane"))
    _sanitize_breadcrumbs(event)
    return event


def init_sentry(*, component: str = "control_plane") -> bool:
    """Initialize Sentry SDK if SENTRY_DSN is configured."""

    global _sentry_initialized
    dsn = _sentry_dsn()
    if not dsn:
        return False
    if _sentry_initialized:
        return True
    if sentry_sdk is None or FastApiIntegration is None:
        logger.warning("SENTRY_DSN is configured but sentry-sdk is not installed")
        return False
    environment = _env("ENOCH_SENTRY_ENV", _env("ENOCH_ENV", "production"))
    release = _env("ENOCH_SENTRY_RELEASE", _env("ENOCH_RELEASE", "unknown"))
    sample_rate = _bounded_float_env("ENOCH_SENTRY_TRACES_SAMPLE_RATE", 0.02, 0.0, 1.0)
    try:
        sentry_sdk.init(
            dsn=dsn,
            integrations=[FastApiIntegration()],
            traces_sample_rate=sample_rate,
            environment=environment,
            release=release,
            server_name=_env("ENOCH_SENTRY_SERVER_NAME") or None,
            send_default_pii=False,
            before_send=before_send,
        )
        with sentry_sdk.configure_scope() as scope:
            scope.set_tag("component", component)
            scope.set_tag("environment", environment)
            scope.set_tag("release", release)
        _sentry_initialized = True
        logger.info(
            "Sentry initialized (env=%s, release=%s, component=%s)",
            environment,
            release,
            component,
        )
        return True
    except Exception as exc:  # pragma: no cover - defensive startup behavior.
        logger.warning("Sentry initialization failed: %s", exc)
        return False


def is_sentry_enabled() -> bool:
    return _sentry_initialized


def capture_exception(exc: BaseException, **context: Any) -> str | None:
    """Report an exception to Sentry if configured and return its event ID."""

    sanitized = _sanitize_context(context)
    if _sentry_initialized and sentry_sdk is not None:
        try:
            with sentry_sdk.configure_scope() as scope:
                for key in _TAG_CONTEXT_KEYS:
                    if sanitized.get(key):
                        scope.set_tag(key, str(sanitized[key]))
                for key, value in sanitized.items():
                    if key not in _TAG_CONTEXT_KEYS:
                        scope.set_extra(key, value)
            event_id = sentry_sdk.capture_exception(exc)
            return str(event_id) if event_id else None
        except Exception:
            logger.debug("Failed to capture exception in Sentry", exc_info=True)
            return None
    logger.error("Unhandled exception: %s", exc, exc_info=True, extra=sanitized)
    return None
