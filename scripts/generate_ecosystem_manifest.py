#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def require_nonnegative_int(value: object, *, label: str) -> int:
    if type(value) is not int or value < 0:
        raise SystemExit(f"{label} must be a non-negative integer")
    return value


def require_repo_path(label: str, path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.exists():
        raise SystemExit(f"{label} repo path does not exist: {resolved}")
    if not resolved.is_dir():
        raise SystemExit(f"{label} repo path is not a directory: {resolved}")
    return resolved


def promising_signal_count_from_repo(promising: Path) -> int:
    data_path = promising / "data" / "signals.jsonl"
    manifest_path = promising / "data" / "manifest.json"
    if not data_path.exists():
        raise SystemExit(f"promising signals data file does not exist: {data_path}")
    if not manifest_path.exists():
        raise SystemExit(f"promising signals manifest does not exist: {manifest_path}")
    count = sum(
        1 for line in data_path.read_text(encoding="utf-8").splitlines() if line.strip()
    )
    manifest = load_json(manifest_path)
    manifest_count = require_nonnegative_int(
        manifest.get("record_count"), label="promising signals manifest record count"
    )
    if manifest_count != count:
        raise SystemExit(
            f"promising signals manifest count {manifest_count} does not match data/signals.jsonl count {count}"
        )
    status_counts = manifest.get("status_counts")
    if not isinstance(status_counts, dict):
        raise SystemExit("promising signals manifest status_counts must be an object")
    summed = 0
    for status, value in status_counts.items():
        summed += require_nonnegative_int(
            value, label=f"promising signals status count {status}"
        )
    if summed != count:
        raise SystemExit(
            f"promising signals status_counts sum {summed} does not match data/signals.jsonl count {count}"
        )
    if manifest.get("public_evidence_copied") is not False:
        raise SystemExit(
            "promising signals manifest public_evidence_copied must be false"
        )
    return count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the public Enoch ecosystem manifest from corpus state."
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        required=True,
        help="Path to alias8818/enoch-ai-research-corpus",
    )
    parser.add_argument(
        "--docs", type=Path, required=True, help="Path to alias8818/enoch-docs"
    )
    parser.add_argument(
        "--promising",
        type=Path,
        default=None,
        help="Path to alias8818/enoch-promising-signals",
    )
    parser.add_argument(
        "--system",
        type=Path,
        default=Path("."),
        help="Path to alias8818/enoch-agentic-research-system",
    )
    parser.add_argument("--output", type=Path, default=Path("site/ecosystem.json"))
    args = parser.parse_args()

    require_repo_path("system", args.system)
    corpus = require_repo_path("corpus", args.corpus)
    require_repo_path("docs", args.docs)
    promising = (
        require_repo_path("promising", args.promising) if args.promising else None
    )
    index = load_json(corpus / "papers" / "index.json")
    report = load_json(corpus / "quality" / "quality_report.json")
    claim_audit_path = corpus / "quality" / "claim_evidence_audit.json"
    claim_audit = (
        load_json(claim_audit_path)
        if claim_audit_path.exists()
        else report.get("claim_evidence_audit", {})
    )

    artifact_count = require_nonnegative_int(
        index.get("count", len(index.get("papers", []))), label="corpus index count"
    )
    promising_signal_count = 0
    if promising:
        promising_signal_count = promising_signal_count_from_repo(promising)
    pass_count = require_nonnegative_int(
        report.get("passed"), label="packaging provenance pass count"
    )
    gate_name = report.get("gate_name", "packaging_provenance_gate")
    gate_version = report.get("gate_version", "1.0")

    manifest = {
        "generated_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "artifact_count": artifact_count,
        "promising_signal_count": promising_signal_count,
        "packaging_provenance_pass_count": pass_count,
        "strict_claim_evidence_pass_count": require_nonnegative_int(
            claim_audit.get("strict_claim_evidence_pass_count", 0),
            label="strict claim/evidence pass count",
        ),
        "strict_claim_evidence_total_count": require_nonnegative_int(
            claim_audit.get("count", artifact_count),
            label="strict claim/evidence total count",
        ),
        "strict_claim_evidence_gate_name": claim_audit.get(
            "gate_name", "strict_claim_evidence_audit"
        ),
        "strict_claim_evidence_gate_status": claim_audit.get(
            "status", "blocked_audit_gaps"
        ),
        "strict_claim_evidence_gap_summary": claim_audit.get(
            "gap_summary",
            "Strict claim/evidence audit has not passed for every artifact.",
        ),
        "claim_ledgers_empty": require_nonnegative_int(
            claim_audit.get("claim_ledgers_empty", 0), label="empty claim ledger count"
        ),
        "result_file_refs": require_nonnegative_int(
            claim_audit.get("result_file_refs", 0), label="result file ref count"
        ),
        "result_file_refs_missing": require_nonnegative_int(
            claim_audit.get("result_file_refs_missing", 0),
            label="missing result file ref count",
        ),
        "gate_name": gate_name,
        "gate_version": gate_version,
        "gate_scope": report.get(
            "gate_scope",
            "artifact packaging, provenance, placeholder, and overclaim linting",
        ),
        "validated": report.get("validated", []),
        "not_validated": report.get(
            "not_validated",
            [
                "peer_review",
                "scientific_correctness",
                "external_replication",
                "statistical_power",
                "semantic_output_quality",
                "citation_accuracy",
            ],
        ),
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

    report_count = require_nonnegative_int(
        report.get("count"), label="gate report count"
    )
    if artifact_count != report_count:
        raise SystemExit(
            f"corpus index count {artifact_count} does not match gate report count {report['count']}"
        )
    if pass_count > artifact_count:
        raise SystemExit(
            f"pass count {pass_count} cannot exceed artifact count {artifact_count}"
        )
    strict_total = require_nonnegative_int(
        claim_audit.get("count", artifact_count),
        label="strict claim/evidence total count",
    )
    strict_pass = require_nonnegative_int(
        claim_audit.get("strict_claim_evidence_pass_count", 0),
        label="strict claim/evidence pass count",
    )
    if strict_total != artifact_count:
        raise SystemExit(
            f"strict claim/evidence total {strict_total} does not match artifact count {artifact_count}"
        )
    if strict_pass > strict_total:
        raise SystemExit(
            f"strict claim/evidence pass count {strict_pass} cannot exceed total {strict_total}"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "artifact_count": artifact_count,
                "promising_signal_count": promising_signal_count,
                "packaging_provenance_pass_count": pass_count,
                "strict_claim_evidence_pass_count": strict_pass,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
