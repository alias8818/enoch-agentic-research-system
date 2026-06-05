#!/usr/bin/env python3
"""Run one bounded Research Facility automation tick.

The service is inert unless ENOCH_ENABLE_RESEARCH_AUTOPILOT=1 is set.  A live
tick is intentionally small: at most one provider request, one promotion, one
dispatch, one positive-gated paper draft, and one automated finalization.
"""

from __future__ import annotations

from datetime import datetime, timezone
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
DEFAULT_JANITOR_LLM_REVIEW_MODEL = "openrouter/owl-alpha"


def _load_config() -> dict:
    path = Path(
        os.environ.get("ENOCH_CONFIG")
        or os.environ.get(
            "ENOCH_CONTROL_PLANE_CONFIG", "/etc/enoch-control-plane/config.json"
        )
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _state_dir(config: dict) -> Path:
    return Path(str(config.get("state_dir") or "/var/lib/enoch-control-plane"))


def _synthetic_settings_provider(config: dict) -> dict:
    configured = os.environ.get("ENOCH_LLM_SETTINGS_PATH", "").strip()
    path = (
        Path(configured).expanduser()
        if configured
        else _state_dir(config) / "llm-provider-settings.json"
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    for provider in data.get("providers") or []:
        if str(provider.get("provider_id") or "").strip() == "synthetic":
            return provider if isinstance(provider, dict) else {}
    return {}


def _synthetic_provider_openai_base_url() -> str:
    if os.environ.get("ENOCH_RESEARCH_PROVIDER_OPENAI_BASE_URL"):
        return os.environ["ENOCH_RESEARCH_PROVIDER_OPENAI_BASE_URL"].rstrip("/")
    provider = _synthetic_settings_provider(_load_config())
    base_url = str(provider.get("base_url") or "").strip()
    if base_url:
        return base_url.rstrip("/")
    return default_research_provider_openai_base_url()


def _synthetic_provider_base_url() -> str:
    if os.environ.get("ENOCH_RESEARCH_PROVIDER_BASE_URL"):
        return os.environ["ENOCH_RESEARCH_PROVIDER_BASE_URL"].rstrip("/")
    openai_base_url = _synthetic_provider_openai_base_url()
    suffix = "/openai/v1"
    if openai_base_url.endswith(suffix):
        return openai_base_url[: -len(suffix)]
    return DEFAULT_RESEARCH_PROVIDER_BASE_URL


def _synthetic_provider_api_key(config: dict) -> str:
    if os.environ.get("SYNTHETIC_API_KEY"):
        return os.environ["SYNTHETIC_API_KEY"]
    configured = os.environ.get("ENOCH_LLM_PROVIDER_SECRETS_DIR", "").strip()
    secret_dir = (
        Path(configured).expanduser()
        if configured
        else _state_dir(config) / "llm-provider-secrets"
    )
    secret_path = secret_dir / "synthetic.token"
    try:
        if secret_path.is_symlink():
            return ""
        return secret_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


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
    database_url = (
        os.environ.get("ENOCH_RESEARCH_QUALITY_DATABASE_URL")
        or os.environ.get("ENOCH_SUPABASE_DATABASE_URL")
        or os.environ.get("ENOCH_CONTROL_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or ""
    ).strip()
    if database_url:
        return database_url
    if not (
        os.environ.get("ENOCH_CONFIG") or os.environ.get("ENOCH_CONTROL_PLANE_CONFIG")
    ):
        return ""
    try:
        return str(_load_config().get("supabase_database_url") or "").strip()
    except (OSError, json.JSONDecodeError):
        return ""


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


def _research_quality_refresh_status_path() -> Path:
    return Path(
        os.environ.get(
            "ENOCH_RESEARCH_QUALITY_REFRESH_STATUS_PATH",
            "/var/lib/enoch-control-plane/research-quality/latest-refresh.json",
        )
    )


def _record_research_quality_refresh_status(result: dict) -> dict:
    payload = {
        key: result.get(key)
        for key in (
            "ok",
            "action",
            "reason",
            "returncode",
            "output",
            "limit",
        )
        if key in result
    }
    payload["recorded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path = _research_quality_refresh_status_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        result["refresh_status_write"] = {
            "ok": False,
            "path": str(path),
            "reason": f"{type(exc).__name__}: {exc}",
        }
        return result
    result["refresh_status_write"] = {"ok": True, "path": str(path)}
    return result


def refresh_research_quality_report() -> dict:
    """Refresh the read-only Research Facility quality report.

    This is intentionally fail-soft for the main autopilot tick: generating the
    report must never enqueue, dispatch, draft, or mutate database state. The
    dashboard readiness surface still exposes stale/missing reports as a
    separate operator-visible condition.
    """

    if _truthy("ENOCH_RESEARCH_QUALITY_REFRESH_DISABLED"):
        return _record_research_quality_refresh_status(
            {
                "ok": True,
                "action": "research_quality_refresh_skipped",
                "reason": "disabled",
            }
        )

    output = Path(
        os.environ.get(
            "ENOCH_RESEARCH_QUALITY_REPORT_PATH",
            "/var/lib/enoch-control-plane/research-quality/latest-report.json",
        )
    )

    database_url = _database_url()
    if not database_url:
        return _record_research_quality_refresh_status(
            {
                "ok": False,
                "action": "research_quality_refresh_skipped",
                "reason": MISSING_DATABASE_URL_REASON,
                "output": str(output),
            }
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
        return _record_research_quality_refresh_status(
            {
                "ok": False,
                "action": "research_quality_refresh_failed",
                "reason": _timeout_reason(timeout),
                "command": display_cmd,
                "output": str(output),
            }
        )
    except OSError as exc:
        return _record_research_quality_refresh_status(
            {
                "ok": False,
                "action": "research_quality_refresh_failed",
                "reason": f"{type(exc).__name__}: {exc}",
                "command": display_cmd,
                "output": str(output),
            }
        )

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    return _record_research_quality_refresh_status(
        {
            "ok": proc.returncode == 0,
            "action": "research_quality_refresh",
            "returncode": proc.returncode,
            "output": str(output),
            "limit": limit,
            "stdout": stdout[-2000:],
            "stderr": stderr[-2000:],
            "command": display_cmd,
        }
    )


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


def _janitor_llm_review_model() -> str:
    return (
        os.environ.get("ENOCH_RESEARCH_JANITOR_LLM_MODEL")
        or DEFAULT_JANITOR_LLM_REVIEW_MODEL
    )


def _janitor_llm_review_command(output: Path, timeout: int) -> list[str]:
    cmd = [
        sys.executable,
        str(_repo_root() / "scripts" / "research_facility_llm_review.py"),
        "--provider-base-url",
        _synthetic_provider_base_url(),
        "--openai-base-url",
        _synthetic_provider_openai_base_url(),
        "--model",
        _janitor_llm_review_model(),
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


def _janitor_llm_review_env(database_url: str) -> dict[str, str]:
    env = _database_url_env(database_url)
    if not env.get("SYNTHETIC_API_KEY"):
        api_key = _synthetic_provider_api_key(_load_config())
        if api_key:
            env["SYNTHETIC_API_KEY"] = api_key
    return env


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
            "provider_review": payload.get("provider_review") or {},
            "stored_decision_apply": payload.get("stored_decision_apply") or {},
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
            env=_janitor_llm_review_env(database_url),
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
        "trace_id": result.get("trace_id") or "",
        "run_cycle_id": result.get("run_cycle_id") or "",
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
    has a worker lane active, or because the control plane made a recorded
    policy decision to block the tick. Those are expected bounded
    backpressure/attention states, not automation failures.
    """

    reason = str(result.get("reason") or "").lower()
    action = str(result.get("action") or "").lower()
    if action in {
        "skipped",
        "noop",
    }:
        return True
    if "active worker lane already exists" in reason:
        return True
    if action == "research_cycle_blocked":
        return True
    if action == "research_cycle":
        return any(
            phrase in reason
            for phrase in (
                "blocked item(s) need attention",
                "provider budget unavailable",
                "provider budget check unavailable",
            )
        )
    return False


def _research_autopilot_failure(reason: str) -> dict:
    return {
        "ok": False,
        "action": "failed",
        "reason": reason,
    }


def _main_quality_refresh_exit() -> int | None:
    if not _truthy("ENOCH_RESEARCH_QUALITY_REFRESH_ONLY"):
        return None
    hold_result = _quality_refresh_control_hold_skip_result()
    if hold_result is not None:
        print(json.dumps(hold_result, sort_keys=True))
        return 0
    result = refresh_research_quality_report()
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("ok") else 1


def _quality_refresh_control_hold_skip_result() -> dict | None:
    try:
        config = _load_config()
    except (OSError, json.JSONDecodeError):
        return None
    token = _resolve_control_token(config)
    if not token:
        return None
    return _control_hold_skip_result(
        _base_url(config),
        token,
        override_env="ENOCH_RESEARCH_QUALITY_REFRESH_RUN_WHILE_HELD",
        component="research quality refresh",
    )


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


def _control_hold_skip_result(
    base_url: str,
    token: str,
    *,
    override_env: str = "ENOCH_RESEARCH_AUTOPILOT_RUN_WHILE_HELD",
    component: str = "research autopilot",
) -> dict | None:
    if _truthy(override_env, "0"):
        return None
    try:
        status = _get_json(base_url, "/control/api/status", token, timeout=10)
    except Exception:
        return None
    flags = status.get("flags") if isinstance(status, dict) else {}
    if not isinstance(flags, dict):
        return None
    held_by: list[str] = []
    if bool(flags.get("maintenance_mode")):
        held_by.append("maintenance_mode")
    if bool(flags.get("queue_paused")):
        held_by.append("queue_paused")
    if not held_by:
        return None
    return {
        "ok": True,
        "action": "skipped",
        "reason": f"{component} skipped while control plane is held: {', '.join(held_by)}",
        "hold_state": {
            "queue_paused": bool(flags.get("queue_paused")),
            "maintenance_mode": bool(flags.get("maintenance_mode")),
            "pause_reason": str(flags.get("pause_reason") or ""),
            "paused_at": str(flags.get("paused_at") or ""),
            "paused_by": str(flags.get("paused_by") or ""),
        },
    }


def _main_control_hold_exit(base_url: str, token: str) -> int | None:
    result = _control_hold_skip_result(base_url, token)
    if result is None:
        return None
    result["research_autopilot_history"] = append_research_autopilot_history(result)
    print(json.dumps(result, sort_keys=True))
    return 0


def _http_error_detail(exc: error.HTTPError) -> str:
    try:
        raw = exc.read(4096)
    except Exception:
        return ""
    try:
        body = raw.decode("utf-8", errors="replace")
    except AttributeError:
        body = str(raw)
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body
    if isinstance(parsed, dict):
        detail = parsed.get("detail")
        if isinstance(detail, dict):
            return json.dumps(detail, sort_keys=True)
        if detail is not None:
            return str(detail)
    return body


def _hold_related_conflict_detail(detail: str) -> bool:
    lowered = detail.lower()
    return any(
        phrase in lowered
        for phrase in (
            "maintenance mode blocks live dispatch",
            "queue pause blocks live dispatch",
            "control plane must be resumed before live dispatch",
        )
    )


def _hold_related_conflict_exit(exc: error.HTTPError) -> tuple[int | None, None]:
    if exc.code != 409:
        return None, None
    detail = _http_error_detail(exc)
    if not _hold_related_conflict_detail(detail):
        return None, None
    result: dict[str, object] = {
        "ok": True,
        "action": "skipped",
        "reason": "research autopilot skipped after hold-related 409",
        "http_status": exc.code,
        "detail": detail,
    }
    result["research_autopilot_history"] = append_research_autopilot_history(result)
    print(json.dumps(result, sort_keys=True))
    return 0, None


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


def _research_run_cycle_request_timeout(payload: dict) -> int:
    generation_timeout = int(payload.get("generation_timeout") or 240)
    generation_attempts = int(payload.get("generation_attempts") or 1)
    wait_timeout = (
        int(payload.get("max_wait_seconds") or 0)
        if bool(payload.get("wait_for_completion"))
        else 0
    )
    paper_timeout = (
        600
        if int(payload.get("max_paper_drafts_per_run") or 0)
        or int(payload.get("max_publication_rewrites_per_run") or 0)
        else 0
    )
    return max(
        60,
        generation_timeout * generation_attempts + wait_timeout + paper_timeout + 120,
    )


def _build_research_run_cycle_payload() -> tuple[dict, int]:
    wait_for_completion = _truthy("ENOCH_RESEARCH_AUTOPILOT_WAIT", "0")
    max_wait_seconds = _bounded_int(
        "ENOCH_RESEARCH_AUTOPILOT_MAX_WAIT_SECONDS", 900, 0, 1800
    )
    papers_enabled = _truthy("ENOCH_RESEARCH_AUTOPILOT_PAPERS", "1")
    generation_timeout = _bounded_int("ENOCH_RESEARCH_PROVIDER_TIMEOUT", 240, 10, 300)
    generation_attempts = _bounded_int("ENOCH_RESEARCH_PROVIDER_ATTEMPTS", 2, 1, 3)
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
        "generation_timeout": generation_timeout,
        "generation_attempts": generation_attempts,
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
    return payload, _research_run_cycle_request_timeout(payload)


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


def _stale_rotation_model_rejection(result: object, payload: dict) -> bool:
    if not isinstance(result, dict) or result.get("ok"):
        return False
    if not str(payload.get("model") or "").strip():
        return False
    reason = str(result.get("reason") or "")
    return (
        result.get("action") == "research_cycle_blocked"
        and "not in the allowed model list" in reason
        and "research provider settings invalid" in reason
    )


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
        if _stale_rotation_model_rejection(result, payload):
            rejected_model = str(payload.get("model") or "").strip()
            rejection_reason = str(result.get("reason") or "")
            retry_payload = dict(payload)
            retry_payload.pop("model", None)
            result = _post_json(
                base_url,
                "/control/api/research/run-cycle",
                token,
                retry_payload,
                timeout=max(60, max_wait_seconds + 120),
            )
            if isinstance(result, dict):
                result["autopilot_model_retry"] = {
                    "retried_without_model": True,
                    "rejected_model": rejected_model,
                    "rejection_reason": rejection_reason,
                }
    except RemoteDisconnected as exc:
        exit_code = _transient_disconnect_exit(exc, base_url, phase="disconnected")
        if exit_code is not None:
            return exit_code, None
        return _research_autopilot_request_failure_exit(exc)
    except error.HTTPError as exc:
        exit_code, result = _hold_related_conflict_exit(exc)
        if exit_code is not None:
            return exit_code, result
        return _research_autopilot_request_failure_exit(exc)
    except error.URLError as exc:
        exit_code = _transient_disconnect_exit(exc, base_url, phase="unavailable")
        if exit_code is not None:
            return exit_code, None
        return _research_autopilot_request_failure_exit(exc)
    except (TimeoutError, json.JSONDecodeError) as exc:
        return _research_autopilot_request_failure_exit(exc)
    return None, result


def _parse_health_checked_at(value: object) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _enabled_provider_ids(settings: dict) -> set[str]:
    providers = (settings.get("settings") or {}).get("providers") or []
    return {
        str(provider.get("provider_id") or "").strip()
        for provider in providers
        if isinstance(provider, dict)
        and str(provider.get("provider_id") or "").strip()
        and bool(provider.get("enabled", True))
    }


def _health_rows_by_model(settings: dict) -> dict[tuple[str, str], dict]:
    rows: dict[tuple[str, str], dict] = {}
    for row in (settings.get("model_health") or {}).get("models") or []:
        if not isinstance(row, dict):
            continue
        provider_id = str(row.get("provider_id") or "").strip()
        model_id = str(row.get("model_id") or "").strip()
        if provider_id and model_id:
            rows[(provider_id, model_id)] = row
    return rows


def _llm_model_health_check_reason(
    health: dict | None, *, now: float, min_interval_seconds: int
) -> str:
    if not health:
        return "stale_health_check"
    status = str(health.get("status") or "").strip().lower()
    failure = str(health.get("latest_failure_kind") or "").strip()
    if status == "stale":
        return "stale_health_check"
    latest = _parse_health_checked_at(health.get("latest_checked_at"))
    if latest > 0 and now - latest < min_interval_seconds:
        return ""
    if status and status != "healthy":
        return f"unhealthy:{failure}" if failure else f"unhealthy:{status}"
    if latest <= 0 or now - latest >= min_interval_seconds:
        return "stale_health_check"
    return ""


def _llm_model_health_check_priority(item: dict) -> tuple[int, float, str]:
    reason = str(item.get("reason") or "")
    latest = float(item.get("latest_checked_ts") or 0.0)
    if reason == "stale_health_check":
        group = 0
    elif reason.startswith("unhealthy:"):
        group = 1
    else:
        group = 2
    return group, latest, str(item.get("model_id") or "")


def _llm_model_health_check_candidates(
    settings: dict, *, now: float, min_interval_seconds: int
) -> tuple[list[dict], int]:
    provider_ids = _enabled_provider_ids(settings)
    health_by_model = _health_rows_by_model(settings)
    candidates: list[dict] = []
    enabled_model_count = 0
    enabled_models = (settings.get("settings") or {}).get("models") or []
    for model in enabled_models:
        if not isinstance(model, dict) or not bool(model.get("enabled", True)):
            continue
        provider_id = str(model.get("provider_id") or "").strip()
        model_id = str(model.get("model_id") or "").strip()
        if not provider_id or not model_id or provider_id not in provider_ids:
            continue
        enabled_model_count += 1
        health = health_by_model.get((provider_id, model_id))
        reason = _llm_model_health_check_reason(
            health, now=now, min_interval_seconds=min_interval_seconds
        )
        if reason:
            candidates.append(
                {
                    "provider_id": provider_id,
                    "model_id": model_id,
                    "reason": reason,
                    "latest_checked_ts": _parse_health_checked_at(
                        (health or {}).get("latest_checked_at")
                    ),
                }
            )
    return candidates, enabled_model_count


def _run_selected_llm_model_health_checks(
    selected: list[dict], *, base_url: str, token: str, timeout: int
) -> tuple[list[dict], list[dict]]:
    checked: list[dict] = []
    failures: list[dict] = []
    for item in selected:
        payload = {
            "provider_id": item["provider_id"],
            "model_id": item["model_id"],
            "source": "autopilot",
        }
        try:
            checked.append(
                _post_json(
                    base_url,
                    "/control/api/settings/llm/test",
                    token,
                    payload,
                    timeout=timeout,
                )
            )
        except Exception as exc:  # noqa: BLE001 - continue bounded health sampling
            failures.append(
                {
                    "provider_id": item["provider_id"],
                    "model_id": item["model_id"],
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )
    return checked, failures


def _llm_model_format_probe_contracts() -> list[str]:
    raw = os.environ.get(
        "ENOCH_LLM_MODEL_FORMAT_PROBE_CONTRACTS",
        "strict_json,markdown_fenced_json,candidate_json",
    )
    contracts: list[str] = []
    for item in raw.split(","):
        contract = item.strip().lower().replace("-", "_")
        if (
            contract
            in {
                "strict_json",
                "markdown_fenced_json",
                "candidate_json",
            }
            and contract not in contracts
        ):
            contracts.append(contract)
    return contracts


def _llm_model_format_probe_reason(
    health: dict | None, *, now: float, min_interval_seconds: int
) -> str:
    if not health:
        return ""
    endpoint = str(health.get("endpoint_health") or health.get("status") or "").lower()
    if endpoint and endpoint != "healthy":
        return ""
    latest = _parse_health_checked_at(health.get("latest_format_checked_at"))
    if latest > 0 and now - latest < min_interval_seconds:
        return ""
    format_health = str(health.get("format_health") or "").strip().lower()
    if format_health in {"", "unmeasured"}:
        return "stale_format_probe"
    if format_health == "degraded":
        malformed = str(health.get("latest_malformed_kind") or "").strip()
        return f"degraded_format:{malformed}" if malformed else "degraded_format"
    if latest <= 0 or now - latest >= min_interval_seconds:
        return "stale_format_probe"
    return ""


def _enabled_llm_model_identity(
    model: object, provider_ids: set[str]
) -> tuple[str, str]:
    if not isinstance(model, dict) or not bool(model.get("enabled", True)):
        return "", ""
    provider_id = str(model.get("provider_id") or "").strip()
    model_id = str(model.get("model_id") or "").strip()
    if provider_id and model_id and provider_id in provider_ids:
        return provider_id, model_id
    return "", ""


def _llm_model_format_probe_items(
    *,
    provider_id: str,
    model_id: str,
    reason: str,
    latest_ts: float,
    contracts: list[str],
) -> list[dict]:
    return [
        {
            "provider_id": provider_id,
            "model_id": model_id,
            "prompt_contract": contract,
            "contract_index": contract_index,
            "reason": reason,
            "latest_checked_ts": latest_ts,
        }
        for contract_index, contract in enumerate(contracts)
    ]


def _llm_model_format_probe_candidates(
    settings: dict, *, now: float, min_interval_seconds: int, contracts: list[str]
) -> tuple[list[dict], int]:
    provider_ids = _enabled_provider_ids(settings)
    health_by_model = _health_rows_by_model(settings)
    candidates: list[dict] = []
    enabled_model_count = 0
    if not contracts:
        return candidates, enabled_model_count
    enabled_models = (settings.get("settings") or {}).get("models") or []
    for model in enabled_models:
        provider_id, model_id = _enabled_llm_model_identity(model, provider_ids)
        if not provider_id:
            continue
        enabled_model_count += 1
        health = health_by_model.get((provider_id, model_id))
        reason = _llm_model_format_probe_reason(
            health, now=now, min_interval_seconds=min_interval_seconds
        )
        if not reason:
            continue
        latest_ts = _parse_health_checked_at(
            (health or {}).get("latest_format_checked_at")
        )
        candidates.extend(
            _llm_model_format_probe_items(
                provider_id=provider_id,
                model_id=model_id,
                reason=reason,
                latest_ts=latest_ts,
                contracts=contracts,
            )
        )
    return candidates, enabled_model_count


def _llm_model_format_probe_priority(item: dict) -> tuple[int, float, str, int]:
    reason = str(item.get("reason") or "")
    if reason == "stale_format_probe":
        group = 0
    elif reason.startswith("degraded_format"):
        group = 1
    else:
        group = 2
    return (
        group,
        float(item.get("latest_checked_ts") or 0.0),
        str(item.get("model_id") or ""),
        int(item.get("contract_index") or 0),
    )


def _run_selected_llm_model_format_probes(
    selected: list[dict], *, base_url: str, token: str, timeout: int
) -> tuple[list[dict], list[dict]]:
    checked: list[dict] = []
    failures: list[dict] = []
    for item in selected:
        payload = {
            "provider_id": item["provider_id"],
            "model_id": item["model_id"],
            "source": "autopilot",
            "prompt_contract": item["prompt_contract"],
        }
        try:
            checked.append(
                _post_json(
                    base_url,
                    "/control/api/settings/llm/test",
                    token,
                    payload,
                    timeout=timeout,
                )
            )
        except Exception as exc:  # noqa: BLE001 - continue bounded format sampling
            failures.append(
                {
                    "provider_id": item["provider_id"],
                    "model_id": item["model_id"],
                    "prompt_contract": item["prompt_contract"],
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )
    return checked, failures


def run_llm_model_health_checks(base_url: str, token: str) -> dict:
    if not base_url or not token:
        return {
            "ok": True,
            "action": "llm_model_health_checks_skipped",
            "reason": "missing control URL or token",
        }
    if not _truthy("ENOCH_LLM_MODEL_HEALTH_CHECKS_ENABLED", "1"):
        return {
            "ok": True,
            "action": "llm_model_health_checks_skipped",
            "reason": "disabled",
        }
    limit = _bounded_int("ENOCH_LLM_MODEL_HEALTH_CHECK_LIMIT", 2, 0, 20)
    if limit <= 0:
        return {
            "ok": True,
            "action": "llm_model_health_checks_skipped",
            "reason": "limit=0",
        }
    min_interval = _bounded_int(
        "ENOCH_LLM_MODEL_HEALTH_MIN_INTERVAL_SECONDS", 21600, 300, 604800
    )
    timeout = _bounded_int("ENOCH_LLM_MODEL_HEALTH_TIMEOUT_SECONDS", 30, 5, 120)
    try:
        settings = _get_json(base_url, "/control/api/settings/llm", token, timeout=10)
    except Exception as exc:  # noqa: BLE001 - sidecar visibility should not abort tick
        return {
            "ok": False,
            "action": "llm_model_health_checks_failed",
            "reason": f"settings lookup failed: {type(exc).__name__}: {exc}",
        }

    candidates, enabled_model_count = _llm_model_health_check_candidates(
        settings, now=time.time(), min_interval_seconds=min_interval
    )
    selected = sorted(candidates, key=_llm_model_health_check_priority)[:limit]
    selected_reasons = {str(item["model_id"]): str(item["reason"]) for item in selected}
    checked, failures = _run_selected_llm_model_health_checks(
        selected, base_url=base_url, token=token, timeout=timeout
    )

    return {
        "ok": not failures,
        "action": "llm_model_health_checks",
        "checked_count": len(checked),
        "failure_count": len(failures),
        "skipped_count": max(0, enabled_model_count - len(selected)),
        "candidate_count": len(candidates),
        "enabled_model_count": enabled_model_count,
        "limit": limit,
        "selected_reasons": selected_reasons,
        "checked": checked,
        "failures": failures,
    }


def run_llm_model_format_probes(base_url: str, token: str) -> dict:
    if not base_url or not token:
        return {
            "ok": True,
            "action": "llm_model_format_probes_skipped",
            "reason": "missing control URL or token",
        }
    if not _truthy("ENOCH_LLM_MODEL_FORMAT_PROBES_ENABLED", "0"):
        return {
            "ok": True,
            "action": "llm_model_format_probes_skipped",
            "reason": "disabled",
        }
    limit = _bounded_int("ENOCH_LLM_MODEL_FORMAT_PROBE_LIMIT", 2, 0, 20)
    if limit <= 0:
        return {
            "ok": True,
            "action": "llm_model_format_probes_skipped",
            "reason": "limit=0",
        }
    min_interval = _bounded_int(
        "ENOCH_LLM_MODEL_FORMAT_PROBE_MIN_INTERVAL_SECONDS",
        86400,
        300,
        604800,
    )
    timeout = _bounded_int("ENOCH_LLM_MODEL_FORMAT_PROBE_TIMEOUT_SECONDS", 45, 5, 180)
    contracts = _llm_model_format_probe_contracts()
    if not contracts:
        return {
            "ok": True,
            "action": "llm_model_format_probes_skipped",
            "reason": "no contracts configured",
        }
    try:
        settings = _get_json(base_url, "/control/api/settings/llm", token, timeout=10)
    except Exception as exc:  # noqa: BLE001 - sidecar visibility should not abort tick
        return {
            "ok": False,
            "action": "llm_model_format_probes_failed",
            "reason": f"settings lookup failed: {type(exc).__name__}: {exc}",
        }
    candidates, enabled_model_count = _llm_model_format_probe_candidates(
        settings,
        now=time.time(),
        min_interval_seconds=min_interval,
        contracts=contracts,
    )
    selected = sorted(candidates, key=_llm_model_format_probe_priority)[:limit]
    selected_reasons = {
        f"{item['model_id']}:{item['prompt_contract']}": str(item["reason"])
        for item in selected
    }
    checked, failures = _run_selected_llm_model_format_probes(
        selected, base_url=base_url, token=token, timeout=timeout
    )
    return {
        "ok": not failures,
        "action": "llm_model_format_probes",
        "checked_count": len(checked),
        "failure_count": len(failures),
        "skipped_count": max(0, len(candidates) - len(selected)),
        "candidate_count": len(candidates),
        "enabled_model_count": enabled_model_count,
        "limit": limit,
        "contracts": contracts,
        "selected_reasons": selected_reasons,
        "checked": checked,
        "failures": failures,
    }


def _attach_autopilot_sidecars(result: dict, base_url: str, token: str) -> None:
    history_result = append_research_autopilot_history(result)
    result["research_autopilot_history"] = history_result
    result["research_quality_refresh"] = refresh_research_quality_report()
    result["research_quality_window_comparison"] = (
        refresh_research_quality_window_comparison()
    )
    result["research_janitor_llm_review"] = run_quota_gated_janitor_llm_review()
    result["llm_model_health_checks"] = run_llm_model_health_checks(base_url, token)
    result["llm_model_format_probes"] = run_llm_model_format_probes(base_url, token)


def _compact_autopilot_stage(stage: object) -> object:
    if not isinstance(stage, dict):
        return stage
    return {
        key: stage.get(key)
        for key in (
            "stage",
            "ok",
            "action",
            "reason",
            "provider_attempt_status",
            "candidate_count",
            "generation_target_lane",
            "promoted_count",
            "queued_count",
            "project_id",
            "event_id",
        )
        if key in stage
    }


def _compact_sidecar_result(result: object) -> object:
    if not isinstance(result, dict):
        return result
    compact = {
        key: result.get(key)
        for key in (
            "ok",
            "action",
            "reason",
            "returncode",
            "output",
            "limit",
            "checked_count",
            "failure_count",
            "candidate_count",
            "enabled_model_count",
        )
        if key in result
    }
    summary = result.get("summary")
    if isinstance(summary, dict):
        compact["summary"] = {
            key: summary.get(key)
            for key in (
                "reason",
                "batch_count",
                "decision_count",
                "decision_counts",
            )
            if key in summary
        }
    return compact


def _autopilot_stdout_summary(result: dict) -> dict:
    """Return bounded stdout for systemd journals.

    Full run-cycle payloads include nested candidates, prompts, dispatch records,
    and janitor decisions.  Writing all of that to journald can leave a oneshot
    tick appearing to hang after useful work has already completed.  Keep stdout
    as deterministic operator evidence; detailed artifacts remain in the DB and
    sidecar JSON files.
    """

    compact = {
        key: result.get(key)
        for key in (
            "ok",
            "action",
            "reason",
            "trace_id",
            "run_cycle_id",
            "provider_model",
            "generated_count",
            "promoted_count",
            "queued_count",
            "dispatched_count",
            "paper_drafted_count",
            "publication_finalized_count",
            "fresh_generation_skipped",
            "fresh_promotion_skipped",
            "fresh_generation_skip_reason",
        )
        if key in result
    }
    if isinstance(result.get("generation_target_lane"), dict):
        target = result["generation_target_lane"]
        compact["generation_target_lane"] = {
            key: target.get(key)
            for key in (
                "machine_target",
                "worker_role",
                "lane_key",
                "queued_count",
                "queue_deficit",
                "promotable_count",
                "next_autopilot_action",
            )
            if key in target
        }
    if isinstance(result.get("provider_generation_attempt"), dict):
        attempt = result["provider_generation_attempt"]
        compact["provider_generation_attempt"] = {
            key: attempt.get(key)
            for key in (
                "status",
                "provider_model",
                "candidate_count",
                "machine_target",
                "worker_role",
                "latency_ms",
                "reason",
                "failure_kind",
                "error_type",
            )
            if key in attempt
        }
    if isinstance(result.get("stages"), list):
        compact["stages"] = [
            _compact_autopilot_stage(stage) for stage in result["stages"]
        ]
    for key in (
        "research_autopilot_history",
        "research_quality_refresh",
        "research_quality_window_comparison",
        "research_janitor_llm_review",
        "llm_model_health_checks",
        "llm_model_format_probes",
    ):
        if key in result:
            compact[key] = _compact_sidecar_result(result[key])
    warnings = result.get("warnings")
    if isinstance(warnings, list) and warnings:
        compact["warnings"] = [str(item)[:500] for item in warnings[:5]]
    return compact


def _finalize_autopilot_tick(
    result: object, base_url: str = "", token: str = ""
) -> int:
    if not isinstance(result, dict):
        print(json.dumps(result, sort_keys=True))
        return 1
    _attach_autopilot_sidecars(result, base_url, token)
    print(json.dumps(_autopilot_stdout_summary(result), sort_keys=True))
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

    base_url = _base_url(config)
    exit_code = _main_control_hold_exit(base_url, token)
    if exit_code is not None:
        return exit_code

    payload, max_wait_seconds = _build_research_run_cycle_payload()
    exit_code, result = _post_research_run_cycle(
        base_url, token, payload, max_wait_seconds
    )
    if exit_code is not None:
        return exit_code
    return _finalize_autopilot_tick(result, base_url, token)


if __name__ == "__main__":
    raise SystemExit(main())
