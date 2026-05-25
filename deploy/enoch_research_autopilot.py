#!/usr/bin/env python3
"""Run one bounded Research Facility automation tick.

The service is inert unless ENOCH_ENABLE_RESEARCH_AUTOPILOT=1 is set.  A live
tick is intentionally small: at most one provider request, one promotion, one
dispatch, one positive-gated paper draft, and one automated finalization.
"""

from __future__ import annotations

import json
from http.client import RemoteDisconnected
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib import error, request

from enoch_control_plane.research_provider_defaults import (
    DEFAULT_RESEARCH_PROVIDER_BASE_URL,
    DEFAULT_RESEARCH_PROVIDER_MODEL,
    DEFAULT_RESEARCH_PROVIDER_MODEL_ROTATION,
    default_research_provider_openai_base_url,
)
from enoch_control_plane.url_safety import secure_default_service_url

# Centralized reason constant for the top remaining S1192 duplication
# in this autopilot script.
MISSING_DATABASE_URL_REASON = "missing database URL"


def _load_config() -> dict:
    path = Path(
        os.environ.get("ENOCH_CONFIG")
        or os.environ.get(
            "ENOCH_CONTROL_PLANE_CONFIG", "/etc/enoch-control-plane/config.json"
        )
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _base_url(config: dict) -> str:
    host = str(config.get("listen_host") or "127.0.0.1")
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return os.environ.get("ENOCH_CONTROL_URL") or secure_default_service_url(
        host, int(config.get("listen_port") or 8787)
    )


def _post_json(
    base_url: str, path: str, token: str, payload: dict, *, timeout: int
) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{base_url}{path}",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    with request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - local/operator-configured control URL
        return json.loads(resp.read().decode("utf-8"))


def _get_json(base_url: str, path: str, token: str, *, timeout: int) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = request.Request(f"{base_url}{path}", method="GET", headers=headers)
    with request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - local/operator-configured control URL
        return json.loads(resp.read().decode("utf-8"))


def _control_plane_recovered(base_url: str) -> bool:
    """Return true when the local control API is reachable after a dropped tick.

    A deploy or service restart can close the long-running run-cycle request
    while a worker is still healthy or after the bounded tick already made
    progress. Do not retry the POST because it is not idempotent; just verify
    the control plane recovered so the next timer tick can continue safely.
    """

    for _ in range(3):
        time.sleep(2)
        try:
            health = _get_json(base_url, "/healthz", "", timeout=5)
        except (OSError, error.URLError, json.JSONDecodeError):
            continue
        if health.get("ok"):
            return True
    return False


def _truthy(name: str, default: str = "0") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _bounded_int(name: str, default: int, lower: int, upper: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(lower, min(value, upper))


def _provider_model() -> str:
    explicit = os.environ.get("ENOCH_RESEARCH_PROVIDER_MODEL")
    if explicit:
        return explicit
    rotation = [
        item.strip()
        for item in os.environ.get(
            "ENOCH_RESEARCH_PROVIDER_MODEL_ROTATION",
            ",".join(DEFAULT_RESEARCH_PROVIDER_MODEL_ROTATION),
        ).split(",")
        if item.strip()
    ]
    if not rotation:
        return DEFAULT_RESEARCH_PROVIDER_MODEL
    window_seconds = _bounded_int(
        "ENOCH_RESEARCH_PROVIDER_MODEL_ROTATION_SECONDS", 1200, 60, 86400
    )
    return rotation[int(time.time() // window_seconds) % len(rotation)]


def _topic() -> str:
    explicit = os.environ.get("ENOCH_RESEARCH_AUTOPILOT_TOPIC")
    if explicit:
        return explicit
    rotation = [
        item.strip()
        for item in os.environ.get(
            "ENOCH_RESEARCH_TOPIC_ROTATION",
            (
                "speculative decoding without extra draft-model VRAM,"
                "tiny-VRAM training and optimizer memory reduction,"
                "agent reliability with falsifiable evidence ledgers,"
                "distributed volunteer training with cheating-resistant validation,"
                "long-context memory with exact anchors and compressed state,"
                "extreme quantization with principled residual channels,"
                "local-serving routing and model cascades,"
                "data selection for tiny local pretraining"
            ),
        ).split(",")
        if item.strip()
    ]
    if not rotation:
        return ""
    window_seconds = _bounded_int(
        "ENOCH_RESEARCH_TOPIC_ROTATION_SECONDS", 1800, 60, 86400
    )
    return rotation[int(time.time() // window_seconds) % len(rotation)]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _database_url() -> str:
    return (
        os.environ.get("ENOCH_RESEARCH_QUALITY_DATABASE_URL")
        or os.environ.get("ENOCH_SUPABASE_DATABASE_URL")
        or os.environ.get("ENOCH_CONTROL_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or ""
    ).strip()


def _database_url_env(database_url: str) -> dict[str, str]:
    """Return a subprocess environment with the database URL kept out of argv."""

    env = os.environ.copy()
    for name in (
        "ENOCH_RESEARCH_QUALITY_DATABASE_URL",
        "ENOCH_SUPABASE_DATABASE_URL",
        "ENOCH_CONTROL_DATABASE_URL",
    ):
        env.pop(name, None)
    env["DATABASE_URL"] = database_url
    return env


def _timeout_reason(timeout: int) -> str:
    return f"timeout after {timeout}s"


def refresh_research_quality_report() -> dict:
    """Refresh the read-only Research Facility quality report.

    This is intentionally fail-soft for the main autopilot tick: generating the
    report must never enqueue, dispatch, draft, or mutate database state. The
    dashboard readiness surface still exposes stale/missing reports as a
    separate operator-visible condition.
    """

    if _truthy("ENOCH_RESEARCH_QUALITY_REFRESH_DISABLED"):
        return {
            "ok": True,
            "action": "research_quality_refresh_skipped",
            "reason": "disabled",
        }

    database_url = _database_url()
    if not database_url:
        return {
            "ok": False,
            "action": "research_quality_refresh_skipped",
            "reason": MISSING_DATABASE_URL_REASON,
        }

    output = Path(
        os.environ.get(
            "ENOCH_RESEARCH_QUALITY_REPORT_PATH",
            "/var/lib/enoch-control-plane/research-quality/latest-report.json",
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    limit = _bounded_int("ENOCH_RESEARCH_QUALITY_LIMIT", 100, 1, 1000)
    timeout = _bounded_int("ENOCH_RESEARCH_QUALITY_TIMEOUT_SECONDS", 90, 10, 600)
    script = _repo_root() / "scripts" / "dspy_research_quality.py"
    cmd = [
        sys.executable,
        str(script),
        "--limit",
        str(limit),
        "--output",
        str(output),
        "--pretty",
    ]
    display_cmd = [*cmd]

    try:
        proc = subprocess.run(
            cmd,
            cwd=_repo_root(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            env=_database_url_env(database_url),
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "action": "research_quality_refresh_failed",
            "reason": _timeout_reason(timeout),
            "command": display_cmd,
            "output": str(output),
        }
    except OSError as exc:
        return {
            "ok": False,
            "action": "research_quality_refresh_failed",
            "reason": f"{type(exc).__name__}: {exc}",
            "command": display_cmd,
            "output": str(output),
        }

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    return {
        "ok": proc.returncode == 0,
        "action": "research_quality_refresh",
        "returncode": proc.returncode,
        "output": str(output),
        "limit": limit,
        "stdout": stdout[-2000:],
        "stderr": stderr[-2000:],
        "command": display_cmd,
    }


def refresh_research_quality_window_comparison() -> dict:
    """Refresh the read-only post-prompt comparison used by the dashboard."""

    cutoff = os.environ.get("ENOCH_RESEARCH_QUALITY_WINDOW_CUTOFF", "").strip()
    if not cutoff:
        return {
            "ok": True,
            "action": "research_quality_window_comparison_skipped",
            "reason": "missing cutoff",
        }

    database_url = _database_url()
    if not database_url:
        return {
            "ok": False,
            "action": "research_quality_window_comparison_skipped",
            "reason": MISSING_DATABASE_URL_REASON,
        }

    output = Path(
        os.environ.get(
            "ENOCH_RESEARCH_QUALITY_WINDOW_REPORT_PATH",
            "/var/lib/enoch-control-plane/research-quality/latest-window-comparison.json",
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    limit = _bounded_int("ENOCH_RESEARCH_QUALITY_WINDOW_LIMIT", 20, 1, 200)
    timeout = _bounded_int("ENOCH_RESEARCH_QUALITY_WINDOW_TIMEOUT_SECONDS", 90, 10, 600)
    script = _repo_root() / "scripts" / "compare_research_quality_windows.py"
    cmd = [
        sys.executable,
        str(script),
        "--cutoff",
        cutoff,
        "--limit",
        str(limit),
        "--output",
        str(output),
    ]
    display_cmd = [*cmd]

    try:
        proc = subprocess.run(
            cmd,
            cwd=_repo_root(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            env=_database_url_env(database_url),
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "action": "research_quality_window_comparison_failed",
            "reason": _timeout_reason(timeout),
            "command": display_cmd,
            "output": str(output),
        }
    except OSError as exc:
        return {
            "ok": False,
            "action": "research_quality_window_comparison_failed",
            "reason": f"{type(exc).__name__}: {exc}",
            "command": display_cmd,
            "output": str(output),
        }

    return {
        "ok": proc.returncode == 0,
        "action": "research_quality_window_comparison",
        "returncode": proc.returncode,
        "output": str(output),
        "cutoff": cutoff,
        "limit": limit,
        "stdout": proc.stdout.strip()[-2000:],
        "stderr": proc.stderr.strip()[-2000:],
        "command": display_cmd,
    }


def _janitor_llm_review_output_path() -> Path:
    output = Path(
        os.environ.get(
            "ENOCH_RESEARCH_JANITOR_LLM_REPORT_PATH",
            "/var/lib/enoch-control-plane/research-quality/latest-janitor-llm-review.json",
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def _janitor_llm_review_command(output: Path, timeout: int) -> list[str]:
    cmd = [
        sys.executable,
        str(_repo_root() / "scripts" / "research_facility_llm_review.py"),
        "--provider-base-url",
        os.environ.get(
            "ENOCH_RESEARCH_PROVIDER_BASE_URL", DEFAULT_RESEARCH_PROVIDER_BASE_URL
        ),
        "--openai-base-url",
        os.environ.get(
            "ENOCH_RESEARCH_PROVIDER_OPENAI_BASE_URL",
            default_research_provider_openai_base_url(),
        ),
        "--model",
        _provider_model(),
        "--batch-size",
        str(_bounded_int("ENOCH_RESEARCH_JANITOR_LLM_BATCH_SIZE", 15, 1, 50)),
        "--janitor-limit",
        str(_bounded_int("ENOCH_RESEARCH_JANITOR_LLM_JANITOR_LIMIT", 250, 1, 500)),
        "--estimated-requests",
        str(_bounded_int("ENOCH_RESEARCH_JANITOR_LLM_ESTIMATED_REQUESTS", 1, 1, 5)),
        "--reserve-requests",
        str(_bounded_int("ENOCH_RESEARCH_JANITOR_LLM_RESERVE_REQUESTS", 5, 0, 100)),
        "--min-rolling-remaining",
        str(_bounded_int("ENOCH_RESEARCH_JANITOR_LLM_MIN_ROLLING", 150, 0, 2500)),
        "--min-remaining-credits",
        os.environ.get("ENOCH_RESEARCH_JANITOR_LLM_MIN_CREDITS", "10.0"),
        "--min-weekly-percent-remaining",
        os.environ.get("ENOCH_RESEARCH_JANITOR_LLM_MIN_WEEKLY_PERCENT", "25.0"),
        "--cooldown-minutes",
        str(_bounded_int("ENOCH_RESEARCH_JANITOR_LLM_COOLDOWN_MINUTES", 25, 0, 1440)),
        "--timeout",
        str(timeout),
        "--max-tokens",
        str(_bounded_int("ENOCH_RESEARCH_JANITOR_LLM_MAX_TOKENS", 6000, 1000, 16000)),
        "--temperature",
        os.environ.get("ENOCH_RESEARCH_JANITOR_LLM_TEMPERATURE", "0.1"),
        "--requested-by",
        os.environ.get(
            "ENOCH_RESEARCH_JANITOR_LLM_REQUESTED_BY",
            "systemd:enoch-research-autopilot",
        ),
        "--output",
        str(output),
    ]
    if _truthy("ENOCH_RESEARCH_JANITOR_LLM_APPLY"):
        cmd.append("--apply")
    else:
        cmd.append("--dry-run")
    if _truthy("ENOCH_RESEARCH_JANITOR_LLM_APPLY_STORED", default="1"):
        cmd.append("--apply-stored-decisions")
        cmd.extend(
            [
                "--stored-decision-limit",
                str(
                    _bounded_int(
                        "ENOCH_RESEARCH_JANITOR_LLM_STORED_LIMIT", 500, 1, 2000
                    )
                ),
            ]
        )
    return cmd


def _read_janitor_llm_payload(output: Path) -> dict:
    if not output.exists():
        return {}
    try:
        return json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _janitor_llm_review_subprocess_error(
    *, reason: str, display_cmd: list, output: Path
) -> dict:
    return {
        "ok": False,
        "action": "research_janitor_llm_review_failed",
        "reason": reason,
        "command": display_cmd,
        "output": str(output),
    }


def _janitor_llm_review_result(
    proc: subprocess.CompletedProcess[str],
    *,
    output: Path,
    payload: dict,
    display_cmd: list,
) -> dict:
    return {
        "ok": proc.returncode == 0 and bool(payload.get("ok", proc.returncode == 0)),
        "action": payload.get("action") or "research_janitor_llm_review",
        "returncode": proc.returncode,
        "output": str(output),
        "summary": {
            "reason": payload.get("reason") or "",
            "batch_count": payload.get("batch_count"),
            "decision_count": payload.get("decision_count"),
            "decision_counts": payload.get("decision_counts") or {},
            "budget": payload.get("budget") or {},
            "apply_result": payload.get("apply_result") or {},
        },
        "stdout": proc.stdout.strip()[-2000:],
        "stderr": proc.stderr.strip()[-2000:],
        "command": display_cmd,
    }


def run_quota_gated_janitor_llm_review() -> dict:
    """Run at most one Synthetic-backed janitor adjudication batch.

    The script owns its own quota/cooldown gates. The timer may call this every
    tick, but provider spend only happens when rolling and weekly budgets are
    healthy and rewrite_suggested backlog exists.
    """

    if not _truthy("ENOCH_RESEARCH_JANITOR_LLM_REVIEW_ENABLED"):
        return {
            "ok": True,
            "action": "research_janitor_llm_review_skipped",
            "reason": "disabled",
        }

    database_url = _database_url()
    if not database_url:
        return {
            "ok": False,
            "action": "research_janitor_llm_review_skipped",
            "reason": MISSING_DATABASE_URL_REASON,
        }

    output = _janitor_llm_review_output_path()
    timeout = _bounded_int("ENOCH_RESEARCH_JANITOR_LLM_TIMEOUT_SECONDS", 180, 30, 600)
    display_cmd = _janitor_llm_review_command(output, timeout)
    try:
        proc = subprocess.run(
            display_cmd,
            cwd=_repo_root(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout + 30,
            check=False,
            env=_database_url_env(database_url),
        )
    except subprocess.TimeoutExpired:
        return _janitor_llm_review_subprocess_error(
            reason=_timeout_reason(timeout + 30),
            display_cmd=display_cmd,
            output=output,
        )
    except OSError as exc:
        return _janitor_llm_review_subprocess_error(
            reason=f"{type(exc).__name__}: {exc}",
            display_cmd=display_cmd,
            output=output,
        )

    return _janitor_llm_review_result(
        proc,
        output=output,
        payload=_read_janitor_llm_payload(output),
        display_cmd=display_cmd,
    )


def _provider_malformed_count(result: dict) -> int:
    texts: list[str] = []
    for warning in result.get("warnings") or []:
        texts.append(str(warning))
    for stage in result.get("stages") or []:
        if isinstance(stage, dict):
            texts.append(str(stage.get("reason") or ""))
    return sum(
        1
        for text in texts
        if "provider returned no usable candidate JSON" in text
        or "Unterminated string" in text
    )


def append_research_autopilot_history(result: dict) -> dict:
    """Append a compact tick summary for dashboard quality monitoring."""

    path = Path(
        os.environ.get(
            "ENOCH_RESEARCH_AUTOPILOT_HISTORY_PATH",
            "/var/lib/enoch-control-plane/research-quality/autopilot-history.jsonl",
        )
    )
    entry = {
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checked_at": (result.get("budget") or {}).get("checked_at") or "",
        "ok": bool(result.get("ok")),
        "reason": result.get("reason") or "",
        "provider_model": result.get("provider_model") or "",
        "generated_count": int(result.get("generated_count") or 0),
        "promoted_count": int(result.get("promoted_count") or 0),
        "dispatched_count": int(result.get("dispatched_count") or 0),
        "initial_promotable_count": int(result.get("initial_promotable_count") or 0),
        "malformed_provider_response_count": _provider_malformed_count(result),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError as exc:
        return {
            "ok": False,
            "action": "research_autopilot_history_append_failed",
            "reason": f"{type(exc).__name__}: {exc}",
            "path": str(path),
        }
    return {
        "ok": True,
        "action": "research_autopilot_history_append",
        "path": str(path),
        "entry": entry,
    }


def _is_benign_skip_result(result: dict) -> bool:
    """Return true for normal long-haul idle/backpressure outcomes.

    The timer should not enter failed state just because a previous tick still
    has a worker lane active. That is expected bounded backpressure, not an
    automation failure.
    """

    reason = str(result.get("reason") or "").lower()
    action = str(result.get("action") or "").lower()
    return "active worker lane already exists" in reason or action in {
        "skipped",
        "noop",
    }


def _research_autopilot_failure(reason: str) -> dict:
    return {
        "ok": False,
        "action": "failed",
        "reason": reason,
    }


def _main_quality_refresh_exit() -> int | None:
    if not _truthy("ENOCH_RESEARCH_QUALITY_REFRESH_ONLY"):
        return None
    result = refresh_research_quality_report()
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("ok") else 1


def _main_autopilot_disabled_exit() -> int | None:
    if _truthy("ENOCH_ENABLE_RESEARCH_AUTOPILOT"):
        return None
    print(
        json.dumps(
            {
                "ok": True,
                "action": "skipped",
                "reason": "research autopilot disabled; set ENOCH_ENABLE_RESEARCH_AUTOPILOT=1",
            },
            sort_keys=True,
        )
    )
    return 0


def _resolve_control_token(config: dict) -> str:
    return os.environ.get("ENOCH_CONTROL_TOKEN") or str(
        config.get("control_api_bearer_token")
        or config.get("omx_inbound_bearer_token")
        or ""
    )


def _main_missing_token_exit(token: str) -> int | None:
    if token:
        return None
    print(
        json.dumps(
            {
                "ok": False,
                "action": "skipped",
                "reason": "missing control-plane token",
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return 2


def _build_research_run_cycle_payload() -> tuple[dict, int]:
    wait_for_completion = _truthy("ENOCH_RESEARCH_AUTOPILOT_WAIT", "0")
    max_wait_seconds = _bounded_int(
        "ENOCH_RESEARCH_AUTOPILOT_MAX_WAIT_SECONDS", 900, 0, 1800
    )
    papers_enabled = _truthy("ENOCH_RESEARCH_AUTOPILOT_PAPERS", "1")
    payload = {
        "enabled": True,
        "dry_run": False,
        "requested_by": os.environ.get(
            "ENOCH_RESEARCH_AUTOPILOT_REQUESTED_BY", "systemd:enoch-research-autopilot"
        ),
        "model": _provider_model(),
        "topic": _topic(),
        "temperature": float(
            os.environ.get("ENOCH_RESEARCH_AUTOPILOT_TEMPERATURE", "0.6")
        ),
        "generation_max_tokens": _bounded_int(
            "ENOCH_RESEARCH_PROVIDER_MAX_TOKENS", 8000, 1000, 16000
        ),
        "generation_attempts": _bounded_int(
            "ENOCH_RESEARCH_PROVIDER_ATTEMPTS", 2, 1, 3
        ),
        "max_provider_requests_per_run": _bounded_int(
            "ENOCH_RESEARCH_AUTOPILOT_PROVIDER_REQUESTS", 1, 0, 1
        ),
        "max_candidates": _bounded_int(
            "ENOCH_RESEARCH_AUTOPILOT_MAX_CANDIDATES", 5, 1, 10
        ),
        "max_promotions_per_run": _bounded_int(
            "ENOCH_RESEARCH_AUTOPILOT_PROMOTIONS", 10, 0, 25
        ),
        "min_queue_depth_per_lane": _bounded_int(
            "ENOCH_RESEARCH_MIN_QUEUE_DEPTH_PER_LANE", 25, 0, 100
        ),
        "max_dispatches_per_run": _bounded_int(
            "ENOCH_RESEARCH_AUTOPILOT_DISPATCHES", 2, 0, 4
        )
        if _truthy("ENOCH_RESEARCH_AUTOPILOT_DISPATCH", "1")
        else 0,
        "wait_for_completion": wait_for_completion,
        "max_wait_seconds": max_wait_seconds if wait_for_completion else 0,
        "poll_interval_seconds": _bounded_int(
            "ENOCH_RESEARCH_AUTOPILOT_POLL_SECONDS", 10, 2, 60
        ),
        "max_paper_drafts_per_run": 1 if papers_enabled else 0,
        "max_publication_rewrites_per_run": 1 if papers_enabled else 0,
        "min_remaining_credits": float(
            os.environ.get("ENOCH_RESEARCH_AUTOPILOT_MIN_CREDITS", "5.0")
        ),
        "min_rolling_remaining": _bounded_int(
            "ENOCH_RESEARCH_AUTOPILOT_MIN_ROLLING", 10, 0, 2500
        ),
        "reserve_requests": _bounded_int(
            "ENOCH_RESEARCH_AUTOPILOT_RESERVE_REQUESTS", 2, 0, 100
        ),
    }
    return payload, max_wait_seconds


def _transient_disconnect_exit(
    exc: BaseException, base_url: str, *, phase: str
) -> int | None:
    if not _control_plane_recovered(base_url):
        return None
    print(
        json.dumps(
            {
                "ok": True,
                "action": "transient_disconnect",
                "reason": (
                    f"control plane {phase} during bounded research tick and recovered: "
                    f"{type(exc).__name__}: {exc}"
                ),
            },
            sort_keys=True,
        )
    )
    return 0


def _research_autopilot_request_failure_exit(exc: BaseException) -> tuple[int, None]:
    failure = _research_autopilot_failure(
        f"research autopilot request failed: {type(exc).__name__}: {exc}"
    )
    print(json.dumps(failure, sort_keys=True), file=sys.stderr)
    return 1, None


def _post_research_run_cycle(
    base_url: str, token: str, payload: dict, max_wait_seconds: int
) -> tuple[int | None, dict | None]:
    try:
        result = _post_json(
            base_url,
            "/control/api/research/run-cycle",
            token,
            payload,
            timeout=max(60, max_wait_seconds + 120),
        )
    except RemoteDisconnected as exc:
        exit_code = _transient_disconnect_exit(exc, base_url, phase="disconnected")
        if exit_code is not None:
            return exit_code, None
        return _research_autopilot_request_failure_exit(exc)
    except error.HTTPError as exc:
        return _research_autopilot_request_failure_exit(exc)
    except error.URLError as exc:
        exit_code = _transient_disconnect_exit(exc, base_url, phase="unavailable")
        if exit_code is not None:
            return exit_code, None
        return _research_autopilot_request_failure_exit(exc)
    except (TimeoutError, json.JSONDecodeError) as exc:
        return _research_autopilot_request_failure_exit(exc)
    return None, result


def _attach_autopilot_sidecars(result: dict) -> None:
    history_result = append_research_autopilot_history(result)
    result["research_autopilot_history"] = history_result
    result["research_quality_refresh"] = refresh_research_quality_report()
    result["research_quality_window_comparison"] = (
        refresh_research_quality_window_comparison()
    )
    result["research_janitor_llm_review"] = run_quota_gated_janitor_llm_review()


def _finalize_autopilot_tick(result: object) -> int:
    if not isinstance(result, dict):
        print(json.dumps(result, sort_keys=True))
        return 1
    _attach_autopilot_sidecars(result)
    print(json.dumps(result, sort_keys=True))
    tick_ok = result.get("ok") or _is_benign_skip_result(result)
    return 0 if tick_ok else 1


def main() -> int:
    exit_code = _main_quality_refresh_exit()
    if exit_code is not None:
        return exit_code

    exit_code = _main_autopilot_disabled_exit()
    if exit_code is not None:
        return exit_code

    config = _load_config()
    token = _resolve_control_token(config)
    exit_code = _main_missing_token_exit(token)
    if exit_code is not None:
        return exit_code

    payload, max_wait_seconds = _build_research_run_cycle_payload()
    base_url = _base_url(config)
    exit_code, result = _post_research_run_cycle(
        base_url, token, payload, max_wait_seconds
    )
    if exit_code is not None:
        return exit_code
    return _finalize_autopilot_tick(result)


if __name__ == "__main__":
    raise SystemExit(main())
