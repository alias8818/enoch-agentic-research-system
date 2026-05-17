#!/usr/bin/env python3
"""Provider budget preflight for Research Facility generators.

Currently supports Synthetic's quota endpoint. The script never prints API keys
and defaults to fail-closed when quota cannot be fetched or required reserves are
not available.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SYNTHETIC_BASE_URL = "https://api.synthetic.new"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch_json(url: str, *, api_key: str = "", timeout: int) -> dict[str, Any]:
    headers = {"User-Agent": "EnochResearchFacility/0.1"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def synthetic_budget_status(
    payload: dict[str, Any],
    *,
    min_remaining_credits: float,
    min_rolling_remaining: int,
    estimated_requests: int,
    reserve_requests: int,
) -> dict[str, Any]:
    failures: list[str] = []

    def section(name: str) -> dict[str, Any]:
        value = payload.get(name) or {}
        if isinstance(value, dict):
            return value
        failures.append(f"malformed {name} section")
        return {}

    weekly = section("weeklyTokenLimit")
    rolling = section("rollingFiveHourLimit")
    subscription = section("subscription")
    remaining_credits_raw = str(weekly.get("remainingCredits") or "0").replace("$", "")
    try:
        remaining_credits = float(remaining_credits_raw)
    except ValueError:
        remaining_credits = 0.0
    rolling_remaining = int(rolling.get("remaining") or 0)
    subscription_limit = int(subscription.get("limit") or 0)
    subscription_remaining = max(0, subscription_limit - int(subscription.get("requests") or 0))
    required_rolling = max(0, int(estimated_requests)) + max(0, int(reserve_requests))
    if remaining_credits < min_remaining_credits:
        failures.append(f"weekly remaining credits {remaining_credits:.2f} < minimum {min_remaining_credits:.2f}")
    if rolling.get("limited") is True:
        failures.append("rolling five-hour limit is currently limited")
    if rolling_remaining < max(min_rolling_remaining, required_rolling):
        failures.append(f"rolling remaining {rolling_remaining} < required {max(min_rolling_remaining, required_rolling)}")
    if subscription_limit > 0 and subscription_remaining < max(0, int(estimated_requests)):
        failures.append(f"subscription request allowance remaining {subscription_remaining} < estimated requests {estimated_requests}")
    return {
        "ok": not failures,
        "provider": "synthetic",
        "checked_at": utc_now(),
        "estimated_requests": estimated_requests,
        "reserve_requests": reserve_requests,
        "remaining_credits": remaining_credits,
        "min_remaining_credits": min_remaining_credits,
        "rolling_remaining": rolling_remaining,
        "rolling_max": int(rolling.get("max") or 0),
        "rolling_limited": bool(rolling.get("limited")),
        "rolling_next_tick_at": rolling.get("nextTickAt") or "",
        "weekly_next_regen_at": weekly.get("nextRegenAt") or "",
        "weekly_next_regen_credits": weekly.get("nextRegenCredits") or "",
        "subscription_remaining": subscription_remaining,
        "subscription_renews_at": subscription.get("renewsAt") or "",
        "failures": failures,
        "payload_json": payload,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["synthetic"], default="synthetic")
    parser.add_argument("--api-key-env", default="SYNTHETIC_API_KEY")
    parser.add_argument("--base-url", default=os.environ.get("SYNTHETIC_BASE_URL", SYNTHETIC_BASE_URL), help="Synthetic API base URL; can be an exe.dev HTTP proxy such as http://synthetic.int.exe.xyz")
    parser.add_argument("--no-auth", action="store_true", help="do not attach Authorization; use when an exe.dev HTTP proxy injects the header")
    parser.add_argument("--estimated-requests", type=int, default=2)
    parser.add_argument("--reserve-requests", type=int, default=2)
    parser.add_argument("--min-remaining-credits", type=float, default=5.0)
    parser.add_argument("--min-rolling-remaining", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--input-json", type=Path, help="offline quota payload for tests or dry-runs")
    parser.add_argument("--output", type=Path, help="write full JSON report to this path")
    parser.add_argument("--allow-missing-key", action="store_true", help="return ok=false JSON instead of exit 2 when API key is missing")
    args = parser.parse_args(argv)

    if args.input_json:
        payload = json.loads(args.input_json.read_text(encoding="utf-8"))
    else:
        api_key = "" if args.no_auth else os.environ.get(args.api_key_env, "")
        base_url = str(args.base_url).rstrip("/")
        quotas_url = f"{base_url}/v2/quotas"
        if not api_key and not args.no_auth:
            result = {
                "ok": False,
                "provider": args.provider,
                "checked_at": utc_now(),
                "base_url": base_url,
                "auth_mode": "env_bearer",
                "failures": [f"missing API key env {args.api_key_env}"],
            }
            text = json.dumps(result, indent=2, sort_keys=True)
            if args.output:
                args.output.write_text(text + "\n", encoding="utf-8")
            print(text)
            return 0 if args.allow_missing_key else 2
        payload = fetch_json(quotas_url, api_key=api_key, timeout=args.timeout)

    result = synthetic_budget_status(
        payload,
        min_remaining_credits=args.min_remaining_credits,
        min_rolling_remaining=args.min_rolling_remaining,
        estimated_requests=args.estimated_requests,
        reserve_requests=args.reserve_requests,
    )
    if not args.input_json:
        result["base_url"] = str(args.base_url).rstrip("/")
        result["auth_mode"] = "exe_http_proxy" if args.no_auth else "env_bearer"
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
