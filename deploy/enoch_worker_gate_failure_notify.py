#!/usr/bin/env python3
"""Notify operators when the control-plane worker gate unit fails.

This script is intentionally best-effort: systemd OnFailure handlers should not
mask the original failed unit with their own failures. It emits a small JSON
record whether Pushover is configured or not.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enoch_control_plane.config import GateConfig
from enoch_control_plane.control_plane.alerts import send_pushover


def _load_config(path: str) -> GateConfig | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    try:
        return GateConfig.model_validate(payload)
    except Exception:
        return None


def notify_failure(config: GateConfig | None, *, failed_unit: str) -> dict[str, Any]:
    message = (
        f"{failed_unit} failed and systemd will not auto-restart it. "
        "Inspect journalctl for the first traceback before manually restarting."
    )
    if config is None:
        return {
            "ok": False,
            "attempted": False,
            "failed_unit": failed_unit,
            "reason": "config unavailable or invalid; pushover notification skipped",
            "message": message,
        }
    result = send_pushover(
        config,
        title="Enoch worker gate failed",
        message=message,
        priority=1,
    )
    return {
        "ok": bool(result.ok),
        "attempted": bool(result.attempted),
        "failed_unit": failed_unit,
        "detail": result.detail,
        "status_code": result.status_code,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Notify on Enoch worker gate unit failure"
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("ENOCH_CONFIG", "/etc/enoch-control-plane/config.json"),
    )
    parser.add_argument(
        "--failed-unit",
        default=os.environ.get("MONITOR_UNIT", "enoch-worker-gate.service"),
    )
    args = parser.parse_args(argv)

    report = notify_failure(_load_config(args.config), failed_unit=args.failed_unit)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via direct script tests
    raise SystemExit(main())
