from __future__ import annotations

import cProfile
import io
import logging
import pstats
import secrets
import time
from typing import Any, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("enoch.profiling")
_PROFILE_SAMPLER = secrets.SystemRandom()


class ProfilingMiddleware(BaseHTTPMiddleware):
    """Lightweight profiling middleware that records CPU time for slow requests.

    The middleware is disabled unless explicitly installed by the app, and even
    then it samples requests and rate-limits slow-request profile logs. This keeps
    cProfile overhead and WARNING log volume bounded during incidents.
    """

    def __init__(
        self,
        app: Any,
        *,
        profile_threshold_ms: int = 2000,
        enabled: bool = True,
        sample_rate: float = 0.01,
        log_cooldown_sec: float = 60.0,
    ) -> None:
        super().__init__(app)
        self.profile_threshold_ms = max(0, int(profile_threshold_ms))
        self.enabled = enabled
        self.sample_rate = max(0.0, min(float(sample_rate), 1.0))
        self.log_cooldown_sec = max(0.0, float(log_cooldown_sec))
        self._last_profile_log_at: dict[str, float] = {}

    def _should_profile(self) -> bool:
        return bool(
            self.enabled
            and self.sample_rate > 0.0
            and _PROFILE_SAMPLER.random() < self.sample_rate
        )

    def _should_log_slow_profile(self, route_key: str, now: float) -> bool:
        last = self._last_profile_log_at.get(route_key, 0.0)
        if self.log_cooldown_sec and now - last < self.log_cooldown_sec:
            return False
        self._last_profile_log_at[route_key] = now
        return True

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Any]
    ) -> Response:
        if not self._should_profile():
            return await call_next(request)

        profiler = cProfile.Profile()
        started = time.perf_counter()
        profiler.enable()
        try:
            response = await call_next(request)
        finally:
            profiler.disable()
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)
            route_key = f"{request.method} {request.url.path}"
            now = time.monotonic()
            if (
                elapsed_ms >= self.profile_threshold_ms
                and self._should_log_slow_profile(route_key, now)
            ):
                stream = io.StringIO()
                stats = pstats.Stats(profiler, stream=stream)
                stats.sort_stats(pstats.SortKey.CUMULATIVE)
                stats.print_stats(20)
                logger.info(
                    "Sampled slow request profile: %s %s took %.1fms (threshold=%dms)\n%s",
                    request.method,
                    request.url.path,
                    elapsed_ms,
                    self.profile_threshold_ms,
                    stream.getvalue()[:2000],
                )
        return response
