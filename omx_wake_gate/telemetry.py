from __future__ import annotations

from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover - dependency may not be installed yet
    psutil = None

try:
    from pynvml import (
        nvmlDeviceGetComputeRunningProcesses,
        nvmlDeviceGetHandleByIndex,
        nvmlDeviceGetMemoryInfo,
        nvmlDeviceGetUtilizationRates,
        nvmlInit,
        nvmlShutdown,
    )
except ImportError:  # pragma: no cover - dependency may not be installed yet
    nvmlDeviceGetComputeRunningProcesses = None
    nvmlDeviceGetHandleByIndex = None
    nvmlDeviceGetMemoryInfo = None
    nvmlDeviceGetUtilizationRates = None
    nvmlInit = None
    nvmlShutdown = None

from .models import TelemetrySample

_KB_PER_MIB = 1024


def _read_meminfo(path: Path = Path("/proc/meminfo")) -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if ":" not in line:
                continue
            key, rest = line.split(":", 1)
            parts = rest.strip().split()
            if not parts:
                continue
            try:
                values[key] = int(parts[0])
            except ValueError:
                continue
    except OSError:
        return {}
    return values


def _uma_memory_from_meminfo(values: dict[str, int]) -> dict[str, int | str]:
    """Estimate allocatable memory on UMA systems.

    NVIDIA documents that DGX Spark uses unified memory and that
    ``nvidia-smi`` reports dedicated memory as unsupported. Treat
    MemAvailable as the primary safe allocation signal. SwapFree is included
    only when swap is configured; the GB10 production posture intentionally
    supports SwapTotal=0 with earlyoom so OOM conditions fail fast instead of
    hanging indefinitely in swap. If HugeTLB pages are in use, only free huge
    pages are relevant and not swappable.
    """

    mem_total_mib = values.get("MemTotal", 0) // _KB_PER_MIB
    mem_available_mib = values.get("MemAvailable", 0) // _KB_PER_MIB
    swap_free_mib = values.get("SwapFree", 0) // _KB_PER_MIB
    swap_total_mib = values.get("SwapTotal", 0) // _KB_PER_MIB
    huge_total = values.get("HugePages_Total", 0)
    huge_free = values.get("HugePages_Free", 0)
    huge_size_mib = values.get("Hugepagesize", 0) // _KB_PER_MIB

    if huge_total > 0:
        allocatable_mib = huge_free * huge_size_mib
        swap_free_mib = 0
        total_pool_mib = huge_total * huge_size_mib
    else:
        allocatable_mib = mem_available_mib + swap_free_mib
        total_pool_mib = mem_total_mib + swap_total_mib

    pressure_mib = max(0, total_pool_mib - allocatable_mib)
    return {
        "memory_source": "uma_meminfo",
        "memory_total_mib": mem_total_mib,
        "memory_available_mib": mem_available_mib,
        "swap_free_mib": swap_free_mib,
        "uma_allocatable_mib": allocatable_mib,
        "uma_pressure_mib": pressure_mib,
    }


class TelemetryCollector:
    """Collect host CPU plus optional NVIDIA GPU/UMA telemetry."""

    def __init__(self) -> None:
        self._psutil = psutil
        self._nvml_ready = False
        if self._psutil is not None:
            self._psutil.cpu_percent(interval=None)
        if nvmlInit is not None:
            try:
                nvmlInit()
                self._nvml_ready = True
            except Exception:
                self._nvml_ready = False

    def sample(self) -> TelemetrySample:
        cpu_pct = 0.0
        if self._psutil is not None:
            cpu_pct = self._psutil.cpu_percent(interval=None)

        meminfo = _read_meminfo()
        uma = _uma_memory_from_meminfo(meminfo)
        gpu_pct = 0.0
        vram_used_mib = int(uma["uma_pressure_mib"])
        memory_source = str(uma["memory_source"])
        gpu_compute_pids: list[int] = []

        if self._nvml_ready and nvmlDeviceGetHandleByIndex is not None:
            try:
                handle = nvmlDeviceGetHandleByIndex(0)
                util = nvmlDeviceGetUtilizationRates(handle)
                gpu_pct = float(util.gpu)
                for proc in nvmlDeviceGetComputeRunningProcesses(handle):
                    pid = getattr(proc, "pid", None)
                    if pid is not None:
                        gpu_compute_pids.append(int(pid))
                try:
                    mem = nvmlDeviceGetMemoryInfo(handle)
                    dedicated_total_mib = int(getattr(mem, "total", 0) / (1024 * 1024))
                    dedicated_used_mib = int(getattr(mem, "used", 0) / (1024 * 1024))
                    if dedicated_total_mib > 0:
                        vram_used_mib = dedicated_used_mib
                        memory_source = "nvml_dedicated"
                except Exception:
                    # Expected on DGX Spark/iGPU UMA platforms: NVIDIA documents
                    # that nvidia-smi reports Memory-Usage as unsupported.
                    pass
            except Exception:
                gpu_pct = 0.0
                gpu_compute_pids = []

        return TelemetrySample(
            cpu_pct=cpu_pct,
            gpu_pct=gpu_pct,
            vram_used_mib=vram_used_mib,
            gpu_compute_pids=gpu_compute_pids,
            memory_source=memory_source,
            memory_total_mib=int(uma["memory_total_mib"]),
            memory_available_mib=int(uma["memory_available_mib"]),
            swap_free_mib=int(uma["swap_free_mib"]),
            uma_allocatable_mib=int(uma["uma_allocatable_mib"]),
            uma_pressure_mib=int(uma["uma_pressure_mib"]),
        )

    def close(self) -> None:
        if self._nvml_ready and nvmlShutdown is not None:
            try:
                nvmlShutdown()
            except Exception:
                pass
