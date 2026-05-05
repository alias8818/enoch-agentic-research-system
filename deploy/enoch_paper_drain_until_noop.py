#!/usr/bin/env python3
"""Bounded, opt-in drain for completed positive runs that still need papers.

This is intentionally separate from the disabled timer. It drafts at most N papers,
finalizes only the paper it just wrote, and stops on noop or repeated failures.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def env_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise SystemExit(f"{name} must be an integer")
    return max(min_value, min(max_value, value))


def load_token() -> str:
    token = os.environ.get("ENOCH_CONTROL_TOKEN", "").strip()
    if token:
        return token
    token_file = os.environ.get("ENOCH_CONTROL_TOKEN_FILE", "").strip()
    if token_file:
        return Path(token_file).expanduser().read_text(encoding="utf-8").strip()
    config_path = Path(os.environ.get("OMX_WAKE_GATE_CONFIG", "/etc/omx-wake-gate/config.json")).expanduser()
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
        token = str(data.get("omx_inbound_bearer_token") or "").strip()
        if token:
            return token
    fallback = Path.home() / "enoch-control-plane-token.txt"
    if fallback.exists():
        return fallback.read_text(encoding="utf-8").strip()
    raise SystemExit("missing control token: set ENOCH_CONTROL_TOKEN, ENOCH_CONTROL_TOKEN_FILE, or config token")


class ControlClient:
    def __init__(self, base_url: str, token: str, timeout: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def post(self, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=body,
            method="POST",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 - operator configured LAN URL
                raw = resp.read().decode("utf-8", errors="replace")
                return resp.status, json.loads(raw or "{}")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw or "{}")
            except json.JSONDecodeError:
                data = {"raw": raw}
            return exc.code, data


def summarize(index: int, draft: dict[str, Any], rewrite: dict[str, Any] | None, status: int) -> dict[str, Any]:
    paper = draft.get("paper") or {}
    candidate = draft.get("candidate") or {}
    item = (rewrite or {}).get("item") or {}
    writer = (rewrite or {}).get("writer") or {}
    return {
        "i": index,
        "http_status": status,
        "action": draft.get("action"),
        "project": candidate.get("project_name") or paper.get("project_name"),
        "project_id": candidate.get("project_id") or paper.get("project_id"),
        "paper_id": paper.get("paper_id"),
        "paper_status": paper.get("paper_status"),
        "review_status": item.get("review_status"),
        "provider": writer.get("provider"),
        "model": writer.get("model"),
        "fallback_used": writer.get("fallback_used"),
        "reason": draft.get("reason") or draft.get("detail"),
    }


def main() -> int:
    if os.environ.get("ENOCH_ENABLE_PAPER_DRAIN", "0") != "1":
        print(json.dumps({"ok": True, "action": "skipped", "reason": "paper drain disabled; set ENOCH_ENABLE_PAPER_DRAIN=1"}, sort_keys=True))
        return 0
    max_runs = env_int("ENOCH_PAPER_DRAIN_MAX_RUNS", 25, min_value=1, max_value=500)
    fail_limit = env_int("ENOCH_PAPER_DRAIN_FAIL_LIMIT", 3, min_value=1, max_value=50)
    sleep_sec = env_int("ENOCH_PAPER_DRAIN_SLEEP_SEC", 0, min_value=0, max_value=3600)
    timeout = env_int("ENOCH_PAPER_DRAIN_TIMEOUT_SEC", 420, min_value=30, max_value=3600)
    rewrite_new = os.environ.get("ENOCH_PAPER_DRAIN_REWRITE_NEW", "1") == "1"
    requested_by = os.environ.get("ENOCH_PAPER_DRAIN_REQUESTED_BY", "systemd:enoch-paper-drain")
    client = ControlClient(os.environ.get("ENOCH_CONTROL_URL", "http://127.0.0.1:8787"), load_token(), timeout)
    drafted = 0
    failures = 0
    for index in range(1, max_runs + 1):
        draft_status, draft = client.post("/control/papers/draft-next", {"force": False, "requested_by": requested_by})
        rewrite: dict[str, Any] | None = None
        action = str(draft.get("action") or "")
        if draft_status >= 400:
            failures += 1
            print(f"{utc_stamp()} drain[{index}] " + json.dumps({"ok": False, "phase": "draft", "http_status": draft_status, "failure": failures, "response": draft}, sort_keys=True), flush=True)
            if failures >= fail_limit:
                print(f"{utc_stamp()} drain stopped drafted={drafted} failures={failures} reason=fail_limit", flush=True)
                return 1
            continue
        if action != "drafted":
            print(f"{utc_stamp()} drain[{index}] " + json.dumps(summarize(index, draft, rewrite, draft_status), sort_keys=True), flush=True)
            print(f"{utc_stamp()} drain complete drafted={drafted} terminal_action={action or 'unknown'}", flush=True)
            return 0
        drafted += 1
        paper_id = str((draft.get("paper") or {}).get("paper_id") or "")
        if rewrite_new and paper_id:
            encoded = urllib.parse.quote(paper_id, safe="")
            rewrite_status, rewrite = client.post(
                f"/control/api/paper-reviews/{encoded}/rewrite-draft",
                {
                    "idempotency_key": f"paper-drain:{paper_id}:{int(time.time())}",
                    "requested_by": requested_by,
                    "force": True,
                },
            )
            if rewrite_status >= 400:
                failures += 1
                print(f"{utc_stamp()} drain[{index}] " + json.dumps({"ok": False, "phase": "rewrite", "http_status": rewrite_status, "paper_id": paper_id, "failure": failures, "response": rewrite}, sort_keys=True), flush=True)
                if failures >= fail_limit:
                    print(f"{utc_stamp()} drain stopped drafted={drafted} failures={failures} reason=fail_limit", flush=True)
                    return 1
            else:
                failures = 0
        print(f"{utc_stamp()} drain[{index}] " + json.dumps(summarize(index, draft, rewrite, draft_status), sort_keys=True), flush=True)
        if sleep_sec:
            time.sleep(sleep_sec)
    print(f"{utc_stamp()} drain stopped at max_runs={max_runs} drafted={drafted} failures={failures}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
