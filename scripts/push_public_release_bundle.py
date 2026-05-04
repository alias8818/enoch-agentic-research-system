#!/usr/bin/env python3
"""Push the multi-repo public Enoch release bundle in a race-safe order.

The corpus repo's public-release workflow checks out sibling repos from their
current `main` branches. If the corpus is pushed before the system/docs/profile
surfaces are visible on GitHub, that workflow can fail with false-positive count
or manifest drift. This script makes the release order executable:

1. Validate local cross-repo public accounting.
2. Push non-corpus public surfaces first.
3. Verify their remote `main` refs match local HEADs.
4. Push the corpus repo last.
5. Optionally watch the corpus public-release workflow.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Repo:
    key: str
    path: Path
    workflow: str | None = None


def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    printable = " ".join(cmd)
    where = f" ({cwd})" if cwd else ""
    print(f"$ {printable}{where}", flush=True)
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def output(cmd: list[str], *, cwd: Path) -> str:
    return run(cmd, cwd=cwd, capture=True).stdout.strip()


def git(repo: Repo, *args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=repo.path, capture=capture)


def git_output(repo: Repo, *args: str) -> str:
    return output(["git", *args], cwd=repo.path)


def require_clean(repo: Repo) -> None:
    status = git_output(repo, "status", "--porcelain")
    if status:
        raise SystemExit(f"{repo.key} has uncommitted changes; commit or stash before bundle push:\n{status}")


def require_main(repo: Repo) -> None:
    branch = git_output(repo, "branch", "--show-current")
    if branch != "main":
        raise SystemExit(f"{repo.key} is on branch {branch!r}, expected 'main'")


def require_not_behind(repo: Repo) -> None:
    git(repo, "fetch", "origin", "main", "--quiet")
    ahead_behind = git_output(repo, "rev-list", "--left-right", "--count", "origin/main...HEAD")
    behind_s, ahead_s = ahead_behind.split()
    behind, ahead = int(behind_s), int(ahead_s)
    if behind:
        raise SystemExit(f"{repo.key} is behind origin/main by {behind} commit(s); pull/rebase before release")
    print(f"{repo.key}: ahead={ahead}, behind={behind}")


def head(repo: Repo) -> str:
    return git_output(repo, "rev-parse", "HEAD")


def remote_head(repo: Repo) -> str:
    return output(["git", "ls-remote", "origin", "refs/heads/main"], cwd=repo.path).split()[0]


def push_and_verify(repo: Repo, *, push: bool, timeout: int) -> None:
    local = head(repo)
    if push:
        git(repo, "push", "origin", "main")
    deadline = time.time() + timeout
    while True:
        remote = remote_head(repo)
        if remote == local:
            print(f"{repo.key}: remote main verified at {local[:12]}")
            return
        if time.time() >= deadline:
            raise SystemExit(f"{repo.key}: origin/main stayed at {remote[:12]}, expected {local[:12]}")
        print(f"{repo.key}: waiting for origin/main {local[:12]} (currently {remote[:12]})")
        time.sleep(2)


def run_local_release_checks(system: Repo, corpus: Repo, docs: Repo, profile_site: Repo, owner_profile: Repo) -> None:
    with tempfile.TemporaryDirectory(prefix="enoch-release-") as tmp:
        generated = Path(tmp) / "ecosystem.generated.json"
        run([
            sys.executable,
            "scripts/generate_ecosystem_manifest.py",
            "--corpus",
            str(corpus.path),
            "--docs",
            str(docs.path),
            "--output",
            str(generated),
        ], cwd=system.path)
        run([
            sys.executable,
            "scripts/validate_public_release.py",
            "--system",
            str(system.path),
            "--corpus",
            str(corpus.path),
            "--docs",
            str(docs.path),
            "--profile",
            str(profile_site.path),
            "--owner-profile",
            str(owner_profile.path),
            "--generated-manifest",
            str(generated),
        ], cwd=system.path)
        manifest = json.loads(generated.read_text(encoding="utf-8"))
        print(
            "local public release accounting:",
            json.dumps(
                {
                    "artifact_count": manifest.get("artifact_count"),
                    "packaging_provenance_pass_count": manifest.get("packaging_provenance_pass_count"),
                    "strict_claim_evidence_pass_count": manifest.get("strict_claim_evidence_pass_count"),
                    "strict_claim_evidence_total_count": manifest.get("strict_claim_evidence_total_count"),
                },
                sort_keys=True,
            ),
        )


def watch_latest_workflow(repo: Repo, *, workflow: str, commit: str) -> None:
    # `gh run list --commit` is not universally available across older gh builds;
    # filter the JSON ourselves to keep this script portable.
    result = run(
        ["gh", "run", "list", "--branch", "main", "--limit", "20", "--json", "databaseId,headSha,workflowName,status,conclusion,url"],
        cwd=repo.path,
        capture=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"warning: gh run list failed for {repo.key}; skipping workflow watch\n{result.stdout}")
        return
    runs = json.loads(result.stdout or "[]")
    match = next((row for row in runs if row.get("headSha") == commit and row.get("workflowName") == workflow), None)
    if not match:
        print(f"warning: no {workflow!r} run found yet for {repo.key}@{commit[:12]}; skipping watch")
        return
    run_id = str(match["databaseId"])
    print(f"watching {repo.key} {workflow}: {match.get('url')}")
    run(["gh", "run", "watch", run_id, "--exit-status"], cwd=repo.path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Race-safe push for the public Enoch multi-repo release bundle.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2], help="Directory containing all public release repos")
    parser.add_argument("--push", action="store_true", help="Actually push repos. Without this, only preflight validation runs.")
    parser.add_argument("--watch", action="store_true", help="After pushing corpus, watch its Public release integrity workflow.")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow uncommitted changes for local preflight only; never use with --push.")
    parser.add_argument("--remote-timeout", type=int, default=120, help="Seconds to wait for origin/main to match each local HEAD")
    args = parser.parse_args()

    if args.push and args.allow_dirty:
        raise SystemExit("--allow-dirty is incompatible with --push")

    root = args.root.resolve()
    system = Repo("system", root / "enoch-agentic-research-system", workflow="Public release integrity")
    docs = Repo("docs", root / "enoch-docs")
    owner_profile = Repo("owner_profile", root / "alias8818")
    profile_site = Repo("profile_site", root / "alias8818.github.io")
    corpus = Repo("corpus", root / "enoch-ai-research-corpus", workflow="Public release integrity")
    ordered_dependencies = [system, docs, owner_profile, profile_site]
    all_repos = [*ordered_dependencies, corpus]

    for repo in all_repos:
        if not repo.path.exists():
            raise SystemExit(f"missing repo path for {repo.key}: {repo.path}")
        require_main(repo)
        if not args.allow_dirty:
            require_clean(repo)
        require_not_behind(repo)

    run_local_release_checks(system, corpus, docs, profile_site, owner_profile)

    print("release push order:", " -> ".join([repo.key for repo in [*ordered_dependencies, corpus]]))
    if not args.push:
        print("preflight complete; rerun with --push to publish in this order")
        return 0

    for repo in ordered_dependencies:
        push_and_verify(repo, push=True, timeout=args.remote_timeout)

    # The corpus public-release workflow reads the sibling repos from remote main;
    # only push corpus after every sibling remote has been verified above.
    push_and_verify(corpus, push=True, timeout=args.remote_timeout)

    if args.watch:
        watch_latest_workflow(corpus, workflow="Public release integrity", commit=head(corpus))

    print("public release bundle push complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
