#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def git_commit(path: Path, *, allow_unknown: bool = False) -> str:
    try:
        commit = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True, stderr=subprocess.PIPE).strip()
    except Exception as exc:
        if allow_unknown:
            return "unknown"
        raise SystemExit(f"could not resolve git commit for {path}: {exc}") from exc
    if not commit:
        if allow_unknown:
            return "unknown"
        raise SystemExit(f"empty git commit for {path}")
    return commit


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the public Enoch ecosystem manifest from corpus state.")
    parser.add_argument("--corpus", type=Path, required=True, help="Path to alias8818/enoch-ai-research-corpus")
    parser.add_argument("--docs", type=Path, required=True, help="Path to alias8818/enoch-docs")
    parser.add_argument("--system", type=Path, default=Path("."), help="Path to alias8818/enoch-agentic-research-system")
    parser.add_argument("--output", type=Path, default=Path("site/ecosystem.json"))
    parser.add_argument("--allow-unknown-commits", action="store_true", help="Allow unknown commit values for local/offline manifest drafts")
    args = parser.parse_args()

    system = args.system.resolve()
    corpus = args.corpus.resolve()
    docs = args.docs.resolve()
    index = load_json(corpus / "papers" / "index.json")
    report = load_json(corpus / "quality" / "quality_report.json")

    artifact_count = int(index.get("count", len(index.get("papers", []))))
    pass_count = int(report["passed"])
    gate_name = report.get("gate_name", "packaging_provenance_gate")
    gate_version = report.get("gate_version", "1.0")

    manifest = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "artifact_count": artifact_count,
        "packaging_provenance_pass_count": pass_count,
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
            "system": {"name": "alias8818/enoch-agentic-research-system", "commit": git_commit(system, allow_unknown=args.allow_unknown_commits)},
            "corpus": {"name": "alias8818/enoch-ai-research-corpus", "commit": git_commit(corpus, allow_unknown=args.allow_unknown_commits)},
            "docs": {"name": "alias8818/enoch-docs", "commit": git_commit(docs, allow_unknown=args.allow_unknown_commits)},
        },
        "warnings": [
            "Generated artifacts are not peer-reviewed publications.",
            "Packaging/provenance pass does not imply scientific correctness.",
            "Generated artifacts have not been independently replicated unless an individual artifact states otherwise.",
        ],
    }

    if artifact_count != int(report["count"]):
        raise SystemExit(f"corpus index count {artifact_count} does not match gate report count {report['count']}")
    if pass_count > artifact_count:
        raise SystemExit(f"pass count {pass_count} cannot exceed artifact count {artifact_count}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "artifact_count": artifact_count, "packaging_provenance_pass_count": pass_count}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
