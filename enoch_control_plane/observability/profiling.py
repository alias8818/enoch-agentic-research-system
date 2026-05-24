from __future__ import annotations

import cProfile
import io
import logging
import pstats
import time
from typing import Any, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("enoch.profiling")


class ProfilingMiddleware(BaseHTTPMiddleware):
    """Lightweight profiling middleware that records CPU time for slow requests.

    When a request exceeds the configured threshold (default 2s), a cProfile
    snapshot is captured and logged at WARNING level. This provides production-
    safe profiling without external dependencies.
    """

    def __init__(
        self,
        app: Any,
        *,
        profile_threshold_ms: int = 2000,
        enabled: bool = True,
    ) -> None:
        super().__init__(app)
        self.profile_threshold_ms = max(0, int(profile_threshold_ms))
        self.enabled = enabled

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Any]
    ) -> Response:
        if not self.enabled:
            return await call_next(request)

        profiler = cProfile.Profile()
        started = time.perf_counter()
        profiler.enable()
        try:
            response = await call_next(request)
        finally:
            profiler.disable()
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)
            if elapsed_ms >= self.profile_threshold_ms:
                stream = io.StringIO()
                stats = pstats.Stats(profiler, stream=stream)
                stats.sort_stats(pstats.SortKey.CUMULATIVE)
                stats.print_stats(20)
                logger.warning(
                    "Slow request profiled: %s %s took %.1fms (threshold=%dms)\n%s",
                    request.method,
                    request.url.path,
                    elapsed_ms,
                    self.profile_threshold_ms,
                    stream.getvalue()[:2000],
                )
        return response
