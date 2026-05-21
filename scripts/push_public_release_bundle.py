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
import os
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


SECRET_ARG_NAMES = {"--token", "--database-url", "--db-url", "--ledger-database-url"}
PROJECT_PYTHON = ["uv", "run", "python"]
DEFAULT_SOURCE_LINEAGE_CREATED_AFTER = "2026-05-19T17:51:00Z"
DEFAULT_PROMISING_SIGNALS_SOURCE_CUTOFF = "2026-05-19T17:51:00Z"


def printable_cmd(cmd: list[str]) -> str:
    redacted: list[str] = []
    skip_next = False
    for part in cmd:
        if skip_next:
            redacted.append("<redacted>")
            skip_next = False
            continue
        redacted.append(part)
        if part in SECRET_ARG_NAMES:
            skip_next = True
    return " ".join(redacted)


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    printable = printable_cmd(cmd)
    where = f" ({cwd})" if cwd else ""
    print(f"$ {printable}{where}", flush=True)
    child_env = None
    if env is not None:
        child_env = os.environ.copy()
        child_env.update(env)
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=child_env,
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



def sync_corpus_import_ledger(system: Repo, corpus: Repo, *, database_url: str, use_linked: bool) -> None:
    """Sync the Supabase corpus_imports ledger from the public corpus index."""

    if database_url.strip():
        run(
            [
                sys.executable,
                "scripts/sync_corpus_import_ledger.py",
                "--corpus",
                str(corpus.path),
                "--prune-stale",
                "--apply",
            ],
            cwd=system.path,
            env={
            "ENOCH_SUPABASE_DATABASE_URL": database_url,
            "ENOCH_PROMISING_SIGNALS_SOURCE_CUTOFF": os.environ.get(
                "ENOCH_PROMISING_SIGNALS_SOURCE_CUTOFF", DEFAULT_PROMISING_SIGNALS_SOURCE_CUTOFF
            ),
        },
        )
        run(
            [
                sys.executable,
                "scripts/validate_corpus_import_ledger.py",
                "--corpus",
                str(corpus.path),
            ],
            cwd=system.path,
            env={
            "ENOCH_SUPABASE_DATABASE_URL": database_url,
            "ENOCH_PROMISING_SIGNALS_SOURCE_CUTOFF": os.environ.get(
                "ENOCH_PROMISING_SIGNALS_SOURCE_CUTOFF", DEFAULT_PROMISING_SIGNALS_SOURCE_CUTOFF
            ),
        },
        )
        return
    if not use_linked:
        raise SystemExit("--sync-corpus-ledger requires --ledger-database-url/ENOCH_SUPABASE_DATABASE_URL or --ledger-use-linked")
    with tempfile.TemporaryDirectory(prefix="enoch-ledger-sync-") as tmp:
        sql_path = Path(tmp) / "sync-corpus-import-ledger.sql"
        run(
            [
                sys.executable,
                "scripts/sync_corpus_import_ledger.py",
                "--corpus",
                str(corpus.path),
                "--prune-stale",
                "--sql-output",
                str(sql_path),
            ],
            cwd=system.path,
        )
        run(["supabase", "db", "query", "--linked", "-f", str(sql_path)], cwd=system.path)
        run(
            [
                sys.executable,
                "scripts/validate_corpus_import_ledger.py",
                "--corpus",
                str(corpus.path),
                "--linked",
            ],
            cwd=system.path,
        )


def run_source_lineage_check(system: Repo) -> None:
    database_url = (
        os.environ.get("ENOCH_SOURCE_LINEAGE_DATABASE_URL")
        or os.environ.get("ENOCH_CONTROL_DATABASE_URL")
        or os.environ.get("ENOCH_SUPABASE_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or ""
    )
    if not database_url:
        print("source lineage validator: skipped; no Postgres URL configured")
        return
    cmd = [*PROJECT_PYTHON, "scripts/validate_source_lineage.py"]
    created_after = os.environ.get("ENOCH_SOURCE_LINEAGE_CREATED_AFTER", DEFAULT_SOURCE_LINEAGE_CREATED_AFTER)
    cmd.extend(["--created-after", created_after])
    run(cmd, cwd=system.path, env={"ENOCH_SOURCE_LINEAGE_DATABASE_URL": database_url})


def run_promising_signals_check(system: Repo, promising: Repo) -> None:
    database_url = (
        os.environ.get("ENOCH_PROMISING_SIGNALS_DATABASE_URL")
        or os.environ.get("ENOCH_CONTROL_DATABASE_URL")
        or os.environ.get("ENOCH_SUPABASE_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or ""
    )
    if not database_url:
        print("promising signals live export validation: skipped; no Postgres URL configured")
        return
    run(
        [
            *PROJECT_PYTHON,
            "scripts/export_promising_signals.py",
            "--output-repo",
            str(promising.path),
            "--validate-output-repo",
        ],
        cwd=system.path,
        env={
            "ENOCH_SUPABASE_DATABASE_URL": database_url,
            "ENOCH_PROMISING_SIGNALS_SOURCE_CUTOFF": os.environ.get(
                "ENOCH_PROMISING_SIGNALS_SOURCE_CUTOFF", DEFAULT_PROMISING_SIGNALS_SOURCE_CUTOFF
            ),
        },
    )


def run_local_release_checks(
    system: Repo,
    corpus: Repo,
    docs: Repo,
    profile_site: Repo,
    owner_profile: Repo,
    personal_site: Repo,
    promising: Repo,
) -> None:
    hf_export = system.path.parent / "hf-enoch-ai-research-corpus"
    with tempfile.TemporaryDirectory(prefix="enoch-release-") as tmp:
        generated = Path(tmp) / "ecosystem.generated.json"
        run([sys.executable, "scripts/validate_runtime_snapshot_links.py"], cwd=system.path)
        run_source_lineage_check(system)
        run_promising_signals_check(system, promising)
        run(["node", "scripts/validate-docs.mjs"], cwd=docs.path)
        run([
            sys.executable,
            "scripts/generate_ecosystem_manifest.py",
            "--corpus",
            str(corpus.path),
            "--docs",
            str(docs.path),
            "--promising",
            str(promising.path),
            "--output",
            str(generated),
        ], cwd=system.path)
        validate_cmd = [
            sys.executable,
            "scripts/validate_public_release.py",
            "--system",
            str(system.path),
            "--corpus",
            str(corpus.path),
            "--docs",
            str(docs.path),
            "--promising",
            str(promising.path),
            "--profile",
            str(profile_site.path),
            "--owner-profile",
            str(owner_profile.path),
            "--personal-site",
            str(personal_site.path),
            "--generated-manifest",
            str(generated),
        ]
        if hf_export.exists():
            validate_cmd.extend(["--hf-export", str(hf_export)])
        run(validate_cmd, cwd=system.path)
        manifest = json.loads(generated.read_text(encoding="utf-8"))
        print(
            "local public release accounting:",
            json.dumps(
                {
                    "artifact_count": manifest.get("artifact_count"),
                    "promising_signal_count": manifest.get("promising_signal_count"),
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
    parser.add_argument("--sync-corpus-ledger", action="store_true", help="After local release checks, sync Supabase corpus_imports from the public corpus index.")
    parser.add_argument("--ledger-database-url", default=os.environ.get("ENOCH_SUPABASE_DATABASE_URL", ""), help="Postgres/Supabase URL for --sync-corpus-ledger; defaults to ENOCH_SUPABASE_DATABASE_URL.")
    parser.add_argument("--ledger-use-linked", action="store_true", help="Use `supabase db query --linked` for --sync-corpus-ledger when no database URL is available.")
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
    personal_site = Repo("personal_site", root / "jeremyblankenship.dev")
    corpus = Repo("corpus", root / "enoch-ai-research-corpus", workflow="Public release integrity")
    promising = Repo("promising", root / "enoch-promising-signals", workflow="Public release integrity")
    ordered_dependencies = [system, docs, owner_profile, profile_site, personal_site, promising]
    all_repos = [*ordered_dependencies, corpus]

    for repo in all_repos:
        if not repo.path.exists():
            raise SystemExit(f"missing repo path for {repo.key}: {repo.path}")
        require_main(repo)
        if not args.allow_dirty:
            require_clean(repo)
        require_not_behind(repo)

    run_local_release_checks(system, corpus, docs, profile_site, owner_profile, personal_site, promising)
    if args.sync_corpus_ledger:
        sync_corpus_import_ledger(
            system,
            corpus,
            database_url=args.ledger_database_url,
            use_linked=bool(args.ledger_use_linked),
        )

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
