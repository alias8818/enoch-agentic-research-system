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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from enoch_control_plane.url_safety import urlopen_validated


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
    config_path = Path(
        os.environ.get("ENOCH_CONFIG")
        or os.environ.get(
            "ENOCH_CONTROL_PLANE_CONFIG", "/etc/enoch-control-plane/config.json"
        )
    ).expanduser()
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
        token = str(data.get("control_api_bearer_token") or "").strip()
        if token:
            return token
    fallback = Path.home() / "enoch-control-plane-token.txt"
    if fallback.exists():
        return fallback.read_text(encoding="utf-8").strip()
    raise SystemExit(
        "missing control token: set ENOCH_CONTROL_TOKEN, ENOCH_CONTROL_TOKEN_FILE, or config token"
    )


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
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen_validated(
                req,
                timeout=self.timeout,
                field_name="deploy/enoch_paper_drain_until_noop.py url",
                allow_private=True,
            ) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return resp.status, json.loads(raw or "{}")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw or "{}")
            except json.JSONDecodeError:
                data = {"raw": raw}
            return exc.code, data

    def get(self, path: str) -> tuple[int, dict[str, Any]]:
        req = urllib.request.Request(
            self.base_url + path,
            method="GET",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        try:
            with urlopen_validated(
                req,
                timeout=self.timeout,
                field_name="deploy/enoch_paper_drain_until_noop.py url",
                allow_private=True,
            ) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return resp.status, json.loads(raw or "{}")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw or "{}")
            except json.JSONDecodeError:
                data = {"raw": raw}
            return exc.code, data


def summarize(
    index: int, draft: dict[str, Any], rewrite: dict[str, Any] | None, status: int
) -> dict[str, Any]:
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


@dataclass(frozen=True)
class DrainSettings:
    max_runs: int
    fail_limit: int
    sleep_sec: int
    rewrite_new: bool
    requested_by: str
    client: ControlClient


def _print_disabled_skip() -> int:
    print(
        json.dumps(
            {
                "ok": True,
                "action": "skipped",
                "reason": "paper drain disabled; set ENOCH_ENABLE_PAPER_DRAIN=1",
            },
            sort_keys=True,
        )
    )
    return 0


def _load_drain_settings() -> DrainSettings:
    timeout = env_int(
        "ENOCH_PAPER_DRAIN_TIMEOUT_SEC", 420, min_value=30, max_value=3600
    )
    client = ControlClient(
        os.environ.get("ENOCH_CONTROL_URL", "http://127.0.0.1:8787"),
        load_token(),
        timeout,
    )
    return DrainSettings(
        max_runs=env_int("ENOCH_PAPER_DRAIN_MAX_RUNS", 25, min_value=1, max_value=500),
        fail_limit=env_int(
            "ENOCH_PAPER_DRAIN_FAIL_LIMIT", 3, min_value=1, max_value=50
        ),
        sleep_sec=env_int(
            "ENOCH_PAPER_DRAIN_SLEEP_SEC", 0, min_value=0, max_value=3600
        ),
        rewrite_new=os.environ.get("ENOCH_PAPER_DRAIN_REWRITE_NEW", "1") == "1",
        requested_by=os.environ.get(
            "ENOCH_PAPER_DRAIN_REQUESTED_BY", "systemd:enoch-paper-drain"
        ),
        client=client,
    )


def _control_hold_skip_result(client: ControlClient) -> dict[str, Any] | None:
    if os.environ.get("ENOCH_PAPER_DRAIN_RUN_WHILE_HELD", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return None
    status_code, status = client.get("/control/api/status")
    if status_code >= 400:
        return None
    flags = status.get("flags") if isinstance(status.get("flags"), dict) else {}
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
        "reason": f"paper drain skipped while control plane is held: {', '.join(held_by)}",
        "hold_state": {
            "queue_paused": bool(flags.get("queue_paused")),
            "maintenance_mode": bool(flags.get("maintenance_mode")),
            "pause_reason": str(flags.get("pause_reason") or ""),
        },
    }


def _log_drain_failure(
    index: int,
    *,
    phase: str,
    http_status: int,
    failures: int,
    response: dict[str, Any],
    paper_id: str = "",
) -> None:
    payload: dict[str, Any] = {
        "ok": False,
        "phase": phase,
        "http_status": http_status,
        "failure": failures,
        "response": response,
    }
    if paper_id:
        payload["paper_id"] = paper_id
    print(
        f"{utc_stamp()} drain[{index}] " + json.dumps(payload, sort_keys=True),
        flush=True,
    )


def _stop_on_fail_limit(drafted: int, failures: int, fail_limit: int) -> bool:
    if failures < fail_limit:
        return False
    print(
        f"{utc_stamp()} drain stopped drafted={drafted} failures={failures} reason=fail_limit",
        flush=True,
    )
    return True


def _record_http_failure(
    index: int,
    *,
    phase: str,
    http_status: int,
    response: dict[str, Any],
    drafted: int,
    failures: int,
    fail_limit: int,
    paper_id: str = "",
) -> tuple[int, int | None]:
    failures += 1
    _log_drain_failure(
        index,
        phase=phase,
        http_status=http_status,
        failures=failures,
        response=response,
        paper_id=paper_id,
    )
    if _stop_on_fail_limit(drafted, failures, fail_limit):
        return failures, 1
    return failures, None


def _finish_on_terminal_action(
    index: int,
    draft: dict[str, Any],
    draft_status: int,
    drafted: int,
    action: str,
) -> int:
    print(
        f"{utc_stamp()} drain[{index}] "
        + json.dumps(summarize(index, draft, None, draft_status), sort_keys=True),
        flush=True,
    )
    print(
        f"{utc_stamp()} drain complete drafted={drafted} terminal_action={action or 'unknown'}",
        flush=True,
    )
    return 0


def _rewrite_drafted_paper(
    index: int,
    *,
    client: ControlClient,
    draft: dict[str, Any],
    settings: DrainSettings,
    drafted: int,
    failures: int,
) -> tuple[dict[str, Any] | None, int, int | None]:
    paper_id = str((draft.get("paper") or {}).get("paper_id") or "")
    if not (settings.rewrite_new and paper_id):
        return None, failures, None
    encoded = urllib.parse.quote(paper_id, safe="")
    rewrite_status, rewrite = client.post(
        f"/control/api/publication-automation/{encoded}/rewrite-draft",
        {
            "idempotency_key": f"paper-drain:{paper_id}:{int(time.time())}",
            "requested_by": settings.requested_by,
            "force": True,
        },
    )
    if rewrite_status >= 400:
        return rewrite, *_record_http_failure(
            index,
            phase="rewrite",
            http_status=rewrite_status,
            response=rewrite,
            drafted=drafted,
            failures=failures,
            fail_limit=settings.fail_limit,
            paper_id=paper_id,
        )
    return rewrite, 0, None


def _run_drain_loop(settings: DrainSettings) -> int:
    drafted = 0
    failures = 0
    client = settings.client
    for index in range(1, settings.max_runs + 1):
        draft_status, draft = client.post(
            "/control/papers/draft-next",
            {"force": False, "requested_by": settings.requested_by},
        )
        action = str(draft.get("action") or "")
        if draft_status >= 400:
            failures, exit_code = _record_http_failure(
                index,
                phase="draft",
                http_status=draft_status,
                response=draft,
                drafted=drafted,
                failures=failures,
                fail_limit=settings.fail_limit,
            )
            if exit_code is not None:
                return exit_code
            continue
        if action != "drafted":
            return _finish_on_terminal_action(
                index, draft, draft_status, drafted, action
            )
        drafted += 1
        rewrite, failures, exit_code = _rewrite_drafted_paper(
            index,
            client=client,
            draft=draft,
            settings=settings,
            drafted=drafted,
            failures=failures,
        )
        if exit_code is not None:
            return exit_code
        print(
            f"{utc_stamp()} drain[{index}] "
            + json.dumps(
                summarize(index, draft, rewrite, draft_status), sort_keys=True
            ),
            flush=True,
        )
        if settings.sleep_sec:
            time.sleep(settings.sleep_sec)
    print(
        f"{utc_stamp()} drain stopped at max_runs={settings.max_runs} drafted={drafted} failures={failures}",
        flush=True,
    )
    return 0


def main() -> int:
    if os.environ.get("ENOCH_ENABLE_PAPER_DRAIN", "0") != "1":
        return _print_disabled_skip()
    settings = _load_drain_settings()
    hold_skip = _control_hold_skip_result(settings.client)
    if hold_skip is not None:
        print(json.dumps(hold_skip, sort_keys=True))
        return 0
    return _run_drain_loop(settings)


if __name__ == "__main__":
    raise SystemExit(main())
