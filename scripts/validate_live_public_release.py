#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from urllib.request import Request, urlopen

DEFAULT_TARGETS = {
    "launch": "https://alias8818.github.io/enoch-agentic-research-system/",
    "profile": "https://alias8818.github.io/",
    "manifest": "https://alias8818.github.io/enoch-agentic-research-system/ecosystem.json",
    "docs": "https://solo-09d10f60.mintlify.app/",
    "hf_summary": "https://huggingface.co/datasets/aliasocracy/enoch-ai-research-corpus/raw/main/dataset_summary.json",
    "hf_readme": "https://huggingface.co/datasets/aliasocracy/enoch-ai-research-corpus/raw/main/README.md",
}
STALE = ["120 AI-generated", "120/120", "quality gate pass", "run quality gates", "fully auditable"]


def fetch(url: str) -> tuple[str, str]:
    req = Request(url, headers={"Cache-Control": "no-cache", "Pragma": "no-cache", "User-Agent": "enoch-live-validator/1.0"})
    with urlopen(req, timeout=30) as response:
        body = response.read().decode("utf-8", errors="replace")
        return body, response.headers.get("content-type", "")


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def reject_stale(name: str, text: str, failures: list[str]) -> None:
    lowered = text.lower()
    for phrase in STALE:
        require(phrase not in lowered, f"{name} contains stale/unscoped phrase: {phrase}", failures)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate deployed Enoch public URLs after Pages/Mintlify deployment.")
    parser.add_argument("--launch", default=DEFAULT_TARGETS["launch"])
    parser.add_argument("--profile", default=DEFAULT_TARGETS["profile"])
    parser.add_argument("--manifest", default=DEFAULT_TARGETS["manifest"])
    parser.add_argument("--docs", default=DEFAULT_TARGETS["docs"])
    parser.add_argument("--hf-summary", default=DEFAULT_TARGETS["hf_summary"])
    parser.add_argument("--hf-readme", default=DEFAULT_TARGETS["hf_readme"])
    parser.add_argument("--expected-count", type=int, default=385)
    parser.add_argument("--expected-strict-pass", type=int, default=3)
    parser.add_argument("--expected-gate", default="packaging_provenance_gate")
    args = parser.parse_args()
    failures: list[str] = []

    launch, _ = fetch(args.launch)
    profile, _ = fetch(args.profile)
    manifest_text, _ = fetch(args.manifest)
    docs, _ = fetch(args.docs)
    hf_summary_text, _ = fetch(args.hf_summary)
    hf_readme, _ = fetch(args.hf_readme)
    manifest = json.loads(manifest_text)
    hf_summary = json.loads(hf_summary_text)

    reject_stale("launch", launch, failures)
    reject_stale("profile", profile, failures)
    reject_stale("docs", docs, failures)

    require("Run local AI research workflows" in launch, "launch missing proof-first hero", failures)
    require("Run the local proof" in launch, "launch missing local proof section", failures)
    require("packaging/provenance" in launch, "launch missing packaging/provenance wording", failures)
    require("strict claim/evidence" in launch, "launch missing strict claim/evidence audit wording", failures)
    require(f"{args.expected_strict_pass}/{args.expected_count}" in launch, f"launch missing strict audit {args.expected_strict_pass}/{args.expected_count} status", failures)
    require("not peer-reviewed" in launch, "launch missing not-peer-reviewed caveat", failures)
    require(f'name="enoch-corpus-count" content="{args.expected_count}"' in launch, "launch missing corpus-count meta", failures)
    require('name="enoch-build-sha"' in launch and '__GITHUB_SHA__' not in launch, "launch missing injected build SHA", failures)

    require(str(args.expected_count) in profile, f"profile missing {args.expected_count} count", failures)
    require(f"{args.expected_count}/{args.expected_count}" in profile, f"profile missing {args.expected_count}/{args.expected_count} pass count", failures)
    require(f"{args.expected_strict_pass}/{args.expected_count}" in profile, f"profile missing strict audit {args.expected_strict_pass}/{args.expected_count} status", failures)
    require("packaging/provenance" in profile, "profile missing packaging/provenance wording", failures)
    require("strict claim/evidence" in profile, "profile missing strict claim/evidence wording", failures)

    require(manifest.get("artifact_count") == args.expected_count, f"manifest artifact_count != {args.expected_count}", failures)
    require(manifest.get("packaging_provenance_pass_count") == args.expected_count, f"manifest pass_count != {args.expected_count}", failures)
    require(manifest.get("gate_name") == args.expected_gate, f"manifest gate_name != {args.expected_gate}", failures)
    require(manifest.get("strict_claim_evidence_pass_count") == args.expected_strict_pass, f"manifest strict audit pass count should be {args.expected_strict_pass}", failures)
    require(manifest.get("strict_claim_evidence_total_count") == args.expected_count, f"manifest strict audit total != {args.expected_count}", failures)
    require(manifest.get("strict_claim_evidence_gate_name") == "strict_claim_evidence_audit", "manifest missing strict audit gate name", failures)
    require(manifest.get("strict_claim_evidence_gate_status") != "strict_pass", "manifest should not claim strict_pass for current corpus", failures)
    require("scientific_correctness" in manifest.get("not_validated", []), "manifest missing scientific_correctness not_validated", failures)
    for repo_name, repo in (manifest.get("repos") or {}).items():
        require("commit" not in repo, f"manifest still has volatile commit field for {repo_name}", failures)

    require(hf_summary.get("artifact_count") == args.expected_count, f"HF summary artifact_count != {args.expected_count}", failures)
    require(hf_summary.get("strict_claim_evidence_pass_count") == args.expected_strict_pass, f"HF summary strict pass count != {args.expected_strict_pass}", failures)
    require(hf_summary.get("strict_claim_evidence_total_count") == args.expected_count, f"HF summary strict total != {args.expected_count}", failures)
    require(f"This dataset contains {args.expected_count} AI-generated research artifacts" in hf_readme, "HF README missing current artifact count", failures)
    require(f"Current strict claim/evidence audit status is **{args.expected_strict_pass} / {args.expected_count} passing**" in hf_readme, "HF README missing current strict audit count", failures)

    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print("PASS live public release integrity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
