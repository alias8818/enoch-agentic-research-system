#!/usr/bin/env python3
"""Offline Research Facility prompt/policy evolution wrapper.

This is intentionally not a live optimizer. It consumes JSONL eval cases from
``build_research_quality_evalset.py`` and emits reviewable artifacts only:

- a candidate prompt/policy addendum;
- a unified diff patch file;
- a machine-readable evolution report.

It does not call providers, mutate production config, write database state,
queue work, dispatch workers, or apply its own patch. Optional DSPy/GEPA can be
added behind this interface later; the default implementation is deterministic
so it is safe for CI and operator smoke tests.
"""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "scripts" / "research_provider_generate.py"
DEFAULT_TARGET = "research-provider-prompt"
INSERT_ANCHOR = "Avoid fake citations. Avoid tiny hyperparameter or +0.05% ideas."


@dataclass(frozen=True)
class EvolutionArtifacts:
    report_path: Path
    prompt_path: Path
    patch_path: Path


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{line_number}: invalid JSONL: {exc}") from exc
        if not isinstance(item, dict):
            raise SystemExit(f"{path}:{line_number}: expected JSON object")
        rows.append(item)
    return rows


def _case_counts(rows: Iterable[dict[str, Any]]) -> Counter[str]:
    return Counter(str(row.get("case_type") or "unknown") for row in rows)


def _policy_clauses(case_counts: Counter[str]) -> list[str]:
    clauses: list[str] = []
    if case_counts.get("duplicateish_candidate"):
        clauses.append(
            "Reject or mark needs_review for near-duplicate mechanisms unless the candidate names the prior failure and states a changed mechanism, stronger baseline, or new evidence path."
        )
    if case_counts.get("proxy_only_positive"):
        clauses.append(
            "Do not treat proxy-only, trace-only, or synthetic-positive evidence as paper-positive; require direct target-stack evidence before paper writing."
        )
    if case_counts.get("supported_but_negative_warning"):
        clauses.append(
            "When a run is supported but still finalize_negative, require the candidate/follow-up to separate mechanism support from publication readiness."
        )
    if case_counts.get("max_depth_followup_ending"):
        clauses.append(
            "Do not propose another automatic follow-up at max depth; require a manually justified new branch with a materially different mechanism."
        )
    if case_counts.get("useful_adjacent_followup"):
        clauses.append(
            "For useful adjacent follow-ups, include a changed hypothesis, at least two concrete evidence items, a success threshold, and a stop condition."
        )
    if not clauses:
        clauses.append(
            "Keep candidate generation falsifiable, non-duplicative, baseline-grounded, and explicit about evidence required before queue promotion."
        )
    return clauses


def _addendum(case_counts: Counter[str]) -> str:
    clauses = _policy_clauses(case_counts)
    bullets = "\n".join(f"- {clause}" for clause in clauses)
    return f"""Research Quality feedback from recent Enoch traces:
{bullets}
""".strip()


def _patch_source(source_text: str, addendum: str) -> str:
    block = f"""
{INSERT_ANCHOR}

Additional Research Quality policy:
{addendum}
""".strip()
    if "Additional Research Quality policy:" in source_text:
        return source_text
    if INSERT_ANCHOR not in source_text:
        raise SystemExit(f"source prompt anchor not found: {INSERT_ANCHOR!r}")
    return source_text.replace(INSERT_ANCHOR, block, 1)


def _write_outputs(*, source_path: Path, output_dir: Path, target: str, evalset_path: Path, cases: list[dict[str, Any]]) -> dict[str, Any]:
    if target != DEFAULT_TARGET:
        raise SystemExit(f"unsupported target {target!r}; supported target: {DEFAULT_TARGET}")
    source_text = source_path.read_text(encoding="utf-8")
    counts = _case_counts(cases)
    addendum = _addendum(counts)
    proposed_text = _patch_source(source_text, addendum)
    output_dir.mkdir(parents=True, exist_ok=True)

    prompt_path = output_dir / "research_provider_prompt_candidate.md"
    patch_path = output_dir / "research_provider_prompt.patch"
    report_path = output_dir / "evolution_report.json"

    prompt_path.write_text(
        "# Research provider prompt candidate\n\n"
        "This is a review artifact. It is not applied to production.\n\n"
        "## Proposed Research Quality addendum\n\n"
        f"{addendum}\n",
        encoding="utf-8",
    )
    diff = difflib.unified_diff(
        source_text.splitlines(keepends=True),
        proposed_text.splitlines(keepends=True),
        fromfile=str(source_path),
        tofile=f"{source_path} (proposed)",
    )
    patch_path.write_text("".join(diff), encoding="utf-8")
    report = {
        "ok": True,
        "schema_version": "enoch_research_prompt_evolution_v1",
        "mode": "offline_patch_only",
        "runtime_effect": "none",
        "target": target,
        "evalset_path": str(evalset_path),
        "source_path": str(source_path),
        "case_count": len(cases),
        "case_counts": dict(sorted(counts.items())),
        "dspy_available": _module_available("dspy"),
        "gepa_available": _module_available("gepa"),
        "optimizer_runtime_used": False,
        "artifacts": {
            "prompt_candidate": str(prompt_path),
            "patch": str(patch_path),
            "report": str(report_path),
        },
        "guardrails": [
            "no provider calls",
            "no database writes",
            "no queue promotion",
            "no worker dispatch",
            "no patch application",
        ],
        "proposed_addendum": addendum,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evalset", type=Path, required=True, help="JSONL eval set from build_research_quality_evalset.py")
    parser.add_argument("--target", default=DEFAULT_TARGET, help=f"evolution target; currently only {DEFAULT_TARGET}")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="source file to diff against")
    parser.add_argument("--output-dir", type=Path, required=True, help="directory for prompt candidate, patch, and report artifacts")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cases = _load_jsonl(args.evalset)
    report = _write_outputs(source_path=args.source, output_dir=args.output_dir, target=args.target, evalset_path=args.evalset, cases=cases)
    print(json.dumps({"ok": True, "output_dir": str(args.output_dir), "case_count": report["case_count"], "artifacts": report["artifacts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
