#!/usr/bin/env python3
"""Provider-backed candidate generation for the Enoch Research Facility.

This module spends provider requests only after a quota/budget preflight.  It
returns candidate JSON for the Research Facility planner; it does not write to
runtime queue tables and does not dispatch work.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts import research_facility_scan

DEFAULT_OPENAI_BASE_URL = "https://api.synthetic.new/openai/v1"
DEFAULT_MODEL = "hf:zai-org/GLM-5.1"
DEFAULT_MAX_TOKENS = 8000
PROMPT_VERSION = "research_provider_generate_v1"

TOPIC_SPREAD = [
    "long-context SSM/Mamba memory for tiny local systems",
    "KV-cache compression/offload for local inference",
    "non-LM speculative decoding and verifier scheduling",
    "1-2 bit quantization with principled residuals",
    "tiny-VRAM fine-tuning and home training",
    "low-trust volunteer/distributed training",
    "agent evidence ledgers and falsification-first reliability",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_generation_prompt(*, max_candidates: int, topic: str, model: str, temperature: float, seed: str) -> str:
    topic_line = topic.strip() or "; ".join(TOPIC_SPREAD)
    return f"""
Return ONLY compact JSON. No markdown. No prose outside JSON.
Top-level JSON object must be: {{"candidates":[candidate_object]}}
The candidates array is required and must contain exactly {max_candidates} object(s).
Never return an empty candidates array. If uncertain, still generate the best falsifiable moonshot.

Generate exactly {max_candidates} Enoch Research Facility candidate idea(s).
Focus: {topic_line}
Metadata: model={model}; temperature={temperature}; seed={seed}

Goal: non-shallow AI systems experiments for local/home AI: lower VRAM/RAM,
cheaper training, longer context, faster inference, safer small agents, or
volunteer/home distributed training. Moonshots are allowed if falsifiable.

Each string value must be short: <= 180 characters.
Each candidate must include these keys:
title, generation_mode, category, priority, hypothesis, mechanism, description,
implementation, baseline_to_beat, success_threshold, kill_condition,
accessibility_delta, expected_artifacts, required_evidence,
likely_failure_modes, estimated_runtime_class, expected_token_budget,
machine_target, model, sandbox, novelty_score, feasibility_score,
accessibility_score, falsifiability_score, novelty_comparison, risk_notes.

Allowed generation_mode:
fresh_grounded, moonshot, implementation_gap, paper_replication_extension,
home_hardware_accessibility, manual_import.
Do not use followup_from_negative unless a parent id is known.

Allowed category:
long-context, kv-compression, spec-decoding, quantization, home-training,
distributed-training, agent-reliability, systems-research.

Fixed values:
expected_artifacts=["run_notes.md","metrics.json","failure_cases.json",".enoch/project_decision.json"]
required_evidence=["baseline comparison","metrics table","failure cases","decision artifact"]
machine_target="gb10"; model="gpt-5.5"; sandbox="danger-full-access"
estimated_runtime_class must be one of: small, medium, large, overnight.
expected_token_budget must be one of: small, medium, large.

Avoid fake citations. Avoid tiny hyperparameter or +0.05% ideas.
""".strip()


def _extract_chat_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(str(part.get("text") or part.get("content") or "") if isinstance(part, dict) else str(part) for part in content)
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    return json.dumps(payload)


def extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        match = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", text, flags=re.S)
        if match:
            text = match.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\{\s*\"candidates\"\s*:\s*\[.*\]\s*\})", text, flags=re.S)
        if not match:
            match = re.search(r"(\[\s*\{.*\}\s*\])", text, flags=re.S)
        if not match:
            raise
        data = json.loads(match.group(1))
    if isinstance(data, list):
        return {"candidates": data}
    if not isinstance(data, dict):
        raise ValueError("provider response JSON must be an object or candidate array")
    return data


def call_openai_compatible_chat(
    *,
    base_url: str,
    model: str,
    prompt: str,
    api_key: str = "",
    temperature: float = 0.8,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: int = 120,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You generate rigorous, falsifiable AI systems research ideas as strict JSON."},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {"Content-Type": "application/json", "User-Agent": "EnochResearchFacility/0.1"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310 - operator-configured provider URL
        return json.loads(response.read().decode("utf-8", errors="replace"))


def candidates_from_provider_response(
    response_payload: dict[str, Any],
    *,
    provider: str,
    provider_model: str,
    prompt: str,
    topic: str,
    temperature: float,
    seed: str,
    default_machine: str,
    default_model: str,
    default_sandbox: str,
) -> list[dict[str, Any]]:
    content = _extract_chat_content(response_payload)
    data = extract_json_object(content)
    raw_candidates = data.get("candidates") or []
    if not isinstance(raw_candidates, list):
        raise ValueError("provider response must contain candidates array")
    source = research_facility_scan.SourceRecord.from_parts(
        source_kind="internal_generated",
        title=f"Provider-backed Research Facility batch: {provider_model}",
        url=f"enoch://research-facility/provider/{provider_model}/{research_facility_scan.sha256_text(seed or utc_now(), 12)}",
        summary=f"Provider-backed generation batch for topic: {topic or 'default spread'}",
        payload_json={
            "provider": provider,
            "provider_model": provider_model,
            "temperature": temperature,
            "seed": seed,
            "prompt_version": PROMPT_VERSION,
        },
    )
    out: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_candidates, start=1):
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        mode = _clean_text(row.get("generation_mode") or "moonshot")
        if mode == "distributed-training":
            mode = "moonshot"
        row["generation_mode"] = mode
        row.setdefault("source_kind", "internal_generated")
        row.setdefault("source_ids", [source.source_id])
        row.setdefault("source_urls", [source.url])
        row.setdefault("source_records", [source.__dict__])
        row.setdefault("expected_artifacts", ["run_notes.md", "metrics.json", "failure_cases.json", ".enoch/project_decision.json"])
        row.setdefault("required_evidence", ["baseline comparison", "metrics table", "failure cases", "decision artifact"])
        row.setdefault("machine_target", default_machine)
        row.setdefault("model", default_model)
        row.setdefault("sandbox", default_sandbox)
        row["provider"] = provider
        row["provider_model"] = provider_model
        row["prompt_version"] = PROMPT_VERSION
        row["generated_by"] = "scripts/research_provider_generate.py"
        row["raw_candidate_json"] = {
            "provider_candidate": raw,
            "provider_response_id": response_payload.get("id", ""),
            "provider_model": provider_model,
            "provider_index": index,
            "topic": topic,
            "temperature": temperature,
            "seed": seed,
            "prompt_version": PROMPT_VERSION,
        }
        out.append(row)
    if not out:
        raise ValueError("provider returned 0 usable candidates")
    return out


def generate_provider_candidates(
    *,
    base_url: str,
    model: str,
    api_key: str = "",
    max_candidates: int = 3,
    topic: str = "",
    temperature: float = 0.8,
    seed: str = "",
    timeout: int = 120,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    attempts: int = 1,
    default_machine: str = "gb10",
    default_model: str = "gpt-5.5",
    default_sandbox: str = "danger-full-access",
) -> dict[str, Any]:
    max_candidates = max(1, min(int(max_candidates), 10))
    seed = seed or utc_now()
    attempts = max(1, min(int(attempts), 3))
    last_error: Exception | None = None
    provider_payload: dict[str, Any] = {}
    candidates: list[dict[str, Any]] = []
    attempt_used = 0
    prompt = ""
    for attempt in range(1, attempts + 1):
        attempt_used = attempt
        attempt_seed = seed if attempt == 1 else f"{seed}:retry-{attempt}"
        prompt = build_generation_prompt(max_candidates=max_candidates, topic=topic, model=model, temperature=temperature, seed=attempt_seed)
        provider_payload = call_openai_compatible_chat(
            base_url=base_url,
            model=model,
            prompt=prompt,
            api_key=api_key,
            temperature=temperature,
            timeout=timeout,
            max_tokens=max_tokens,
        )
        try:
            candidates = candidates_from_provider_response(
                provider_payload,
                provider="synthetic.new",
                provider_model=model,
                prompt=prompt,
                topic=topic,
                temperature=temperature,
                seed=attempt_seed,
                default_machine=default_machine,
                default_model=default_model,
                default_sandbox=default_sandbox,
            )
            break
        except Exception as exc:
            last_error = exc
            if attempt == attempts:
                raise ValueError(f"provider returned no usable candidate JSON after {attempts} attempt(s): {exc}") from exc

    return {
        "ok": True,
        "provider": "synthetic.new",
        "provider_model": model,
        "max_tokens": max_tokens,
        "attempts_requested": attempts,
        "attempts_used": attempt_used,
        "candidate_count": len(candidates),
        "prompt_version": PROMPT_VERSION,
        "generated_at": utc_now(),
        "candidates": candidates,
        "provider_response_id": provider_payload.get("id", ""),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("ENOCH_RESEARCH_PROVIDER_OPENAI_BASE_URL", os.environ.get("SYNTHETIC_OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL)))
    parser.add_argument("--model", default=os.environ.get("ENOCH_RESEARCH_PROVIDER_MODEL", DEFAULT_MODEL))
    parser.add_argument("--api-key-env", default="SYNTHETIC_API_KEY")
    parser.add_argument("--no-auth", action="store_true")
    parser.add_argument("--max-candidates", type=int, default=3)
    parser.add_argument("--topic", default="")
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--seed", default="")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--max-tokens", type=int, default=int(os.environ.get("ENOCH_RESEARCH_PROVIDER_MAX_TOKENS", DEFAULT_MAX_TOKENS)))
    parser.add_argument("--attempts", type=int, default=int(os.environ.get("ENOCH_RESEARCH_PROVIDER_ATTEMPTS", "1")))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    api_key = "" if args.no_auth else os.environ.get(args.api_key_env, "")
    payload = generate_provider_candidates(
        base_url=args.base_url,
        model=args.model,
        api_key=api_key,
        max_candidates=args.max_candidates,
        topic=args.topic,
        temperature=args.temperature,
        seed=args.seed,
        timeout=args.timeout,
        max_tokens=args.max_tokens,
        attempts=args.attempts,
    )
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
