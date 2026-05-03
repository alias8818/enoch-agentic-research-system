#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PUBLIC_FILES = [
    "README.md",
    "site/index.html",
    "site/site.js",
    "site/ecosystem.json",
    "site/assets/social-card.svg",
    "docs/launch-todo.md",
    "docs/launch-checklist.md",
    "docs/outreach/launch-announcement.md",
]
PROFILE_FILES = ["index.html", "README.md", "assets/social-card.svg"]
DOC_FILES = [
    "README.md",
    "index.mdx",
    "introduction.mdx",
    "deployment.mdx",
    "concepts/evidence-and-artifacts.mdx",
    "configuration/paper-writer.mdx",
    "guides/paper-artifacts.mdx",
]
OWNER_PROFILE_FILES = ["README.md"]
HISTORIC_STALE_COUNT = re.compile(r"\b120\b|120/120")
COUNT_PHRASE = re.compile(r"\b(\d{2,5})\b\s+(AI-generated artifacts indexed|AI-generated research artifacts|generated research artifacts|indexed artifacts|artifacts)", re.I)
PASS_PHRASE = re.compile(r"\b(\d{2,5})\s*/\s*(\d{2,5})\b\s+(pass packaging/provenance|packaging/provenance passed|pass count|quality)", re.I)
QUALITY_WORDING = re.compile(r"quality (?:gates?|scans?|checks?)", re.I)


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def existing(root: Path, rels: list[str]) -> list[Path]:
    return [root / rel for rel in rels if (root / rel).exists()]


def fail(message: str, failures: list[str]) -> None:
    failures.append(message)


def line_for(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def check_counts(paths: list[Path], artifact_count: int, pass_count: int, failures: list[str]) -> None:
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in HISTORIC_STALE_COUNT.finditer(text):
            fail(f"historic stale count in {path}:{line_for(text, match.start())}: {match.group(0)}", failures)
        for match in COUNT_PHRASE.finditer(text):
            value = int(match.group(1))
            if value != artifact_count:
                fail(f"artifact count drift in {path}:{line_for(text, match.start())}: {value} != {artifact_count}", failures)
        for match in PASS_PHRASE.finditer(text):
            left, right = int(match.group(1)), int(match.group(2))
            if (left, right) != (pass_count, artifact_count):
                fail(f"packaging/provenance pass count drift in {path}:{line_for(text, match.start())}: {left}/{right} != {pass_count}/{artifact_count}", failures)


def check_quality_scope(paths: list[Path], failures: list[str]) -> None:
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in QUALITY_WORDING.finditer(text):
            start = max(0, match.start() - 120)
            end = min(len(text), match.end() + 180)
            window = text[start:end].lower()
            if "packaging/provenance" not in window:
                fail(f"unscoped quality wording in {path}:{line_for(text, match.start())}: {match.group(0)}", failures)


def check_required_copy(paths: list[Path], failures: list[str]) -> None:
    combined = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in paths).lower()
    required = ["ai-generated", "not peer-reviewed", "packaging/provenance"]
    for phrase in required:
        if phrase not in combined:
            fail(f"missing required public caveat/copy: {phrase}", failures)
    if "not independently replicated" not in combined and "independent replication" not in combined:
        fail("missing independent-replication caveat", failures)


def check_manifest(committed: dict, generated: dict | None, failures: list[str]) -> None:
    required = [
        "artifact_count",
        "packaging_provenance_pass_count",
        "gate_name",
        "gate_version",
        "gate_scope",
        "validated",
        "not_validated",
        "warnings",
    ]
    for key in required:
        if key not in committed:
            fail(f"manifest missing required key: {key}", failures)
    if generated is None:
        return
    stable_keys = [key for key in required if key != "warnings"]
    for key in stable_keys:
        if committed.get(key) != generated.get(key):
            fail(f"committed manifest drift for {key}: {committed.get(key)!r} != generated {generated.get(key)!r}", failures)
    committed_repos = committed.get("repos") or {}
    generated_repos = generated.get("repos") or {}
    for repo_key, generated_repo in generated_repos.items():
        committed_repo = committed_repos.get(repo_key) or {}
        if committed_repo.get("name") != generated_repo.get("name"):
            fail(f"committed manifest repo name drift for {repo_key}: {committed_repo.get('name')!r} != {generated_repo.get('name')!r}", failures)
        if not committed_repo.get("commit"):
            fail(f"committed manifest missing repo commit for {repo_key}", failures)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Enoch public release accounting and gate wording.")
    parser.add_argument("--system", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--docs", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--owner-profile", type=Path, default=None)
    parser.add_argument("--generated-manifest", type=Path, default=None, help="Optional freshly generated manifest to compare against committed site/ecosystem.json")
    args = parser.parse_args()

    system = args.system.resolve()
    corpus = args.corpus.resolve()
    docs = args.docs.resolve()
    profile = args.profile.resolve()
    owner_profile = args.owner_profile.resolve() if args.owner_profile else None
    failures: list[str] = []

    manifest = load_json(system / "site" / "ecosystem.json")
    generated_manifest = load_json(args.generated_manifest.resolve()) if args.generated_manifest else None
    index = load_json(corpus / "papers" / "index.json")
    report = load_json(corpus / "quality" / "quality_report.json")

    artifact_count = int(index.get("count", len(index.get("papers", []))))
    pass_count = int(report["passed"])
    if manifest.get("artifact_count") != artifact_count:
        fail(f"manifest artifact_count {manifest.get('artifact_count')} != corpus index count {artifact_count}", failures)
    if manifest.get("packaging_provenance_pass_count") != pass_count:
        fail("manifest packaging_provenance_pass_count does not match quality_report passed", failures)
    if manifest.get("packaging_provenance_pass_count") != manifest.get("artifact_count"):
        fail("manifest pass count and artifact count diverge; update public copy accordingly", failures)
    if report.get("gate_name") != "packaging_provenance_gate":
        fail("quality_report gate_name is not packaging_provenance_gate", failures)
    if not report.get("not_validated"):
        fail("quality_report missing not_validated list", failures)
    check_manifest(manifest, generated_manifest, failures)

    public_paths = existing(system, PUBLIC_FILES) + existing(profile, PROFILE_FILES) + existing(docs, DOC_FILES)
    if owner_profile:
        public_paths += existing(owner_profile, OWNER_PROFILE_FILES)
    public_paths += existing(corpus, ["README.md", "quality/quality_report.md", "quality/packaging_provenance_report.md"])

    check_counts(public_paths, int(manifest["artifact_count"]), int(manifest["packaging_provenance_pass_count"]), failures)
    check_quality_scope(public_paths, failures)
    check_required_copy(public_paths, failures)

    if failures:
        for item in failures:
            print(f"FAIL {item}")
        return 1
    print("PASS public release integrity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
