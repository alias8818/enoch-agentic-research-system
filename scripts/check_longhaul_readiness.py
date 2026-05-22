#!/usr/bin/env python3
"""Check Enoch long-haul/24x7 automation readiness."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from urllib import request


def _load_config(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _base_url(config: dict) -> str:
    host = str(config.get("listen_host") or "127.0.0.1")
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return f"http://{host}:{int(config.get('listen_port') or 8787)}"


def _get_json(url: str, token: str, timeout: int = 30) -> dict:
    req = request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - operator-configured control URL
        return json.loads(resp.read().decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="query the live control-plane readiness endpoint",
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("ENOCH_CONFIG", "/etc/enoch-control-plane/config.json"),
    )
    parser.add_argument("--control-url", default="")
    parser.add_argument("--token", default=os.environ.get("ENOCH_CONTROL_TOKEN", ""))
    parser.add_argument(
        "--json", action="store_true", help="print the full readiness payload"
    )
    args = parser.parse_args(argv)
    if not args.live:
        parser.error(
            "--live is required; offline fixture mode is intentionally not implemented"
        )

    config = _load_config(args.config)
    token = args.token or str(config.get("control_api_bearer_token") or "")
    if not token:
        print("FAIL missing control-plane token", file=sys.stderr)
        return 2
    env_control_url = os.environ.get("ENOCH_CONTROL_URL", "")
    base_url = (
        args.control_url
        or (env_control_url if args.token and env_control_url else "")
        or _base_url(config)
    ).rstrip("/")
    payload = _get_json(f"{base_url}/control/api/v1/automation-readiness", token)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    if payload.get("ok"):
        print("PASS long-haul ready")
        return 0
    for blocker in payload.get("blockers") or [
        payload.get("label") or "long-haul readiness failed"
    ]:
        print(f"FAIL {blocker}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
