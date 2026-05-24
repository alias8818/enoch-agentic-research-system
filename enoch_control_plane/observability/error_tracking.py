from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("enoch.error_tracking")

# Sentry DSN is optional. When configured, unhandled exceptions are reported
# with stack traces, breadcrumbs, and request context. When not configured,
# errors are logged locally only.
_SENTRY_DSN = os.environ.get("SENTRY_DSN", "").strip()
_sentry_initialized = False


def init_sentry() -> None:
    """Initialize Sentry SDK if SENTRY_DSN is configured."""
    global _sentry_initialized
    if not _SENTRY_DSN or _sentry_initialized:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration

        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            integrations=[FastApiIntegration()],
            traces_sample_rate=0.1,
            environment=os.environ.get("ENOCH_SENTRY_ENV", "production"),
            release=os.environ.get("ENOCH_SENTRY_RELEASE", "unknown"),
            send_default_pii=False,
        )
        _sentry_initialized = True
        logger.info(
            "Sentry initialized (env=%s)",
            os.environ.get("ENOCH_SENTRY_ENV", "production"),
        )
    except ImportError:
        logger.debug("sentry-sdk not installed; error tracking disabled")
    except Exception as exc:
        logger.warning("Sentry initialization failed: %s", exc)


def capture_exception(exc: BaseException, **context: Any) -> None:
    """Report an exception to error tracking if configured."""
    if _sentry_initialized:
        try:
            import sentry_sdk

            with sentry_sdk.configure_scope() as scope:
                for key, value in context.items():
                    scope.set_extra(key, value)
            sentry_sdk.capture_exception(exc)
        except Exception:
            logger.debug("Failed to capture exception in Sentry", exc_info=True)
    else:
        logger.error("Unhandled exception: %s", exc, exc_info=True, extra=context)
