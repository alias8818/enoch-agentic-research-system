#!/usr/bin/env python3
"""Agent-assisted property-based testing harness for Python targets.

The script has two deliberately separate modes:

1. Prompt mode writes a focused prompt asking an LLM to propose Hypothesis tests.
2. Execution mode runs an operator-supplied proposal file locally and records any
   counterexample output as a bug-report artifact.

Executing generated tests is intentionally opt-in via --execute-proposals because
proposal code is Python code.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enoch_control_plane.url_safety import validate_http_url

from scripts import research_provider_budget


PROMPT_TEMPLATE = """# Agentic property-based testing request

You are proposing Hypothesis property tests for a Python code target. Your job is
to infer invariants from source code and existing tests, then emit a compact JSON
proposal. Do not include prose outside JSON.

Target path: {target_path}

## Requirements

- Propose tests that use `hypothesis` and `pytest`.
- Prefer deterministic, bounded strategies.
- Focus on invariants, round trips, idempotency, path containment, monotonicity,
  schema/field stability, state-transition safety, and error handling.
- Avoid network calls, sleeps, live credentials, destructive filesystem writes,
  or tests that depend on host-specific state.
- Each proposed test must be self-contained Python code.
- Each proposed test must import every target function it uses.
- Respect function signatures from the source excerpt; for example, pass
  `pathlib.Path` values to parameters annotated as `Path`.
- Do not use Hypothesis APIs that may not exist in the installed version.
  Prefer composing `st.text`, `st.lists`, `st.dictionaries`, and
  `pathlib.Path` manually over APIs such as `st.paths`.
- Collection/import/syntax errors are invalid proposals, not counterexamples.
- Never ask for operator input. Every outcome must be handled by an agentic next
  action: regenerate invalid proposals, minimize/reproduce counterexamples,
  patch confirmed bugs, or advance to the next target.
- Valid output shape:

```json
{{
  "tests": [
    {{
      "name": "short_snake_case_name",
      "rationale": "why this invariant should hold",
      "code": "from hypothesis import given, strategies as st\\n..."
    }}
  ]
}}
```

## Source excerpt

```python
{source_excerpt}
```

## Existing related tests

```python
{test_excerpt}
```
"""


def _artifact_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


@dataclass(frozen=True)
class Proposal:
    name: str
    rationale: str
    code: str


def _read_excerpt(path: Path, *, max_chars: int) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(errors="replace")
    return text[:max_chars]


def _related_test_excerpt(repo_root: Path, target: Path, *, max_chars: int) -> str:
    tests_dir = repo_root / "tests"
    if not tests_dir.exists():
        return ""
    stem = target.stem.replace("test_", "")
    chunks: list[str] = []
    for candidate in sorted(tests_dir.glob("test_*.py")):
        if stem in candidate.stem or target.parent.name in candidate.stem:
            chunks.append(
                f"# {candidate.relative_to(repo_root)}\n{_read_excerpt(candidate, max_chars=max_chars // 2)}"
            )
        if sum(len(chunk) for chunk in chunks) >= max_chars:
            break
    return "\n\n".join(chunks)[:max_chars]


def write_prompt(
    repo_root: Path, target: Path, output: Path, *, max_chars: int
) -> None:
    target = target.resolve()
    source_excerpt = _read_excerpt(target, max_chars=max_chars)
    test_excerpt = _related_test_excerpt(repo_root, target, max_chars=max_chars)
    prompt = PROMPT_TEMPLATE.format(
        target_path=str(
            target.relative_to(repo_root)
            if target.is_relative_to(repo_root)
            else target
        ),
        source_excerpt=source_excerpt,
        test_excerpt=test_excerpt,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(prompt, encoding="utf-8")


def load_proposals(path: Path) -> list[Proposal]:
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_tests = data.get("tests") if isinstance(data, dict) else None
    if not isinstance(raw_tests, list):
        raise ValueError("proposal file must contain a top-level tests list")
    proposals: list[Proposal] = []
    for idx, item in enumerate(raw_tests, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"proposal {idx} must be an object")
        name = str(item.get("name") or f"proposal_{idx}").strip()
        rationale = str(item.get("rationale") or "").strip()
        code = str(item.get("code") or "").strip()
        if not code:
            raise ValueError(f"proposal {name} has no code")
        proposals.append(Proposal(name=name, rationale=rationale, code=code))
    return proposals


def _proposal_module(proposals: list[Proposal], repo_root: Path) -> str:
    parts = [
        "from __future__ import annotations",
        "import sys",
        f"sys.path.insert(0, {str(repo_root)!r})",
        "",
    ]
    for proposal in proposals:
        parts.extend(
            [
                f"# Proposal: {proposal.name!r}",
                f"# Rationale: {proposal.rationale!r}",
                proposal.code,
                "",
            ]
        )
    return "\n".join(parts)


def _execution_status(returncode: int, output: str) -> str:
    if returncode == 0:
        return "no_counterexample"
    execution_error_markers = (
        "No module named pytest",
        "ERROR: file or directory not found",
        "unrecognized arguments:",
        "pytest: error:",
    )
    if returncode in {3, 4, 5} or any(
        marker in output for marker in execution_error_markers
    ):
        return "execution_error"
    proposal_error_markers = (
        "ERROR collecting",
        "Interrupted: ",
        "SyntaxError:",
        "IndentationError:",
        "ImportError:",
        "ModuleNotFoundError:",
        "AttributeError: module 'hypothesis.strategies'",
    )
    fixture_lookup_error = (
        re.search(r"(?m)^E\s+fixture ['\"][^'\"]+['\"] not found", output) is not None
    )
    if (
        returncode == 2
        or fixture_lookup_error
        or any(marker in output for marker in proposal_error_markers)
    ):
        return "proposal_error"
    return "counterexample_found"


def _agentic_next_action(status: str) -> str:
    if status == "no_counterexample":
        return "agent_continue_next_target_or_generate_more_properties"
    if status == "proposal_error":
        return "agent_quarantine_invalid_proposal_and_regenerate"
    if status == "counterexample_found":
        return "agent_minimize_reproduce_patch_and_rerun"
    if status == "execution_error":
        return "agent_fix_harness_invocation_or_environment_and_rerun"
    if status == "max_attempts_exhausted":
        return "agent_quarantine_attempt_batch_and_regenerate"
    return "agent_route_unknown_status_to_quarantine"


def execute_proposals(
    repo_root: Path,
    proposal_file: Path,
    report_dir: Path,
    *,
    pytest_args: list[str] | None = None,
) -> dict[str, Any]:
    proposals = load_proposals(proposal_file)
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _artifact_timestamp()
    module_text = ""
    with tempfile.TemporaryDirectory(prefix="enoch-agentic-pbt-") as tmp:
        test_path = Path(tmp) / "test_agentic_property_proposals.py"
        module_text = _proposal_module(proposals, repo_root)
        test_path.write_text(module_text, encoding="utf-8")
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            str(test_path),
            *(pytest_args or []),
        ]
        proc = subprocess.run(
            cmd,
            cwd=repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
    status = _execution_status(proc.returncode, proc.stdout)
    next_action = _agentic_next_action(status)
    report_path = report_dir / f"agentic-pbt-{timestamp}.md"
    reproducer_path = ""
    if status != "no_counterexample":
        reproducer = report_dir / f"agentic-pbt-{timestamp}-reproducer.py.txt"
        reproducer.write_text(module_text, encoding="utf-8")
        reproducer_path = str(reproducer)
    report_path.write_text(
        "\n".join(
            [
                f"# Agentic PBT report - {status}",
                "",
                f"Proposal file: `{proposal_file}`",
                f"Command: `{' '.join(cmd)}`",
                f"Exit code: `{proc.returncode}`",
                "",
                "## Agentic disposition",
                "",
                "No operator action required.",
                f"Next action: `{next_action}`",
                f"Reproducer: `{reproducer_path or 'not needed'}`",
                "",
                "## Output",
                "",
                "```text",
                proc.stdout[-12000:],
                "```",
            ]
        ),
        encoding="utf-8",
    )
    return {
        "status": status,
        "exit_code": proc.returncode,
        "report_path": str(report_path),
        "proposal_count": len(proposals),
        "agentic_terminal": True,
        "next_action": next_action,
        "reproducer_path": reproducer_path,
    }


def _write_loop_report(
    report_dir: Path, timestamp: str, result: dict[str, Any]
) -> Path:
    path = report_dir / f"agentic-pbt-loop-{timestamp}.md"
    path.write_text(
        "\n".join(
            [
                f"# Agentic PBT loop - {result['status']}",
                "",
                "No operator action required.",
                f"Next action: `{result['next_action']}`",
                f"Attempts: `{result['attempt_count']}`",
                "",
                "## Attempts",
                "",
                *[
                    f"- attempt {idx}: `{attempt.get('status')}` via `{attempt.get('proposal_file')}` -> `{attempt.get('next_action')}`"
                    for idx, attempt in enumerate(result.get("attempts") or [], start=1)
                ],
                "",
                "## JSON",
                "",
                "```json",
                json.dumps(result, indent=2, sort_keys=True),
                "```",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def run_autonomous_loop(
    repo_root: Path,
    target: Path,
    proposal_files: list[Path],
    report_dir: Path,
    *,
    max_attempts: int,
    pytest_args: list[str] | None = None,
) -> dict[str, Any]:
    del target  # Reserved for provider-backed generation and report context.
    report_dir.mkdir(parents=True, exist_ok=True)
    attempts: list[dict[str, Any]] = []
    timestamp = _artifact_timestamp()
    bounded_attempts = max(1, int(max_attempts))
    for proposal_file in proposal_files[:bounded_attempts]:
        attempt = execute_proposals(
            repo_root, proposal_file.resolve(), report_dir, pytest_args=pytest_args
        )
        attempt["proposal_file"] = str(proposal_file)
        attempts.append(attempt)
        if attempt["status"] == "proposal_error":
            continue
        result = {
            "status": attempt["status"],
            "attempt_count": len(attempts),
            "attempts": attempts,
            "agentic_terminal": True,
            "next_action": attempt["next_action"],
        }
        loop_report = _write_loop_report(report_dir, timestamp, result)
        result["loop_report_path"] = str(loop_report)
        return result
    status = "max_attempts_exhausted"
    result = {
        "status": status,
        "attempt_count": len(attempts),
        "attempts": attempts,
        "agentic_terminal": True,
        "next_action": _agentic_next_action(status),
    }
    loop_report = _write_loop_report(report_dir, timestamp, result)
    result["loop_report_path"] = str(loop_report)
    return result


def synthetic_budget_preflight(
    *,
    base_url: str,
    api_key: str,
    no_auth: bool,
    timeout: int,
    estimated_requests: int,
    reserve_requests: int,
    min_remaining_credits: float,
    min_rolling_remaining: int,
) -> dict[str, Any]:
    quotas_url = f"{base_url.rstrip('/')}/v2/quotas"
    payload = research_provider_budget.fetch_json(
        quotas_url, api_key="" if no_auth else api_key, timeout=timeout
    )
    result = research_provider_budget.synthetic_budget_status(
        payload,
        min_remaining_credits=min_remaining_credits,
        min_rolling_remaining=min_rolling_remaining,
        estimated_requests=estimated_requests,
        reserve_requests=reserve_requests,
    )
    result["base_url"] = base_url.rstrip("/")
    result["auth_mode"] = "exe_http_proxy" if no_auth else "env_bearer"
    return result


def generate_provider_proposal(
    *,
    prompt_text: str,
    output: Path,
    openai_base_url: str,
    model: str,
    api_key: str,
    no_auth: bool,
    temperature: float,
    max_tokens: int,
    timeout: int,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key and not no_auth:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Return only valid JSON. No markdown fences. No prose.",
            },
            {"role": "user", "content": prompt_text},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    safe_url = validate_http_url(
        openai_base_url.rstrip("/") + "/chat/completions",
        field_name="agentic pbt provider url",
    )
    req = urllib.request.Request(
        safe_url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = ((data.get("choices") or [{}])[0].get("message") or {}).get(
        "content"
    ) or ""
    proposal = json.loads(content)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(proposal, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "ok": True,
        "proposal_file": str(output),
        "model": model,
        "response_id": data.get("id", ""),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--target", type=Path, required=True, help="Python module or script to analyze"
    )
    parser.add_argument(
        "--prompt-output", type=Path, default=Path("artifacts/agentic-pbt-prompt.md")
    )
    parser.add_argument("--proposal-file", type=Path)
    parser.add_argument("--loop-proposal-file", type=Path, action="append", default=[])
    parser.add_argument(
        "--report-dir", type=Path, default=Path("artifacts/agentic-pbt")
    )
    parser.add_argument("--max-chars", type=int, default=12000)
    parser.add_argument(
        "--execute-proposals",
        action="store_true",
        help="Run Python test code from --proposal-file",
    )
    parser.add_argument(
        "--autonomous-loop",
        action="store_true",
        help="run bounded operator-free proposal execution loop",
    )
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument(
        "--generate-provider-proposal",
        action="store_true",
        help="generate one proposal via an OpenAI-compatible provider",
    )
    parser.add_argument(
        "--provider-base-url",
        default=os.environ.get(
            "ENOCH_AGENTIC_PBT_PROVIDER_BASE_URL", "https://synthetic.int.exe.xyz"
        ),
    )
    parser.add_argument(
        "--openai-base-url",
        default=os.environ.get(
            "ENOCH_AGENTIC_PBT_OPENAI_BASE_URL",
            "https://synthetic.int.exe.xyz/openai/v1",
        ),
    )
    parser.add_argument(
        "--provider-no-auth",
        action="store_true",
        help="use exe.dev HTTP proxy auth injection instead of local API key",
    )
    parser.add_argument("--provider-api-key-env", default="SYNTHETIC_API_KEY")
    parser.add_argument(
        "--provider-model",
        default=os.environ.get("ENOCH_AGENTIC_PBT_MODEL", "hf:zai-org/GLM-5.1"),
    )
    parser.add_argument("--provider-temperature", type=float, default=0.2)
    parser.add_argument("--provider-max-tokens", type=int, default=6000)
    parser.add_argument("--provider-timeout", type=int, default=180)
    parser.add_argument("--min-remaining-credits", type=float, default=5.0)
    parser.add_argument("--min-rolling-remaining", type=int, default=10)
    parser.add_argument("--reserve-requests", type=int, default=1)
    args, passthrough = parser.parse_known_args(argv)
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]

    repo_root = args.repo_root.resolve()
    target = (
        (repo_root / args.target).resolve()
        if not args.target.is_absolute()
        else args.target.resolve()
    )
    if not target.exists() or target.suffix != ".py":
        raise SystemExit(f"target must be an existing Python file: {target}")

    report_dir = (repo_root / args.report_dir).resolve()
    if args.generate_provider_proposal:
        api_key = (
            ""
            if args.provider_no_auth
            else os.environ.get(args.provider_api_key_env, "")
        )
        if not api_key and not args.provider_no_auth:
            result = {
                "ok": False,
                "status": "provider_budget_blocked",
                "agentic_terminal": True,
                "next_action": "agent_retry_after_provider_credentials_or_proxy_are_available",
                "failures": [f"missing API key env {args.provider_api_key_env}"],
            }
            print(json.dumps(result, indent=2, sort_keys=True))
            return 1
        try:
            budget = synthetic_budget_preflight(
                base_url=args.provider_base_url,
                api_key=api_key,
                no_auth=args.provider_no_auth,
                timeout=args.provider_timeout,
                estimated_requests=1,
                reserve_requests=args.reserve_requests,
                min_remaining_credits=args.min_remaining_credits,
                min_rolling_remaining=args.min_rolling_remaining,
            )
        except Exception as exc:
            result = {
                "ok": False,
                "status": "provider_budget_blocked",
                "agentic_terminal": True,
                "next_action": "agent_retry_after_provider_budget_probe_recovers",
                "failures": [f"{type(exc).__name__}: {exc}"],
            }
            print(json.dumps(result, indent=2, sort_keys=True))
            return 1
        if not budget.get("ok"):
            result = {
                "ok": False,
                "status": "provider_budget_blocked",
                "agentic_terminal": True,
                "next_action": "agent_retry_after_provider_budget_regenerates",
                "budget": budget,
            }
            print(json.dumps(result, indent=2, sort_keys=True))
            return 1
        provider_prompt = report_dir / f"{target.stem}-provider-prompt.md"
        write_prompt(repo_root, target, provider_prompt, max_chars=args.max_chars)
        try:
            generated = generate_provider_proposal(
                prompt_text=provider_prompt.read_text(encoding="utf-8"),
                output=report_dir / f"{target.stem}-provider-proposal.json",
                openai_base_url=args.openai_base_url,
                model=args.provider_model,
                api_key=api_key,
                no_auth=args.provider_no_auth,
                temperature=args.provider_temperature,
                max_tokens=args.provider_max_tokens,
                timeout=args.provider_timeout,
            )
        except Exception as exc:
            result = {
                "ok": False,
                "status": "provider_generation_failed",
                "agentic_terminal": True,
                "next_action": "agent_retry_with_smaller_prompt_or_next_provider",
                "failures": [f"{type(exc).__name__}: {exc}"],
                "prompt_path": str(provider_prompt),
            }
            print(json.dumps(result, indent=2, sort_keys=True))
            return 1
        if args.autonomous_loop:
            result = {
                "ok": False,
                "status": "provider_proposal_requires_review",
                "agentic_terminal": True,
                "next_action": "agent_require_operator_review_and_explicit_loop_proposal_file",
                "proposal_file": generated["proposal_file"],
                "prompt_path": str(provider_prompt),
                "budget": budget,
            }
            print(json.dumps(result, indent=2, sort_keys=True))
            return 1
        print(
            json.dumps(
                {"status": "provider_proposal_written", "budget": budget, **generated},
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.autonomous_loop:
        if not args.loop_proposal_file and args.proposal_file:
            args.loop_proposal_file.append(args.proposal_file)
        if not args.loop_proposal_file:
            raise SystemExit(
                "--autonomous-loop requires --loop-proposal-file, --proposal-file, or --generate-provider-proposal"
            )
        result = run_autonomous_loop(
            repo_root,
            target,
            [path.resolve() for path in args.loop_proposal_file],
            report_dir,
            max_attempts=args.max_attempts,
            pytest_args=passthrough,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return (
            1
            if result["status"]
            in {"counterexample_found", "execution_error", "max_attempts_exhausted"}
            else 0
        )

    if args.proposal_file and args.execute_proposals:
        result = execute_proposals(
            repo_root, args.proposal_file.resolve(), report_dir, pytest_args=passthrough
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return (
            1 if result["status"] in {"counterexample_found", "execution_error"} else 0
        )

    output = (
        (repo_root / args.prompt_output).resolve()
        if not args.prompt_output.is_absolute()
        else args.prompt_output.resolve()
    )
    write_prompt(repo_root, target, output, max_chars=args.max_chars)
    print(
        json.dumps(
            {"status": "prompt_written", "prompt_path": str(output)},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
