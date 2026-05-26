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
import socket
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from enoch_control_plane.url_safety import secure_default_service_url

CONTROL_PLANE_PORT = 8787
# Documented on-prem control-plane host for the research-facility LAN.
# Override via ENOCH_WORKER_HOST (host only) or ENOCH_CONTROL_URL (full base URL).
LAB_CONTROL_PLANE_HOST = "192.168.1.166"  # NOSONAR python:S1313


def _default_control_plane_host() -> str:
    explicit = os.environ.get("ENOCH_WORKER_HOST", "").strip()
    if explicit:
        return explicit
    try:
        hostname = socket.gethostname().strip()
    except OSError:
        hostname = ""
    if hostname and hostname not in {"localhost", "localhost.localdomain"}:
        return hostname
    return LAB_CONTROL_PLANE_HOST


def default_control_url() -> str:
    for env_name in ("ENOCH_CONTROL_URL", "ENOCH_CONTROL_PLANE_URL"):
        explicit = os.environ.get(env_name, "").strip()
        if explicit:
            return explicit
    host = _default_control_plane_host()
    return secure_default_service_url(host, CONTROL_PLANE_PORT)


def default_generated_manifest_path() -> Path:
    override = os.environ.get("ENOCH_ECOSYSTEM_MANIFEST")
    if override:
        return Path(override)
    fd, path = tempfile.mkstemp(
        prefix="enoch-ecosystem.generated.",
        suffix=".json",
    )
    os.close(fd)
    return Path(path)


def _default_ledger_sql_output() -> str:
    fd, path = tempfile.mkstemp(
        prefix="enoch-sync-corpus-imports.",
        suffix=".sql",
    )
    os.close(fd)
    return path


@dataclass(frozen=True)
class Step:
    name: str
    cmd: list[str]
    cwd: Path
    env: dict[str, str] | None = None


@dataclass(frozen=True)
class ReleasePaths:
    system: Path
    corpus: Path
    docs: Path
    promising: Path
    profile_site: Path
    owner_profile: Path
    personal_site: Path
    hf_export: Path


def _release_paths(root: Path) -> ReleasePaths:
    root = root.resolve()
    return ReleasePaths(
        system=root / "enoch-agentic-research-system",
        corpus=root / "enoch-ai-research-corpus",
        docs=root / "enoch-docs",
        promising=root / "enoch-promising-signals",
        profile_site=root / "alias8818.github.io",
        owner_profile=root / "alias8818",
        personal_site=root / "jeremyblankenship.dev",
        hf_export=root / "hf-enoch-ai-research-corpus",
    )


def _control_token(args: argparse.Namespace) -> str:
    return (
        args.token
        or os.environ.get("ENOCH_CONTROL_TOKEN")
        or os.environ.get("ENOCH_CONTROL_PLANE_TOKEN")
        or ""
    )


def _require_control_token(token: str, flag: str) -> None:
    if not token:
        raise SystemExit(
            f"{flag} requires --token or ENOCH_CONTROL_TOKEN/ENOCH_CONTROL_PLANE_TOKEN"
        )


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


def _import_steps(
    args: argparse.Namespace, paths: ReleasePaths, token: str
) -> list[Step]:
    if not args.import_from_control_plane:
        return []
    _require_control_token(token, "--import-from-control-plane")
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
    return [
        Step(
            "import finalized papers",
            import_cmd,
            paths.corpus,
            env={"ENOCH_CONTROL_TOKEN": token},
        )
    ]


def _baseline_release_steps(
    paths: ReleasePaths, generated_manifest: Path
) -> list[Step]:
    return [
        Step(
            "audit strict claim evidence",
            [sys.executable, "scripts/audit_claim_evidence_contract.py"],
            paths.corpus,
        ),
        Step(
            "scan corpus quality",
            [sys.executable, "scripts/quality_scan.py"],
            paths.corpus,
        ),
        Step(
            "build corpus index",
            [sys.executable, "scripts/build_index.py"],
            paths.corpus,
        ),
        Step(
            "validate corpus trust surfaces",
            [sys.executable, "scripts/validate_public_trust_surfaces.py"],
            paths.corpus,
        ),
        Step(
            "generate ecosystem manifest",
            [
                sys.executable,
                "scripts/generate_ecosystem_manifest.py",
                "--corpus",
                str(paths.corpus),
                "--docs",
                str(paths.docs),
                "--promising",
                str(paths.promising),
                "--output",
                str(generated_manifest),
            ],
            paths.system,
        ),
        Step(
            "validate public release",
            [
                sys.executable,
                "scripts/validate_public_release.py",
                "--system",
                str(paths.system),
                "--corpus",
                str(paths.corpus),
                "--docs",
                str(paths.docs),
                "--promising",
                str(paths.promising),
                "--profile",
                str(paths.profile_site),
                "--owner-profile",
                str(paths.owner_profile),
                "--personal-site",
                str(paths.personal_site),
                "--generated-manifest",
                str(generated_manifest),
            ],
            paths.system,
        ),
    ]


def _hf_steps(args: argparse.Namespace, paths: ReleasePaths) -> list[Step]:
    steps: list[Step] = []
    if args.build_hf:
        steps.append(
            Step(
                "build Hugging Face export",
                [sys.executable, "build_from_corpus.py", "--corpus", str(paths.corpus)],
                paths.hf_export,
            )
        )
    if args.publish_hf:
        steps.append(
            Step(
                "publish Hugging Face export",
                [sys.executable, "publish_to_huggingface.py"],
                paths.hf_export,
            )
        )
    return steps


def _reconcile_steps(
    args: argparse.Namespace, paths: ReleasePaths, token: str
) -> list[Step]:
    if not args.reconcile_control_plane:
        return []
    _require_control_token(token, "--reconcile-control-plane")
    reconcile_cmd = [
        sys.executable,
        "scripts/reconcile_paper_ledgers.py",
        "--control-url",
        args.control_url,
        "--corpus",
        str(paths.corpus),
        "--require-synced",
        "--include-draft-candidate",
        "--verbose",
    ]
    return [
        Step(
            "reconcile control-plane papers",
            reconcile_cmd,
            paths.system,
            env={"ENOCH_CONTROL_TOKEN": token},
        )
    ]


def _ledger_sync_with_database(
    sync_cmd: list[str], args: argparse.Namespace, paths: ReleasePaths
) -> list[Step]:
    sync_cmd = [*sync_cmd, "--apply"]
    db_env = {"ENOCH_SUPABASE_DATABASE_URL": args.ledger_database_url}
    return [
        Step("sync Supabase corpus_imports", sync_cmd, paths.system, env=db_env),
        Step(
            "validate Supabase corpus_imports",
            [
                sys.executable,
                "scripts/validate_corpus_import_ledger.py",
                "--corpus",
                str(paths.corpus),
            ],
            paths.system,
            env=db_env,
        ),
    ]


def _ledger_sync_with_sql_file(
    sync_cmd: list[str], args: argparse.Namespace, paths: ReleasePaths
) -> list[Step]:
    sql_path = Path(args.ledger_sql_output)
    sync_cmd = [*sync_cmd, "--sql-output", str(sql_path)]
    steps = [Step("render Supabase corpus_imports sync SQL", sync_cmd, paths.system)]
    if args.ledger_use_linked:
        steps.extend(
            [
                Step(
                    "apply Supabase corpus_imports sync SQL",
                    ["supabase", "db", "query", "--linked", "-f", str(sql_path)],
                    paths.system,
                ),
                Step(
                    "validate Supabase corpus_imports",
                    [
                        sys.executable,
                        "scripts/validate_corpus_import_ledger.py",
                        "--corpus",
                        str(paths.corpus),
                        "--linked",
                    ],
                    paths.system,
                ),
            ]
        )
        return steps
    steps.append(
        Step(
            "manual Supabase corpus_imports sync required",
            ["echo", f"Run: supabase db query --linked -f {sql_path}"],
            paths.system,
        )
    )
    return steps


def _ledger_sync_steps(args: argparse.Namespace, paths: ReleasePaths) -> list[Step]:
    if not args.sync_corpus_ledger:
        return []
    sync_cmd = [
        sys.executable,
        "scripts/sync_corpus_import_ledger.py",
        "--corpus",
        str(paths.corpus),
        "--prune-stale",
    ]
    if args.ledger_database_url:
        return _ledger_sync_with_database(sync_cmd, args, paths)
    return _ledger_sync_with_sql_file(sync_cmd, args, paths)


def build_steps(args: argparse.Namespace) -> list[Step]:
    paths = _release_paths(args.root)
    generated_manifest = Path(args.generated_manifest)
    token = _control_token(args)
    steps: list[Step] = []
    steps.extend(_import_steps(args, paths, token))
    steps.extend(_baseline_release_steps(paths, generated_manifest))
    steps.extend(_hf_steps(args, paths))
    steps.extend(_reconcile_steps(args, paths, token))
    steps.extend(_ledger_sync_steps(args, paths))
    return steps


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument(
        "--control-url",
        default=default_control_url(),
    )
    parser.add_argument("--token", default="")
    parser.add_argument(
        "--generated-manifest",
        default=None,
        help="Path for ecosystem manifest output (default: private temp file).",
    )
    parser.add_argument(
        "--import-from-control-plane",
        action="store_true",
        help="Import finalized publication_draft rows into the public corpus before rebuilding indexes.",
    )
    parser.add_argument("--paper-status", default="publication_draft")
    parser.add_argument("--review-status", default="finalized")
    parser.add_argument("--import-limit", type=int, default=0)
    parser.add_argument("--import-force", action="store_true")
    parser.add_argument("--allow-title-duplicates", action="store_true")
    parser.add_argument(
        "--build-hf",
        action="store_true",
        help="Rebuild hf-enoch-ai-research-corpus from the corpus repo.",
    )
    parser.add_argument(
        "--publish-hf",
        action="store_true",
        help="Publish the HF dataset export. Implies --build-hf.",
    )
    parser.add_argument(
        "--reconcile-control-plane",
        action="store_true",
        help="Run reconcile_paper_ledgers.py --require-synced.",
    )
    parser.add_argument(
        "--sync-corpus-ledger",
        action="store_true",
        help="Sync Supabase corpus_imports from the public index.",
    )
    parser.add_argument(
        "--ledger-database-url",
        default=os.environ.get("ENOCH_SUPABASE_DATABASE_URL", ""),
    )
    parser.add_argument(
        "--ledger-use-linked",
        action="store_true",
        help="Apply ledger sync through Supabase linked CLI when no DB URL is available.",
    )
    parser.add_argument(
        "--ledger-sql-output",
        default="",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned commands without running them.",
    )
    args = parser.parse_args(argv)
    if args.generated_manifest is None:
        args.generated_manifest = str(default_generated_manifest_path())
    if not args.ledger_sql_output:
        args.ledger_sql_output = _default_ledger_sql_output()
    if args.publish_hf:
        args.build_hf = True
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    steps = build_steps(args)
    print(
        "public corpus release steps:",
        " -> ".join(step.name for step in steps),
        flush=True,
    )
    for step in steps:
        run(step, dry_run=bool(args.dry_run))
    print(
        "public corpus release workflow complete"
        if not args.dry_run
        else "public corpus release dry-run complete"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
