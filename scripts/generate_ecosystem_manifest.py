#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def require_repo_path(label: str, path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.exists():
        raise SystemExit(f"{label} repo path does not exist: {resolved}")
    if not resolved.is_dir():
        raise SystemExit(f"{label} repo path is not a directory: {resolved}")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the public Enoch ecosystem manifest from corpus state.")
    parser.add_argument("--corpus", type=Path, required=True, help="Path to alias8818/enoch-ai-research-corpus")
    parser.add_argument("--docs", type=Path, required=True, help="Path to alias8818/enoch-docs")
    parser.add_argument("--promising", type=Path, default=None, help="Path to alias8818/enoch-promising-signals")
    parser.add_argument("--system", type=Path, default=Path("."), help="Path to alias8818/enoch-agentic-research-system")
    parser.add_argument("--output", type=Path, default=Path("site/ecosystem.json"))
    args = parser.parse_args()

    system = require_repo_path("system", args.system)
    corpus = require_repo_path("corpus", args.corpus)
    docs = require_repo_path("docs", args.docs)
    promising = require_repo_path("promising", args.promising) if args.promising else None
    index = load_json(corpus / "papers" / "index.json")
    report = load_json(corpus / "quality" / "quality_report.json")
    claim_audit_path = corpus / "quality" / "claim_evidence_audit.json"
    claim_audit = load_json(claim_audit_path) if claim_audit_path.exists() else report.get("claim_evidence_audit", {})

    artifact_count = int(index.get("count", len(index.get("papers", []))))
    promising_signal_count = 0
    if promising:
        signals_path = promising / "data" / "signals.jsonl"
        promising_signal_count = sum(1 for line in signals_path.read_text(encoding="utf-8").splitlines() if line.strip())
    pass_count = int(report["passed"])
    gate_name = report.get("gate_name", "packaging_provenance_gate")
    gate_version = report.get("gate_version", "1.0")

    manifest = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "artifact_count": artifact_count,
        "promising_signal_count": promising_signal_count,
        "packaging_provenance_pass_count": pass_count,
        "strict_claim_evidence_pass_count": int(claim_audit.get("strict_claim_evidence_pass_count", 0)),
        "strict_claim_evidence_total_count": int(claim_audit.get("count", artifact_count)),
        "strict_claim_evidence_gate_name": claim_audit.get("gate_name", "strict_claim_evidence_audit"),
        "strict_claim_evidence_gate_status": claim_audit.get("status", "blocked_audit_gaps"),
        "strict_claim_evidence_gap_summary": claim_audit.get("gap_summary", "Strict claim/evidence audit has not passed for every artifact."),
        "claim_ledgers_empty": int(claim_audit.get("claim_ledgers_empty", 0)),
        "result_file_refs": int(claim_audit.get("result_file_refs", 0)),
        "result_file_refs_missing": int(claim_audit.get("result_file_refs_missing", 0)),
        "gate_name": gate_name,
        "gate_version": gate_version,
        "gate_scope": report.get("gate_scope", "artifact packaging, provenance, placeholder, and overclaim linting"),
        "validated": report.get("validated", []),
        "not_validated": report.get("not_validated", [
            "peer_review",
            "scientific_correctness",
            "external_replication",
            "statistical_power",
            "semantic_output_quality",
            "citation_accuracy",
        ]),
        "repos": {
            "system": {"name": "alias8818/enoch-agentic-research-system"},
            "corpus": {"name": "alias8818/enoch-ai-research-corpus"},
            "promising_signals": {"name": "alias8818/enoch-promising-signals"},
            "docs": {"name": "alias8818/enoch-docs"},
        },
        "warnings": [
            "Generated artifacts are not peer-reviewed publications.",
            "Promising signals are not validated papers and are separate from the paper corpus.",
            "Packaging/provenance pass does not imply scientific correctness.",
            "Generated artifacts have not been independently replicated unless an individual artifact states otherwise.",
            "Strict claim/evidence audit currently reports blocked audit gaps and must not be conflated with packaging/provenance lint pass.",
        ],
    }

    if artifact_count != int(report["count"]):
        raise SystemExit(f"corpus index count {artifact_count} does not match gate report count {report['count']}")
    if pass_count > artifact_count:
        raise SystemExit(f"pass count {pass_count} cannot exceed artifact count {artifact_count}")
    strict_total = int(claim_audit.get("count", artifact_count))
    strict_pass = int(claim_audit.get("strict_claim_evidence_pass_count", 0))
    if strict_total != artifact_count:
        raise SystemExit(f"strict claim/evidence total {strict_total} does not match artifact count {artifact_count}")
    if strict_pass > strict_total:
        raise SystemExit(f"strict claim/evidence pass count {strict_pass} cannot exceed total {strict_total}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "artifact_count": artifact_count, "promising_signal_count": promising_signal_count, "packaging_provenance_pass_count": pass_count, "strict_claim_evidence_pass_count": strict_pass}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
