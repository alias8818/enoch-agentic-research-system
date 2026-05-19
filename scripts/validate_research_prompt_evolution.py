#!/usr/bin/env python3
"""Validate offline Research Facility prompt-evolution artifacts.

This is a safety gate for artifacts produced by ``evolve_research_prompt.py``.
It checks that the report is patch-only, the patch applies to a temporary copy,
and the proposed source still satisfies deterministic prompt-contract replay
checks. It never modifies the source checkout.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "scripts" / "research_provider_generate.py"
REQUIRED_GUARDRAILS = {
    "no provider calls",
    "no database writes",
    "no queue promotion",
    "no worker dispatch",
    "no patch application",
}
REQUIRED_PROMPT_SNIPPETS = [
    "Additional Research Quality policy:",
    "Do not treat proxy-only",
    "Do not propose another automatic follow-up",
    "generation does not queue work until promotion policy allows it",
]


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: expected JSON object")
    return data


def _run(cmd: list[str], *, cwd: Path, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, input=stdin, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def _copy_source_tree(source_path: Path, tmpdir: Path) -> Path:
    target = tmpdir / "patched_source.py"
    target.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def _retarget_patch(patch_text: str) -> str:
    lines = patch_text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("--- "):
            lines[index] = "--- patched_source.py"
            continue
        if line.startswith("+++ "):
            lines[index] = "+++ patched_source.py"
            break
    return "\n".join(lines) + ("\n" if patch_text.endswith("\n") else "")


def _validate_report(report: dict[str, Any], *, patch_path: Path, prompt_path: Path) -> list[str]:
    failures: list[str] = []
    if report.get("mode") != "offline_patch_only":
        failures.append("report mode must be offline_patch_only")
    if report.get("runtime_effect") != "none":
        failures.append("report runtime_effect must be none")
    if report.get("optimizer_runtime_used") is not False:
        failures.append("optimizer_runtime_used must be false for this deterministic gate")
    artifacts = report.get("artifacts") if isinstance(report.get("artifacts"), dict) else {}
    if artifacts.get("patch") and Path(str(artifacts["patch"])).name != patch_path.name:
        failures.append("report artifacts.patch does not match supplied patch filename")
    if artifacts.get("prompt_candidate") and Path(str(artifacts["prompt_candidate"])).name != prompt_path.name:
        failures.append("report artifacts.prompt_candidate does not match supplied prompt filename")
    guardrails = set(report.get("guardrails") or [])
    missing = sorted(REQUIRED_GUARDRAILS - guardrails)
    if missing:
        failures.append(f"missing guardrails: {', '.join(missing)}")
    if int(report.get("case_count") or 0) < 1:
        failures.append("report case_count must be positive")
    return failures


def _validate_patched_source(source_text: str) -> list[str]:
    failures: list[str] = []
    for snippet in REQUIRED_PROMPT_SNIPPETS:
        if snippet not in source_text:
            failures.append(f"patched source missing prompt snippet: {snippet}")
    return failures


def _non_string_ast_signature(source_text: str) -> str:
    tree = ast.parse(source_text)

    class StripStrings(ast.NodeTransformer):
        def visit_Constant(self, node: ast.Constant) -> ast.AST:  # noqa: N802 - ast API
            if isinstance(node.value, str):
                return ast.copy_location(ast.Constant(value="<prompt-string>"), node)
            return node

    stripped = StripStrings().visit(tree)
    ast.fix_missing_locations(stripped)
    return ast.dump(stripped, include_attributes=False)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True, help="evolution_report.json from evolve_research_prompt.py")
    parser.add_argument("--patch", type=Path, required=True, help="unified diff patch from evolve_research_prompt.py")
    parser.add_argument("--prompt-candidate", type=Path, required=True, help="prompt candidate markdown artifact")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="source file to test patch against")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = _load_json(args.report)
    failures = _validate_report(report, patch_path=args.patch, prompt_path=args.prompt_candidate)
    if not args.patch.read_text(encoding="utf-8").strip():
        failures.append("patch is empty")
    if "Proposed Research Quality addendum" not in args.prompt_candidate.read_text(encoding="utf-8"):
        failures.append("prompt candidate is missing review heading")

    with tempfile.TemporaryDirectory(prefix="enoch-prompt-evolution-") as temp_name:
        tmpdir = Path(temp_name)
        original_source = args.source.read_text(encoding="utf-8")
        patched_source = _copy_source_tree(args.source, tmpdir)
        proc = _run(["patch", "-p0"], cwd=tmpdir, stdin=_retarget_patch(args.patch.read_text(encoding="utf-8")))
        if proc.returncode != 0:
            failures.append(f"patch did not apply cleanly: {proc.stderr.strip() or proc.stdout.strip()}")
        else:
            patched_text = patched_source.read_text(encoding="utf-8")
            failures.extend(_validate_patched_source(patched_text))
            try:
                if _non_string_ast_signature(original_source) != _non_string_ast_signature(patched_text):
                    failures.append("patch changes executable Python structure; only prompt string changes are allowed")
            except SyntaxError as exc:
                failures.append(f"patched source is not valid Python: {exc}")

    result = {
        "ok": not failures,
        "schema_version": "enoch_research_prompt_evolution_validation_v1",
        "runtime_effect": "none",
        "source": str(args.source),
        "patch": str(args.patch),
        "report": str(args.report),
        "prompt_candidate": str(args.prompt_candidate),
        "failures": failures,
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
