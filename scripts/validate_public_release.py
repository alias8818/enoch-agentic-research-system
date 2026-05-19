#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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
PERSONAL_SITE_FILES = ["index.html", "writing/index.html", "writing/ai-research-failure-rate.html"]
HISTORIC_STALE_COUNT = re.compile(r"\b120\b|120/120")
COUNT_PHRASE = re.compile(r"\b(\d{2,5})\b(?:\s|<[^>]+>)+(canonical AI-generated artifacts indexed|canonical AI-generated artifacts|AI-generated artifacts indexed|indexed AI artifacts|AI artifacts|AI-generated research artifacts|generated research artifacts|indexed artifacts|canonical AI-generated papers|canonical artifacts|canonical outputs|artifacts)", re.I)
SPLIT_SVG_COUNT_PHRASE = re.compile(r"\b(\d{2,5})\b(?:\s|<[^>]+>)+indexed(?:\s|<[^>]+>)+AI artifacts", re.I)
PASS_PHRASE = re.compile(r"\b(\d{1,5})\s*/\s*(\d{2,5})\b\s+(pass packaging/provenance|pass packaging and provenance|packaging/provenance passed|pass count|quality|pass strict claim/evidence|pass strict claim and evidence|strict claim/evidence audit)", re.I)
OF_PASS_PHRASE = re.compile(r"\b(\d{2,5})\s+of\s+(\d{2,5})\s+pass(?:es)?\s+(?:the\s+)?packaging(?:/| and )provenance", re.I)
STRICT_FAIL_PHRASE = re.compile(r"\b(?:fails?|flags|rejects)\s+(\d{1,5})\s+of\s+(?:its own\s+|its\s+|the\s+)?(\d{2,5})\s+(?:canonical\s+)?outputs", re.I)
PROMISING_COUNT_PHRASE = re.compile(r"\b(\d{1,5})\b(?:\s|<[^>]+>)+(?:bounded\s+)?(?:useful/scale-blocked\s+|useful\s+or\s+scale-blocked\s+|promising\s+)?(?:leads|signals)(?:\s|<[^>]+>)+(?:preserved|outside|that are not|repo|records)", re.I)
FULL_AUDIT_CLAIM = re.compile(r"fully auditable|deeply auditable", re.I)
QUALITY_WORDING = re.compile(r"quality (?:gates?|scans?|checks?)", re.I)
GITHUB_REPO_METADATA = [
    "alias8818/enoch-agentic-research-system",
    "alias8818/enoch-ai-research-corpus",
    "alias8818/enoch-promising-signals",
    "alias8818/enoch-docs",
    "alias8818/alias8818",
    "alias8818/alias8818.github.io",
]

SECRET_LIKE_TOKEN = re.compile(
    r"("
    r"sk-proj-[A-Za-z0-9_-]{20,}"
    r"|sk-ant-api03-[A-Za-z0-9_-]{40,}"
    r"|sk-[A-Za-z0-9]{24,}"
    r"|syn_[A-Za-z0-9]{20,}"
    r"|hf_[A-Za-z0-9]{20,}"
    r"|gh[pousr]_[A-Za-z0-9_]{20,}"
    r"|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"
    r"|Authorization:\s*Bearer\s*[A-Za-z0-9._~+/=-]{24,}"
    r"|(?:OPENAI|ANTHROPIC|SYNTHETIC|GITHUB|HF|HUGGINGFACE|SUPABASE|ENOCH|CONTROL|CALLBACK|DATABASE|POSTGRES)[_-]?(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|BEARER|DATABASE[_-]?URL)\s*[=:]\s*[A-Za-z0-9._~:/?#[\]@!$&'()*+,;=%-]{12,}"
    r")"
)
PUBLIC_SECRET_SCAN_EXTENSIONS = {".html", ".js", ".json", ".jsonl", ".md", ".mdx", ".svg", ".txt", ".csv"}


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def existing(root: Path, rels: list[str]) -> list[Path]:
    return [root / rel for rel in rels if (root / rel).exists()]


def fail(message: str, failures: list[str]) -> None:
    failures.append(message)


def line_for(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def corpus_artifact_public_paths(corpus: Path) -> list[Path]:
    roots = [corpus / "papers", corpus / "quality"]
    paths: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in PUBLIC_SECRET_SCAN_EXTENSIONS:
                paths.append(path)
    return paths


def check_public_secret_tokens(paths: list[Path], failures: list[str]) -> None:
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in SECRET_LIKE_TOKEN.finditer(text):
            if "[REDACTED_TOKEN]" in match.group(0):
                continue
            fail(f"secret-like token in public release surface {path}:{line_for(text, match.start())}", failures)


def check_promising_counts(paths: list[Path], promising_signal_count: int, failures: list[str]) -> None:
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in PROMISING_COUNT_PHRASE.finditer(text):
            value = int(match.group(1))
            if value != promising_signal_count:
                fail(f"promising signal count drift in {path}:{line_for(text, match.start())}: {value} != {promising_signal_count}", failures)


def check_counts(paths: list[Path], artifact_count: int, pass_count: int, failures: list[str]) -> None:
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in HISTORIC_STALE_COUNT.finditer(text):
            fail(f"historic stale count in {path}:{line_for(text, match.start())}: {match.group(0)}", failures)
        for pattern in (COUNT_PHRASE, SPLIT_SVG_COUNT_PHRASE):
            for match in pattern.finditer(text):
                value = int(match.group(1))
                if value != artifact_count:
                    fail(f"artifact count drift in {path}:{line_for(text, match.start())}: {value} != {artifact_count}", failures)
        for match in PASS_PHRASE.finditer(text):
            left, right = int(match.group(1)), int(match.group(2))
            phrase = match.group(3).lower()
            if "packaging" in phrase and (left, right) != (pass_count, artifact_count):
                fail(f"packaging/provenance pass count drift in {path}:{line_for(text, match.start())}: {left}/{right} != {pass_count}/{artifact_count}", failures)
        for match in OF_PASS_PHRASE.finditer(text):
            left, right = int(match.group(1)), int(match.group(2))
            if (left, right) != (pass_count, artifact_count):
                fail(f"packaging/provenance pass count drift in {path}:{line_for(text, match.start())}: {left} of {right} != {pass_count} of {artifact_count}", failures)


def check_strict_public_counts(paths: list[Path], artifact_count: int, strict_pass_count: int, failures: list[str]) -> None:
    strict_fail_count = artifact_count - strict_pass_count
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in PASS_PHRASE.finditer(text):
            left, right = int(match.group(1)), int(match.group(2))
            phrase = match.group(3).lower()
            if "packaging" not in phrase and (left, right) != (strict_pass_count, artifact_count):
                fail(f"strict audit pass count drift in {path}:{line_for(text, match.start())}: {left}/{right} != {strict_pass_count}/{artifact_count}", failures)
        for match in STRICT_FAIL_PHRASE.finditer(text):
            left, right = int(match.group(1)), int(match.group(2))
            if (left, right) != (strict_fail_count, artifact_count):
                fail(f"strict audit fail count drift in {path}:{line_for(text, match.start())}: {left} of {right} != {strict_fail_count} of {artifact_count}", failures)


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
        "promising_signal_count",
        "packaging_provenance_pass_count",
        "gate_name",
        "gate_version",
        "gate_scope",
        "validated",
        "not_validated",
        "warnings",
        "strict_claim_evidence_pass_count",
        "strict_claim_evidence_total_count",
        "strict_claim_evidence_gate_name",
        "strict_claim_evidence_gate_status",
    ]
    for key in required:
        if key not in committed:
            fail(f"manifest missing required key: {key}", failures)
    if committed.get("strict_claim_evidence_gate_name") != "strict_claim_evidence_audit":
        fail("manifest strict claim/evidence gate name is not strict_claim_evidence_audit", failures)
    strict_pass_count = int(committed.get("strict_claim_evidence_pass_count") or 0)
    if strict_pass_count < 0 or strict_pass_count > int(committed.get("artifact_count") or 0):
        fail("manifest strict claim/evidence pass count must be between 0 and artifact count", failures)
    if committed.get("strict_claim_evidence_total_count") != committed.get("artifact_count"):
        fail("manifest strict claim/evidence total must match artifact count", failures)
    if committed.get("strict_claim_evidence_gate_status") == "strict_pass" and committed.get("strict_claim_evidence_pass_count") != committed.get("artifact_count"):
        fail("manifest strict audit status cannot be strict_pass unless every artifact passes", failures)
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
        if "commit" in committed_repo:
            fail(f"committed manifest should not contain volatile repo commit for {repo_key}", failures)


def fetch_github_repo_metadata(repo: str) -> dict:
    req = Request(
        f"https://api.github.com/repos/{repo}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "enoch-public-release-validator/1.0",
        },
    )
    try:
        with urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code not in {403, 404}:
            raise
        # Public unauthenticated GitHub REST calls are rate-limited aggressively,
        # and private repos return 404 until flipped public.
        # Prefer the authenticated gh CLI fallback so the release validator remains
        # deterministic on developer machines and CI runners that already have gh
        # credentials configured.
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{repo}"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except OSError as subprocess_exc:
            raise URLError(f"gh fallback failed: {type(subprocess_exc).__name__}: {subprocess_exc}") from subprocess_exc
        if result.returncode != 0:
            raise exc
        return json.loads(result.stdout)


def check_github_metadata(artifact_count: int, failures: list[str], promising_signal_count: int = 0) -> None:
    expected_corpus_prefix = f"{artifact_count} AI-generated research artifacts produced by Enoch"
    expected_promising_prefix = f"{promising_signal_count} bounded Enoch promising signals"
    expected_homepage = "https://alias8818.github.io/enoch-agentic-research-system/"
    for repo in GITHUB_REPO_METADATA:
        try:
            metadata = fetch_github_repo_metadata(repo)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            fail(f"could not fetch GitHub repo metadata for {repo}: {exc}", failures)
            continue
        description = str(metadata.get("description") or "")
        homepage = str(metadata.get("homepage") or "")
        metadata_text = f"{description} {homepage}"
        for match in HISTORIC_STALE_COUNT.finditer(metadata_text):
            fail(f"historic stale count in GitHub metadata for {repo}: {match.group(0)}", failures)
        for match in COUNT_PHRASE.finditer(metadata_text):
            value = int(match.group(1))
            if value != artifact_count:
                fail(f"artifact count drift in GitHub metadata for {repo}: {value} != {artifact_count}", failures)
        if repo == "alias8818/enoch-ai-research-corpus":
            if not description.startswith(expected_corpus_prefix):
                fail(f"corpus GitHub description does not start with {expected_corpus_prefix!r}: {description!r}", failures)
            if homepage != expected_homepage:
                fail(f"corpus GitHub homepage drift: {homepage!r} != {expected_homepage!r}", failures)
        if repo == "alias8818/enoch-promising-signals" and promising_signal_count:
            if not description.startswith(expected_promising_prefix):
                fail(f"promising signals GitHub description does not start with {expected_promising_prefix!r}: {description!r}", failures)
            if homepage != expected_homepage:
                fail(f"promising signals GitHub homepage drift: {homepage!r} != {expected_homepage!r}", failures)



def promising_signal_public_paths(promising: Path) -> list[Path]:
    roots = [promising / "README.md", promising / "docs", promising / "data", promising / "schemas", promising / "signals", promising / "templates"]
    paths: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix.lower() in PUBLIC_SECRET_SCAN_EXTENSIONS:
            paths.append(root)
        elif root.exists():
            for path in root.rglob("*"):
                if path.is_file() and path.suffix.lower() in PUBLIC_SECRET_SCAN_EXTENSIONS:
                    paths.append(path)
    return paths


def check_promising_signals_repo(promising: Path, expected_count: int, failures: list[str]) -> None:
    signals_path = promising / "data" / "signals.jsonl"
    validator = promising / "scripts" / "validate.py"
    public_validator = promising / "scripts" / "validate_public_trust_surfaces.py"
    if not signals_path.exists():
        fail(f"promising signals repo missing data/signals.jsonl: {signals_path}", failures)
        return
    if not validator.exists():
        fail("promising signals repo missing scripts/validate.py", failures)
    if not public_validator.exists():
        fail("promising signals repo missing scripts/validate_public_trust_surfaces.py", failures)
    records = [json.loads(line) for line in signals_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(records) != expected_count:
        fail(f"promising_signal_count drift: {len(records)} != {expected_count}", failures)
    allowed = {"useful_signal", "promising_if_scaled", "compute_scale_blocked"}
    for record in records:
        project_id = str(record.get("project_id") or "<missing>")
        if record.get("status") not in allowed:
            fail(f"promising signal {project_id} has invalid status {record.get('status')!r}", failures)
        disclaimer = record.get("do_not_overclaim") if isinstance(record.get("do_not_overclaim"), dict) else {}
        if "not validated papers" not in str(disclaimer.get("disclaimer") or ""):
            fail(f"promising signal {project_id} missing not-validated-papers disclaimer", failures)
        evidence = record.get("evidence") if isinstance(record.get("evidence"), dict) else {}
        if evidence.get("public_evidence_copied") is not False:
            fail(f"promising signal {project_id} public_evidence_copied must be false", failures)
    for script in (validator, public_validator):
        if script.exists():
            result = subprocess.run([sys.executable, str(script)], cwd=promising, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if result.returncode != 0:
                fail(f"promising signals validator failed: {script.name}\n" + result.stdout.strip(), failures)

def check_hf_export(hf_export: Path, artifact_count: int, strict_pass_count: int, failures: list[str]) -> None:
    summary_path = hf_export / "dataset_summary.json"
    readme_path = hf_export / "README.md"
    if not summary_path.exists():
        fail(f"HF export missing dataset_summary.json: {summary_path}", failures)
        return
    if not readme_path.exists():
        fail(f"HF export missing README.md: {readme_path}", failures)
        return
    try:
        summary = load_json(summary_path)
    except json.JSONDecodeError as exc:
        fail(f"HF export dataset_summary.json is invalid JSON: {exc}", failures)
        return
    if int(summary.get("artifact_count") or -1) != artifact_count:
        fail(f"HF export artifact_count {summary.get('artifact_count')} != {artifact_count}", failures)
    if int(summary.get("strict_claim_evidence_pass_count") or -1) != strict_pass_count:
        fail(f"HF export strict pass count {summary.get('strict_claim_evidence_pass_count')} != {strict_pass_count}", failures)
    if int(summary.get("strict_claim_evidence_total_count") or -1) != artifact_count:
        fail(f"HF export strict total {summary.get('strict_claim_evidence_total_count')} != {artifact_count}", failures)
    readme = readme_path.read_text(encoding="utf-8", errors="replace")
    expected_fragments = [
        f"This dataset contains {artifact_count} AI-generated research artifacts",
        f"current public corpus indexes **{artifact_count} AI-generated research artifacts**",
        f"Current strict claim/evidence audit status is **{strict_pass_count} / {artifact_count} passing**",
    ]
    for fragment in expected_fragments:
        if fragment not in readme:
            fail(f"HF export README missing current count fragment: {fragment}", failures)


def check_corpus_public_trust_validator(corpus: Path, failures: list[str], *, execute: bool = False) -> None:
    corpus_trust_validator = corpus / "scripts" / "validate_public_trust_surfaces.py"
    if not corpus_trust_validator.exists():
        fail("missing corpus public trust validator", failures)
        return
    if not execute:
        return
    result = subprocess.run([sys.executable, str(corpus_trust_validator)], cwd=corpus, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        fail("corpus public trust validator failed:\n" + result.stdout.strip(), failures)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Enoch public release accounting and gate wording.")
    parser.add_argument("--system", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--docs", type=Path, required=True)
    parser.add_argument("--promising", type=Path, default=None)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--owner-profile", type=Path, default=None)
    parser.add_argument("--personal-site", type=Path, default=None)
    parser.add_argument("--hf-export", type=Path, default=None)
    parser.add_argument("--generated-manifest", type=Path, default=None, help="Optional freshly generated manifest to compare against committed site/ecosystem.json")
    parser.add_argument("--skip-github-metadata", action="store_true", help="Skip live GitHub repository About/description checks for offline validation")
    parser.add_argument("--execute-corpus-validator", action="store_true", help="Opt in to executing the sibling corpus validator script")
    args = parser.parse_args(argv)

    system = args.system.resolve()
    corpus = args.corpus.resolve()
    docs = args.docs.resolve()
    promising = args.promising.resolve() if args.promising else None
    profile = args.profile.resolve()
    owner_profile = args.owner_profile.resolve() if args.owner_profile else None
    personal_site = args.personal_site.resolve() if args.personal_site else None
    hf_export = args.hf_export.resolve() if args.hf_export else None
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
    promising_count = int(manifest.get("promising_signal_count") or 0)
    if promising:
        check_promising_signals_repo(promising, promising_count, failures)
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
    if personal_site:
        public_paths += existing(personal_site, PERSONAL_SITE_FILES)
    public_paths += existing(corpus, ["README.md", "quality/quality_report.md", "quality/packaging_provenance_report.md"])
    promising_paths = promising_signal_public_paths(promising) if promising else []

    check_public_secret_tokens(public_paths + corpus_artifact_public_paths(corpus) + promising_paths, failures)
    check_counts(public_paths, int(manifest["artifact_count"]), int(manifest["packaging_provenance_pass_count"]), failures)
    check_promising_counts(public_paths + promising_paths, promising_count, failures)
    check_strict_public_counts(
        public_paths,
        int(manifest["artifact_count"]),
        int(manifest.get("strict_claim_evidence_pass_count") or 0),
        failures,
    )
    check_quality_scope(public_paths, failures)
    check_required_copy(public_paths, failures)
    check_corpus_public_trust_validator(corpus, failures, execute=bool(args.execute_corpus_validator))
    combined_public = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in public_paths)
    if "strict claim/evidence" not in combined_public.lower():
        fail("missing strict claim/evidence audit public framing", failures)
    for match in FULL_AUDIT_CLAIM.finditer(combined_public):
        if int(manifest.get("strict_claim_evidence_pass_count", 0)) < int(manifest.get("artifact_count") or 0):
            fail(f"public copy implies full strict auditability while strict audit is incomplete: {match.group(0)}", failures)
    if not args.skip_github_metadata:
        check_github_metadata(int(manifest["artifact_count"]), failures, promising_count)
    if hf_export:
        check_hf_export(
            hf_export,
            int(manifest["artifact_count"]),
            int(manifest.get("strict_claim_evidence_pass_count") or 0),
            failures,
        )

    if failures:
        for item in failures:
            print(f"FAIL {item}")
        return 1
    print("PASS public release integrity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
