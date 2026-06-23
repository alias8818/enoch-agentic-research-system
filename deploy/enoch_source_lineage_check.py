#!/usr/bin/env python3
"""Run the source-lineage validator as an operational guard."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib import request

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enoch_control_plane.config import GateConfig
from enoch_control_plane.control_plane.alerts import send_pushover
from enoch_control_plane.url_safety import secure_default_service_url
from scripts.validate_source_lineage import build_report, fetch_snapshot, write_report
from enoch_control_plane.url_safety import urlopen_validated

DEFAULT_OUTPUT = Path("/var/lib/enoch-control-plane/source-lineage/latest-report.json")
DEFAULT_CUTOVER = "2026-05-19T17:51:00Z"


def _load_config(path: str) -> GateConfig:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return GateConfig.model_validate(payload)


def _database_url(config: GateConfig, explicit: str = "") -> str:
    return (
        explicit
        or os.environ.get("ENOCH_SOURCE_LINEAGE_DATABASE_URL", "")
        or os.environ.get("ENOCH_SUPABASE_DATABASE_URL", "")
        or os.environ.get("DATABASE_URL", "")
        or config.supabase_database_url
    ).strip()


def _base_url(config: GateConfig) -> str:
    host = str(config.listen_host or "127.0.0.1")
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return os.environ.get("ENOCH_CONTROL_URL") or secure_default_service_url(
        host, int(config.listen_port or 8787)
    )


def _get_control_status(config: GateConfig) -> dict[str, Any]:
    token = str(config.control_api_bearer_token or "").strip()
    if not token:
        return {}
    req = request.Request(
        f"{_base_url(config)}/control/api/status",
        method="GET",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urlopen_validated(
        req,
        timeout=10,
        field_name="deploy/enoch_source_lineage_check.py url",
        allow_private=False,
    ) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _exception_summary(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc)[:500]}"


def _control_hold_skip_result(config: GateConfig) -> dict[str, Any] | None:
    if os.environ.get("ENOCH_SOURCE_LINEAGE_RUN_WHILE_HELD", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return None
    try:
        status = _get_control_status(config)
    except OSError as exc:
        return {
            "ok": True,
            "action": "skipped",
            "reason": "source-lineage check skipped because control-plane hold status could not be verified",
            "control_status_unreachable": True,
            "error": _exception_summary(exc),
        }
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
        "reason": f"source-lineage check skipped while control plane is held: {', '.join(held_by)}",
        "hold_state": {
            "queue_paused": bool(flags.get("queue_paused")),
            "maintenance_mode": bool(flags.get("maintenance_mode")),
            "pause_reason": str(flags.get("pause_reason") or ""),
            "paused_at": str(flags.get("paused_at") or ""),
            "paused_by": str(flags.get("paused_by") or ""),
        },
    }


def _build_report(database_url: str, created_after: str) -> dict[str, Any]:
    snapshot = fetch_snapshot(database_url, created_after=created_after)
    return build_report(snapshot, created_after=created_after)


def _problem_fingerprint(report: dict[str, Any]) -> str:
    payload = {
        "created_after": report.get("created_after"),
        "problem_counts": report.get("problem_counts") or {},
        "problems": report.get("problems") or [],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _blocked_with_problems(report: dict[str, Any]) -> bool:
    return (
        report.get("status") == "blocked"
        and int((report.get("counts") or {}).get("problems") or 0) > 0
    )


def _default_alert() -> dict[str, Any]:
    return {
        "sent": False,
        "attempted": False,
        "suppressed_by_fingerprint": False,
        "detail": "no alert required",
    }


def _read_previous_fingerprint(fingerprint_path: Path) -> str:
    if not fingerprint_path.exists():
        return ""
    return fingerprint_path.read_text(encoding="utf-8").strip()


def _notify_for_blocked(
    config: GateConfig | Any,
    report: dict[str, Any],
) -> dict[str, Any]:
    if getattr(config, "pushover_alerts_enabled", False):
        return _send_alert(config, report)
    return {
        "attempted": False,
        "ok": False,
        "detail": "pushover alerts disabled",
    }


def _blocked_alert(
    config: GateConfig | Any,
    report: dict[str, Any],
    state_dir: Path,
) -> dict[str, Any]:
    state_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = _problem_fingerprint(report)
    fingerprint_path = state_dir / "last-alert-fingerprint"
    if _read_previous_fingerprint(fingerprint_path) == fingerprint:
        return {
            "sent": False,
            "attempted": False,
            "suppressed_by_fingerprint": True,
            "fingerprint": fingerprint,
        }

    notification = _notify_for_blocked(config, report)
    if notification.get("ok") or not getattr(config, "pushover_alerts_enabled", False):
        fingerprint_path.write_text(fingerprint + "\n", encoding="utf-8")
    return {
        "sent": bool(notification.get("ok")),
        "fingerprint": fingerprint,
        **notification,
    }


def _send_alert(config: GateConfig, report: dict[str, Any]) -> dict[str, Any]:
    counts = report.get("counts") or {}
    problem_counts = report.get("problem_counts") or {}
    message = "\n".join(
        [
            "Enoch source-lineage validation failed",
            f"Created-after: {report.get('created_after') or 'unknown'}",
            f"Problems: {counts.get('problems') or 0}",
            f"Candidates checked: {counts.get('candidates') or 0}",
            f"Follow-ups checked: {counts.get('followups') or 0}",
            f"Problem counts: {json.dumps(problem_counts, sort_keys=True)}",
        ]
    )[:1024]
    result = send_pushover(
        config, title="Enoch source-lineage blocked", message=message, priority=1
    )
    return {
        "attempted": result.attempted,
        "ok": result.ok,
        "status_code": result.status_code,
        "detail": result.detail,
    }


def run_check(
    *,
    database_url: str,
    created_after: str,
    output: Path,
    config: GateConfig | Any,
    state_dir: Path,
) -> dict[str, Any]:
    report = _build_report(database_url, created_after)
    write_report(report, output)
    alert = (
        _blocked_alert(config, report, state_dir)
        if _blocked_with_problems(report)
        else _default_alert()
    )
    return {
        "ok": report.get("status") != "blocked",
        "report_path": str(output),
        "report": report,
        "alert": alert,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=os.environ.get("ENOCH_CONFIG")
        or os.environ.get("ENOCH_CONTROL_PLANE_CONFIG")
        or "/etc/enoch-control-plane/config.json",
    )
    parser.add_argument("--database-url", default="")
    parser.add_argument(
        "--created-after",
        default=os.environ.get("ENOCH_SOURCE_LINEAGE_CREATED_AFTER")
        or os.environ.get("ENOCH_SOURCE_LINEAGE_CUTOVER")
        or DEFAULT_CUTOVER,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            os.environ.get("ENOCH_SOURCE_LINEAGE_REPORT_PATH", str(DEFAULT_OUTPUT))
        ),
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path(
            os.environ.get("ENOCH_SOURCE_LINEAGE_STATE_DIR", str(DEFAULT_OUTPUT.parent))
        ),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    config = _load_config(args.config)
    hold_skip = _control_hold_skip_result(config)
    if hold_skip is not None:
        if args.json:
            print(json.dumps(hold_skip, indent=2, sort_keys=True))
        else:
            print(hold_skip["reason"])
        return 0
    database_url = _database_url(config, args.database_url)
    if not database_url:
        raise SystemExit("source-lineage database URL is not configured")
    result = run_check(
        database_url=database_url,
        created_after=args.created_after,
        output=args.output,
        config=config,
        state_dir=args.state_dir,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        counts = result["report"].get("counts") or {}
        print(
            f"source-lineage {result['report'].get('status')} problems={counts.get('problems') or 0} report={result['report_path']}"
        )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
