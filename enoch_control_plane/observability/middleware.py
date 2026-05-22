from __future__ import annotations

import json
from pathlib import Path
import resource
import time
from typing import Any, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from enoch_control_plane.models import utc_now


def peak_rss_mib() -> float:
    """Return process peak RSS in MiB using stdlib-only resource data."""

    # Linux reports ru_maxrss in KiB. macOS reports bytes, but this service is
    # deployed on Linux; keep the Linux path explicit and harmless elsewhere.
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0


def current_rss_mib() -> float | None:
    """Return current process RSS in MiB when Linux /proc is available."""

    status_path = Path("/proc/self/status")
    try:
        for line in status_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                parts = line.split()
                if len(parts) >= 2:
                    return float(parts[1]) / 1024.0
    except OSError:
        return None
    return None


class RouteObservationMiddleware(BaseHTTPMiddleware):
    """Record bounded per-route timing/size/memory observations.

    The middleware is intentionally lightweight and opt-in. It never inspects or
    stores request/response bodies, never records query strings, and writes one
    compact JSONL line per request when an observation path is configured.
    """

    def __init__(
        self,
        app: Any,
        *,
        observation_path: str | Path | None = None,
        slow_ms: int = 1000,
        memory_warn_rss_mib: int = 0,
    ) -> None:
        super().__init__(app)
        self.observation_path = (
            Path(observation_path).expanduser() if observation_path else None
        )
        self.slow_ms = max(0, int(slow_ms))
        self.memory_warn_rss_mib = max(0, int(memory_warn_rss_mib))
        if self.observation_path is not None:
            self.observation_path.parent.mkdir(parents=True, exist_ok=True)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Any]
    ) -> Response:
        started = time.perf_counter()
        rss_before = current_rss_mib()
        peak_before = peak_rss_mib()
        response: Response | None = None
        error_type = ""
        try:
            response = await call_next(request)
            return response
        except Exception as exc:  # pragma: no cover - re-raised for FastAPI
            error_type = type(exc).__name__
            raise
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
            rss_after = current_rss_mib()
            peak_after = peak_rss_mib()
            status_code = response.status_code if response is not None else 500
            content_length = None
            if response is not None:
                raw_length = response.headers.get("content-length")
                if raw_length and raw_length.isdigit():
                    content_length = int(raw_length)
                response.headers["X-Enoch-Route-Duration-Ms"] = str(elapsed_ms)
                response.headers["X-Enoch-Route-Peak-RSS-MiB"] = f"{peak_after:.3f}"
                if rss_after is not None:
                    response.headers["X-Enoch-Route-RSS-MiB"] = f"{rss_after:.3f}"
            observation = {
                "observed_at": utc_now(),
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": elapsed_ms,
                "content_length": content_length,
                "rss_before_mib": rss_before,
                "rss_after_mib": rss_after,
                "rss_delta_mib": None
                if rss_before is None or rss_after is None
                else round(rss_after - rss_before, 3),
                "peak_rss_before_mib": round(peak_before, 3),
                "peak_rss_after_mib": round(peak_after, 3),
                "slow": bool(self.slow_ms and elapsed_ms >= self.slow_ms),
                "memory_warn": bool(
                    self.memory_warn_rss_mib
                    and rss_after is not None
                    and rss_after >= self.memory_warn_rss_mib
                ),
                "error_type": error_type,
            }
            self._append_observation(observation)

    def _append_observation(self, observation: dict[str, Any]) -> None:
        if self.observation_path is None:
            return
        try:
            with self.observation_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(observation, sort_keys=True) + "\n")
        except OSError:
            # Observability must never make the control plane unhealthy.
            return
