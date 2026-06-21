#!/usr/bin/env python3
"""Run bounded prompt-only vs provider-enforced structured-output probes.

The script calls the existing authenticated control-plane LLM test endpoint. It does
not mutate LLM settings or production routing; each row is a manual format probe.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any
from enoch_control_plane.url_safety import urlopen_validated

DEFAULT_MODES: tuple[str, ...] = ("prompt_only", "json_object", "json_schema")
DEFAULT_CONTRACT = "candidate_json"


def matrix_plan(
    *,
    models: list[str],
    modes: list[str],
    prompt_contracts: list[str],
    repeat: int = 1,
) -> list[dict[str, Any]]:
    bounded_repeat = max(1, min(int(repeat), 20))
    return [
        {
            "model_id": model_id,
            "structured_output_mode": mode,
            "prompt_contract": prompt_contract,
            "repeat_index": repeat_index,
        }
        for model_id in models
        for mode in modes
        for prompt_contract in prompt_contracts
        for repeat_index in range(1, bounded_repeat + 1)
    ]


@dataclass(frozen=True)
class ProbeRow:
    provider_id: str
    model_id: str
    prompt_contract: str
    structured_output_mode: str
    ok: bool
    status_code: int | None
    valid_json: bool
    schema_ok: bool
    malformed_kind: str
    recoverable_json_shape: bool
    candidate_count: int
    candidate_title_complete: bool
    candidate_rationale_complete: bool
    finish_reason: str
    visible_chars: int
    latency_ms: int
    response_format_type: str
    error: str
    response_preview: str


def _control_api_url() -> str:
    explicit = os.environ.get("ENOCH_CONTROL_API_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    host = os.environ.get("ENOCH_CONTROL_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = os.environ.get("ENOCH_CONTROL_PORT", "8787").strip() or "8787"
    return f"http://{host}:{port}"


def _bearer_token(args: argparse.Namespace) -> str:
    token = str(args.token or "").strip()
    if token:
        return token
    token = os.environ.get("ENOCH_CONTROL_API_BEARER_TOKEN", "").strip()
    if token:
        return token
    token = os.environ.get("CONTROL_API_BEARER_TOKEN", "").strip()
    if token:
        return token
    raise SystemExit(
        "missing bearer token: pass --token or set ENOCH_CONTROL_API_BEARER_TOKEN"
    )


def _request_json(
    url: str, token: str, payload: dict[str, Any], timeout: int
) -> dict[str, Any]:
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/control/api/settings/llm/test",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen_validated(
            req,
            timeout=timeout,
            field_name="scripts/compare_structured_output_modes.py url",
            allow_private=True,
        ) as resp:
            data = resp.read().decode("utf-8")
            parsed = json.loads(data)
            if isinstance(parsed, dict):
                return parsed
            return {"ok": False, "error": "non-object API response"}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        return {
            "ok": False,
            "status_code": exc.code,
            "error": f"HTTP {exc.code}: {detail}",
        }
    except Exception as exc:  # noqa: BLE001 - CLI should report bounded row errors
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _row(
    *,
    provider_id: str,
    model_id: str,
    prompt_contract: str,
    structured_output_mode: str,
    result: dict[str, Any],
) -> ProbeRow:
    mode = "" if structured_output_mode == "prompt_only" else structured_output_mode
    return ProbeRow(
        provider_id=provider_id,
        model_id=model_id,
        prompt_contract=prompt_contract,
        structured_output_mode=structured_output_mode,
        ok=bool(result.get("ok")),
        status_code=int(result.get("status_code") or 0) or None,
        valid_json=bool(result.get("valid_json")),
        schema_ok=bool(result.get("schema_ok")),
        malformed_kind=str(result.get("malformed_kind") or ""),
        recoverable_json_shape=bool(result.get("recoverable_json_shape")),
        candidate_count=int(result.get("candidate_count") or 0),
        candidate_title_complete=bool(result.get("candidate_title_complete")),
        candidate_rationale_complete=bool(result.get("candidate_rationale_complete")),
        finish_reason=str(result.get("finish_reason") or ""),
        visible_chars=int(result.get("visible_chars") or 0),
        latency_ms=int(result.get("latency_ms") or 0),
        response_format_type=str(result.get("response_format_type") or mode),
        error=str(result.get("error") or ""),
        response_preview=str(result.get("response_preview") or "")[:240],
    )


def run_matrix(
    *,
    url: str,
    token: str,
    provider_id: str,
    models: list[str],
    modes: list[str],
    prompt_contract: str,
    repeat: int,
    timeout: int,
    pause_seconds: float,
) -> list[ProbeRow]:
    rows: list[ProbeRow] = []
    for item in matrix_plan(
        models=models,
        modes=modes,
        prompt_contracts=[prompt_contract],
        repeat=repeat,
    ):
        model_id = item["model_id"]
        mode = item["structured_output_mode"]
        contract = item["prompt_contract"]
        payload: dict[str, Any] = {
            "provider_id": provider_id,
            "model_id": model_id,
            "source": "manual",
            "prompt_contract": contract,
        }
        if mode != "prompt_only":
            payload["structured_output_mode"] = mode
        result = _request_json(url, token, payload, timeout)
        rows.append(
            _row(
                provider_id=provider_id,
                model_id=model_id,
                prompt_contract=contract,
                structured_output_mode=mode,
                result=result,
            )
        )
        if pause_seconds > 0:
            time.sleep(pause_seconds)
    return rows


def summarize(rows: list[ProbeRow]) -> dict[str, Any]:
    by_mode: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = by_mode.setdefault(
            row.structured_output_mode,
            {
                "attempts": 0,
                "ok": 0,
                "valid_json": 0,
                "schema_ok": 0,
                "recoverable_json_shape": 0,
                "invalid_json": 0,
                "complete_candidate": 0,
                "latency_ms_total": 0,
            },
        )
        bucket["attempts"] += 1
        bucket["ok"] += int(row.ok)
        bucket["valid_json"] += int(row.valid_json)
        bucket["schema_ok"] += int(row.schema_ok)
        bucket["recoverable_json_shape"] += int(row.recoverable_json_shape)
        bucket["invalid_json"] += int(row.malformed_kind == "invalid_json")
        bucket["complete_candidate"] += int(
            row.candidate_count >= 1
            and row.candidate_title_complete
            and row.candidate_rationale_complete
        )
        bucket["latency_ms_total"] += row.latency_ms
    for bucket in by_mode.values():
        attempts = max(int(bucket["attempts"]), 1)
        bucket["schema_ok_rate"] = bucket["schema_ok"] / attempts
        bucket["valid_json_rate"] = bucket["valid_json"] / attempts
        bucket["complete_candidate_rate"] = bucket["complete_candidate"] / attempts
        bucket["avg_latency_ms"] = bucket["latency_ms_total"] / attempts
        bucket.pop("latency_ms_total", None)
    return {"mode_summary": by_mode}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="openrouter", dest="provider_id")
    parser.add_argument("--model", action="append", dest="models", required=True)
    parser.add_argument("--mode", action="append", dest="modes", choices=DEFAULT_MODES)
    parser.add_argument("--contract", default=DEFAULT_CONTRACT, dest="prompt_contract")
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Repeat each model/mode/contract probe up to 20 times for stability evidence",
    )
    parser.add_argument("--url", default="", help="Control API base URL")
    parser.add_argument("--token", default="", help="Control API bearer token")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--pause-seconds", type=float, default=0.0)
    parser.add_argument("--output", default="", help="Optional JSON output path")
    args = parser.parse_args(argv)

    url = str(args.url or _control_api_url()).rstrip("/")
    token = _bearer_token(args)
    modes = list(args.modes or DEFAULT_MODES)
    rows = run_matrix(
        url=url,
        token=token,
        provider_id=str(args.provider_id),
        models=list(args.models),
        modes=modes,
        prompt_contract=str(args.prompt_contract),
        repeat=args.repeat,
        timeout=args.timeout,
        pause_seconds=args.pause_seconds,
    )
    report = {
        "source": "compare_structured_output_modes",
        "mutates_production_routing": False,
        "control_api_url": url,
        "provider_id": args.provider_id,
        "prompt_contract": args.prompt_contract,
        "modes": modes,
        "repeat": max(1, min(int(args.repeat), 20)),
        "rows": [asdict(row) for row in rows],
        **summarize(rows),
    }
    encoded = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(encoded + "\n")
    print(encoded)
    return 0 if all(row.status_code != 0 for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
