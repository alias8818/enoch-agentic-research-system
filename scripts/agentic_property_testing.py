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
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
            chunks.append(f"# {candidate.relative_to(repo_root)}\n{_read_excerpt(candidate, max_chars=max_chars // 2)}")
        if sum(len(chunk) for chunk in chunks) >= max_chars:
            break
    return "\n\n".join(chunks)[:max_chars]


def write_prompt(repo_root: Path, target: Path, output: Path, *, max_chars: int) -> None:
    target = target.resolve()
    source_excerpt = _read_excerpt(target, max_chars=max_chars)
    test_excerpt = _related_test_excerpt(repo_root, target, max_chars=max_chars)
    prompt = PROMPT_TEMPLATE.format(
        target_path=str(target.relative_to(repo_root) if target.is_relative_to(repo_root) else target),
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
                f"# Proposal: {proposal.name}",
                f"# Rationale: {proposal.rationale}",
                proposal.code,
                "",
            ]
        )
    return "\n".join(parts)


def execute_proposals(repo_root: Path, proposal_file: Path, report_dir: Path, *, pytest_args: list[str] | None = None) -> dict[str, Any]:
    proposals = load_proposals(proposal_file)
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with tempfile.TemporaryDirectory(prefix="enoch-agentic-pbt-") as tmp:
        test_path = Path(tmp) / "test_agentic_property_proposals.py"
        test_path.write_text(_proposal_module(proposals, repo_root), encoding="utf-8")
        cmd = [sys.executable, "-m", "pytest", "-q", str(test_path), *(pytest_args or [])]
        proc = subprocess.run(cmd, cwd=repo_root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    status = "counterexample_found" if proc.returncode else "no_counterexample"
    report_path = report_dir / f"agentic-pbt-{timestamp}.md"
    report_path.write_text(
        "\n".join(
            [
                f"# Agentic PBT report - {status}",
                "",
                f"Proposal file: `{proposal_file}`",
                f"Command: `{' '.join(cmd)}`",
                f"Exit code: `{proc.returncode}`",
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
    return {"status": status, "exit_code": proc.returncode, "report_path": str(report_path), "proposal_count": len(proposals)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--target", type=Path, required=True, help="Python module or script to analyze")
    parser.add_argument("--prompt-output", type=Path, default=Path("artifacts/agentic-pbt-prompt.md"))
    parser.add_argument("--proposal-file", type=Path)
    parser.add_argument("--report-dir", type=Path, default=Path("artifacts/agentic-pbt"))
    parser.add_argument("--max-chars", type=int, default=12000)
    parser.add_argument("--execute-proposals", action="store_true", help="Run Python test code from --proposal-file")
    args, passthrough = parser.parse_known_args(argv)

    repo_root = args.repo_root.resolve()
    target = (repo_root / args.target).resolve() if not args.target.is_absolute() else args.target.resolve()
    if not target.exists() or target.suffix != ".py":
        raise SystemExit(f"target must be an existing Python file: {target}")

    if args.proposal_file and args.execute_proposals:
        result = execute_proposals(repo_root, args.proposal_file.resolve(), (repo_root / args.report_dir).resolve(), pytest_args=passthrough)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1 if result["status"] == "counterexample_found" else 0

    output = (repo_root / args.prompt_output).resolve() if not args.prompt_output.is_absolute() else args.prompt_output.resolve()
    write_prompt(repo_root, target, output, max_chars=args.max_chars)
    print(json.dumps({"status": "prompt_written", "prompt_path": str(output)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
