"""Sync project evidence from the worker HTTP read API into a local artifact root."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, NamedTuple

from ..config import GateConfig
from .store import _atomic_write_text
from .worker_adapter import HttpResult, post_worker_json


class _WorkerEvidenceSyncCtx(NamedTuple):
    wake_gate_url: str
    bearer_token: str
    project_id: str
    artifact_root: Path
    written: list[str]
    skipped: list[dict[str, Any]]


def _worker_json_request(
    base_url: str,
    path: str,
    token: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float,
) -> HttpResult:
    """Call the worker read endpoint without leaving uncancellable threads.

    The underlying adapter uses urllib with a bounded socket timeout. Keeping
    the call synchronous means a stuck or slow worker consumes the current
    request only, not an unbounded background daemon thread per evidence file.
    """

    try:
        return post_worker_json(base_url, path, token, payload, timeout=timeout_seconds)
    except TypeError as exc:
        if "timeout" not in str(exc):
            raise
        return post_worker_json(base_url, path, token, payload)


def _target_is_existing_dir(path: Path) -> tuple[bool, str]:
    try:
        if not path.exists():
            return False, ""
        return path.is_dir(), ""
    except (OSError, RuntimeError, ValueError) as exc:
        return (
            False,
            f"{type(exc).__name__}: evidence target could not be inspected: {exc}",
        )


def _worker_http_evidence_paths(*, base_run: str) -> list[str]:
    paths = [
        "run_notes.md",
        ".enoch/project_decision.json",
        ".enoch/metrics.json",
        ".omx/project_decision.json",
        ".omx/metrics.json",
        "results/hot_cold_sim_results.json",
        "results/smoke.json",
        "results/llamacpp_probe/hotcold_probe.json",
        "results/llamacpp_hotcold_residency/qwen32b_hotcold_residency.json",
        "results/llamacpp_hotcold_residency/qwen32b_hotcold_fixed_budget_pager_sweep.json",
        "results/llamacpp_hotcold_residency/qwen32b_hotcold_fixed_budget_pager_sweep_summary.csv",
        "results/llamacpp_hotcold_residency/qwen32b_hotcold_reuse_pager_sweep.json",
        "results/llamacpp_hotcold_residency/qwen32b_hotcold_reuse_pager_sweep_summary.csv",
    ]
    if base_run:
        paths.extend(
            [
                f"papers/{base_run}/README.md",
                f"papers/{base_run}/paper.md",
                f"papers/{base_run}/paper_manifest.json",
                f"papers/{base_run}/evidence_bundle.json",
                f"papers/{base_run}/claim_ledger.json",
            ]
        )
    return paths


def _prepare_worker_evidence_artifact_root(
    artifact_root: Path,
) -> tuple[Path | None, dict[str, Any] | None]:
    try:
        resolved = artifact_root.resolve()
        resolved.mkdir(parents=True, exist_ok=True)
    except (OSError, RuntimeError, ValueError) as exc:
        return None, {
            "ok": False,
            "reason": "artifact_root_unusable",
            "files": 0,
            "paths": [],
            "skipped": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
    if not resolved.is_dir():
        return None, {
            "ok": False,
            "reason": "artifact_root_unusable",
            "files": 0,
            "paths": [],
            "skipped": [],
            "error": "artifact root is not a directory",
        }
    return resolved, None


def _worker_evidence_skip(path: str, status: str | int, error: str) -> dict[str, Any]:
    return {"path": path, "status": status, "error": error[:300]}


def _purge_stale_worker_evidence_file(artifact_root: Path, rel: str) -> None:
    try:
        stale_target = (artifact_root / rel).resolve()
        stale_target.relative_to(artifact_root)
        if rel and stale_target != artifact_root and stale_target.is_file():
            stale_target.unlink()
    except (OSError, RuntimeError, ValueError):
        pass


def _resolve_worker_evidence_target(
    artifact_root: Path, rel: str
) -> tuple[Path | None, dict[str, Any] | None]:
    try:
        target = (artifact_root / rel).resolve()
        target.relative_to(artifact_root)
    except (OSError, RuntimeError, ValueError):
        return None, _worker_evidence_skip(
            rel, "unsafe_path", "worker returned path outside artifact root"
        )
    target_is_dir, target_error = _target_is_existing_dir(target)
    if target_error:
        return None, _worker_evidence_skip(rel, "unsafe_path", target_error)
    if not rel or target == artifact_root or target_is_dir:
        return None, _worker_evidence_skip(
            rel, "unsafe_path", "worker returned path is not a file target"
        )
    return target, None


def _apply_worker_evidence_file(
    artifact_root: Path,
    request_path: str,
    file: Any,
    *,
    written: list[str],
    skipped: list[dict[str, Any]],
) -> None:
    if not isinstance(file, dict):
        skipped.append(
            _worker_evidence_skip(
                request_path,
                "malformed_file",
                "worker read response file entry is not an object",
            )
        )
        return
    rel = str(file.get("path") or "").strip()
    content = str(file.get("content") or "")
    if not content:
        _purge_stale_worker_evidence_file(artifact_root, rel)
        skipped.append(
            _worker_evidence_skip(
                rel, "empty_content", "worker returned empty evidence content"
            )
        )
        return
    target, skip = _resolve_worker_evidence_target(artifact_root, rel)
    if skip is not None:
        skipped.append(skip)
        return
    assert target is not None
    try:
        _atomic_write_text(target, content)
    except OSError as exc:
        skipped.append(
            _worker_evidence_skip(rel, "write_failed", f"{type(exc).__name__}: {exc}")
        )
        return
    written.append(rel)


def _apply_worker_evidence_read_body(
    artifact_root: Path,
    request_path: str,
    body: dict[str, Any],
    *,
    written: list[str],
    skipped: list[dict[str, Any]],
) -> None:
    files = body.get("files", [])
    if not isinstance(files, list):
        skipped.append(
            _worker_evidence_skip(
                request_path,
                "malformed_response",
                "worker read response files field is not a list",
            )
        )
        return
    for file in files:
        _apply_worker_evidence_file(
            artifact_root, request_path, file, written=written, skipped=skipped
        )


def _fetch_worker_evidence_path(
    ctx: _WorkerEvidenceSyncCtx,
    path: str,
    request_timeout: float,
) -> bool:
    """Fetch one worker evidence path. Returns True when the request timed out."""
    result = _worker_json_request(
        ctx.wake_gate_url,
        f"/project-paper/{ctx.project_id}/read",
        ctx.bearer_token,
        {"paths": [path], "max_bytes_per_file": 2_000_000},
        timeout_seconds=request_timeout,
    )
    if not result.ok or not result.body:
        is_timeout = "TimeoutError:" in (result.error or "")
        ctx.skipped.append(
            _worker_evidence_skip(
                path,
                "timeout" if is_timeout else result.status,
                result.error or str(result.status),
            )
        )
        return is_timeout
    if not isinstance(result.body, dict):
        ctx.skipped.append(
            _worker_evidence_skip(
                path,
                "malformed_response",
                "worker read response body is not an object",
            )
        )
        return False
    _apply_worker_evidence_read_body(
        ctx.artifact_root,
        path,
        result.body,
        written=ctx.written,
        skipped=ctx.skipped,
    )
    return False


def _worker_http_evidence_sync_result(
    *,
    written: list[str],
    skipped: list[dict[str, Any]],
    timeouts: int,
) -> dict[str, Any]:
    if not written:
        return {
            "ok": False,
            "reason": "no_worker_http_evidence" if timeouts else "worker_read_failed",
            "files": 0,
            "paths": [],
            "skipped": skipped[:30],
            "timeouts": timeouts,
        }
    return {
        "ok": True,
        "reason": "worker_http_synced",
        "files": len(written),
        "paths": written[:30],
        "skipped": skipped[:30],
        "timeouts": timeouts,
    }


def _run_worker_http_evidence_sync_loop(
    ctx: _WorkerEvidenceSyncCtx,
    paths: list[str],
    *,
    per_request_timeout_seconds: float,
    overall_timeout_seconds: float,
) -> int:
    """Fetch each evidence path until overall timeout. Returns timeout count."""
    started = time.monotonic()
    timeouts = 0
    for path in paths:
        remaining = overall_timeout_seconds - (time.monotonic() - started)
        if remaining <= 0:
            timeouts += 1
            ctx.skipped.append(
                _worker_evidence_skip(
                    path,
                    "timeout",
                    "overall worker evidence sync timeout exceeded",
                )
            )
            break
        request_timeout = min(per_request_timeout_seconds, remaining)
        if _fetch_worker_evidence_path(ctx, path, request_timeout):
            timeouts += 1
    return timeouts


def _sync_worker_http_evidence(
    config: GateConfig,
    *,
    project_id: str,
    artifact_root: Path,
    source_run_id: str = "",
    worker_wake_gate_url: str | None = None,
    worker_bearer_token: str | None = None,
    per_request_timeout_seconds: float = 5.0,
    overall_timeout_seconds: float = 45.0,
) -> dict[str, Any]:
    wake_gate_url = (worker_wake_gate_url or config.worker_wake_gate_url or "").strip()
    bearer_token = (
        worker_bearer_token or config.worker_wake_gate_bearer_token or ""
    ).strip()
    if not bearer_token:
        return {"ok": False, "reason": "worker_token_missing"}
    if not wake_gate_url:
        return {"ok": False, "reason": "worker_url_missing"}
    base_run = source_run_id.removesuffix("-publication") if source_run_id else ""
    paths = _worker_http_evidence_paths(base_run=base_run)
    written: list[str] = []
    skipped: list[dict[str, Any]] = []
    artifact_root, artifact_error = _prepare_worker_evidence_artifact_root(
        artifact_root
    )
    if artifact_error is not None:
        return artifact_error
    assert artifact_root is not None
    # Read each evidence path independently. The GB10 worker read endpoint is
    # intentionally strict and returns a non-2xx response when any requested
    # path is missing. Most projects only have a subset of the optional
    # artifacts below, so a single bulk read can fail an otherwise valid rewrite
    # before useful evidence is copied. Treat missing optional paths as skipped
    # and let the later local evidence gate decide whether enough material was
    # synced to ground a paper.
    ctx = _WorkerEvidenceSyncCtx(
        wake_gate_url=wake_gate_url,
        bearer_token=bearer_token,
        project_id=project_id,
        artifact_root=artifact_root,
        written=written,
        skipped=skipped,
    )
    timeouts = _run_worker_http_evidence_sync_loop(
        ctx,
        paths,
        per_request_timeout_seconds=per_request_timeout_seconds,
        overall_timeout_seconds=overall_timeout_seconds,
    )
    return _worker_http_evidence_sync_result(
        written=written, skipped=skipped, timeouts=timeouts
    )
