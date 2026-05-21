#!/usr/bin/env python3
"""Run the end-to-end public corpus release workflow.

This script is the agent-facing checklist for moving finalized control-plane
papers into the public corpus/HF/release surfaces without mixing ledgers:
optional control-plane import, corpus quality/index rebuild, public release
validation, optional Hugging Face export/publish, reconciliation, and optional
Supabase corpus_imports sync.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Step:
    name: str
    cmd: list[str]
    cwd: Path
    env: dict[str, str] | None = None


SECRET_ARG_NAMES = {"--token", "--database-url", "--db-url", "--ledger-database-url"}


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


def run(step: Step, *, dry_run: bool = False) -> None:
    printable = printable_cmd(step.cmd)
    print(f"[{step.name}] $ {printable} ({step.cwd})", flush=True)
    if dry_run:
        return
    env = os.environ.copy()
    if step.env:
        env.update(step.env)
    subprocess.run(step.cmd, cwd=str(step.cwd), env=env, check=True)


def build_steps(args: argparse.Namespace) -> list[Step]:
    root = args.root.resolve()
    system = root / "enoch-agentic-research-system"
    corpus = root / "enoch-ai-research-corpus"
    docs = root / "enoch-docs"
    promising = root / "enoch-promising-signals"
    profile_site = root / "alias8818.github.io"
    owner_profile = root / "alias8818"
    personal_site = root / "jeremyblankenship.dev"
    hf_export = root / "hf-enoch-ai-research-corpus"
    generated_manifest = Path(args.generated_manifest)
    token = args.token or os.environ.get("ENOCH_CONTROL_TOKEN") or os.environ.get("ENOCH_CONTROL_PLANE_TOKEN") or ""
    steps: list[Step] = []

    if args.import_from_control_plane:
        if not token:
            raise SystemExit("--import-from-control-plane requires --token or ENOCH_CONTROL_TOKEN/ENOCH_CONTROL_PLANE_TOKEN")
        import_cmd = [
            sys.executable,
            "scripts/import_from_control_plane.py",
            "--control-url",
            args.control_url,
            "--paper-status",
            args.paper_status,
            "--review-status",
            args.review_status,
        ]
        if args.import_limit:
            import_cmd.extend(["--limit", str(args.import_limit)])
        if args.import_force:
            import_cmd.append("--force")
        if args.allow_title_duplicates:
            import_cmd.append("--allow-title-duplicates")
        steps.append(Step("import finalized papers", import_cmd, corpus, env={"ENOCH_CONTROL_TOKEN": token}))

    steps.extend(
        [
            Step("audit strict claim evidence", [sys.executable, "scripts/audit_claim_evidence_contract.py"], corpus),
            Step("scan corpus quality", [sys.executable, "scripts/quality_scan.py"], corpus),
            Step("build corpus index", [sys.executable, "scripts/build_index.py"], corpus),
            Step("validate corpus trust surfaces", [sys.executable, "scripts/validate_public_trust_surfaces.py"], corpus),
            Step(
                "generate ecosystem manifest",
                [
                    sys.executable,
                    "scripts/generate_ecosystem_manifest.py",
                    "--corpus",
                    str(corpus),
                    "--docs",
                    str(docs),
                    "--promising",
                    str(promising),
                    "--output",
                    str(generated_manifest),
                ],
                system,
            ),
            Step(
                "validate public release",
                [
                    sys.executable,
                    "scripts/validate_public_release.py",
                    "--system",
                    str(system),
                    "--corpus",
                    str(corpus),
                    "--docs",
                    str(docs),
                    "--promising",
                    str(promising),
                    "--profile",
                    str(profile_site),
                    "--owner-profile",
                    str(owner_profile),
                    "--personal-site",
                    str(personal_site),
                    "--generated-manifest",
                    str(generated_manifest),
                ],
                system,
            ),
        ]
    )

    if args.build_hf:
        steps.append(Step("build Hugging Face export", [sys.executable, "build_from_corpus.py", "--corpus", str(corpus)], hf_export))
    if args.publish_hf:
        steps.append(Step("publish Hugging Face export", [sys.executable, "publish_to_huggingface.py"], hf_export))

    if args.reconcile_control_plane:
        if not token:
            raise SystemExit("--reconcile-control-plane requires --token or ENOCH_CONTROL_TOKEN/ENOCH_CONTROL_PLANE_TOKEN")
        reconcile_cmd = [
            sys.executable,
            "scripts/reconcile_paper_ledgers.py",
            "--control-url",
            args.control_url,
            "--corpus",
            str(corpus),
            "--require-synced",
            "--include-draft-candidate",
            "--verbose",
        ]
        steps.append(Step("reconcile control-plane papers", reconcile_cmd, system, env={"ENOCH_CONTROL_TOKEN": token}))

    if args.sync_corpus_ledger:
        sync_cmd = [sys.executable, "scripts/sync_corpus_import_ledger.py", "--corpus", str(corpus), "--prune-stale"]
        if args.ledger_database_url:
            sync_cmd.append("--apply")
            steps.append(Step("sync Supabase corpus_imports", sync_cmd, system, env={"ENOCH_SUPABASE_DATABASE_URL": args.ledger_database_url}))
            steps.append(
                Step(
                    "validate Supabase corpus_imports",
                    [
                        sys.executable,
                        "scripts/validate_corpus_import_ledger.py",
                        "--corpus",
                        str(corpus),
                    ],
                    system,
                    env={"ENOCH_SUPABASE_DATABASE_URL": args.ledger_database_url},
                )
            )
        else:
            sql_path = Path(args.ledger_sql_output)
            sync_cmd.extend(["--sql-output", str(sql_path)])
            steps.append(Step("render Supabase corpus_imports sync SQL", sync_cmd, system))
            if args.ledger_use_linked:
                steps.append(Step("apply Supabase corpus_imports sync SQL", ["supabase", "db", "query", "--linked", "-f", str(sql_path)], system))
                steps.append(
                    Step(
                        "validate Supabase corpus_imports",
                        [
                            sys.executable,
                            "scripts/validate_corpus_import_ledger.py",
                            "--corpus",
                            str(corpus),
                            "--linked",
                        ],
                        system,
                    )
                )
            else:
                steps.append(Step("manual Supabase corpus_imports sync required", ["echo", f"Run: supabase db query --linked -f {sql_path}"], system))

    return steps


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--control-url", default=os.environ.get("ENOCH_CONTROL_URL", "http://192.168.1.166:8787"))
    parser.add_argument("--token", default="")
    parser.add_argument("--generated-manifest", default="/tmp/enoch-ecosystem.generated.json")
    parser.add_argument("--import-from-control-plane", action="store_true", help="Import finalized publication_draft rows into the public corpus before rebuilding indexes.")
    parser.add_argument("--paper-status", default="publication_draft")
    parser.add_argument("--review-status", default="finalized")
    parser.add_argument("--import-limit", type=int, default=0)
    parser.add_argument("--import-force", action="store_true")
    parser.add_argument("--allow-title-duplicates", action="store_true")
    parser.add_argument("--build-hf", action="store_true", help="Rebuild hf-enoch-ai-research-corpus from the corpus repo.")
    parser.add_argument("--publish-hf", action="store_true", help="Publish the HF dataset export. Implies --build-hf.")
    parser.add_argument("--reconcile-control-plane", action="store_true", help="Run reconcile_paper_ledgers.py --require-synced.")
    parser.add_argument("--sync-corpus-ledger", action="store_true", help="Sync Supabase corpus_imports from the public index.")
    parser.add_argument("--ledger-database-url", default=os.environ.get("ENOCH_SUPABASE_DATABASE_URL", ""))
    parser.add_argument("--ledger-use-linked", action="store_true", help="Apply ledger sync through Supabase linked CLI when no DB URL is available.")
    parser.add_argument("--ledger-sql-output", default="/tmp/enoch-sync-corpus-imports.sql")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned commands without running them.")
    args = parser.parse_args(argv)
    if args.publish_hf:
        args.build_hf = True
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    steps = build_steps(args)
    print("public corpus release steps:", " -> ".join(step.name for step in steps), flush=True)
    for step in steps:
        run(step, dry_run=bool(args.dry_run))
    print("public corpus release workflow complete" if not args.dry_run else "public corpus release dry-run complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
