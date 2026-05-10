#!/usr/bin/env python3
"""Run one capped public corpus-import automation tick.

The service is inert unless ENOCH_ENABLE_CORPUS_IMPORT_AUTOPILOT=1 is set.
A tick is intentionally conservative: it first performs a real import into a
throwaway corpus copy, rebuilds indexes/reports, regenerates the ecosystem
manifest, and runs the public-release validator. It writes to the canonical
repos only after that preflight passes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any


REPO_NAMES = [
    "enoch-agentic-research-system",
    "enoch-ai-research-corpus",
    "enoch-docs",
    "alias8818.github.io",
    "alias8818",
    "jeremyblankenship.dev",
]


def _truthy(name: str, default: str = "0") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(name: str, default: int, lower: int, upper: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(lower, min(value, upper))


def _load_config() -> dict[str, Any]:
    path = Path(os.environ.get("ENOCH_CONFIG") or os.environ.get("ENOCH_CONTROL_PLANE_CONFIG", "/etc/enoch-control-plane/config.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def _base_url(config: dict[str, Any]) -> str:
    host = str(config.get("listen_host") or "127.0.0.1")
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return os.environ.get("ENOCH_CONTROL_URL") or f"http://{host}:{int(config.get('listen_port') or 8787)}"


def _release_root() -> Path:
    return Path(os.environ.get("ENOCH_RELEASE_ROOT", "/home/jeremy/Desktop/projects/enoch-release")).expanduser().resolve()


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(cmd, cwd=str(cwd), env=merged, text=True, capture_output=True, check=True)


def _git_clean(repo: Path) -> bool:
    result = _run(["git", "status", "--porcelain"], cwd=repo)
    return not result.stdout.strip()


def _copy_repo_tree(src: Path, dst: Path) -> None:
    def ignore(_dir: str, names: list[str]) -> set[str]:
        return {name for name in names if name in {".git", ".venv", "node_modules", ".pytest_cache", "__pycache__"}}

    shutil.copytree(src, dst, ignore=ignore)


def _import_cmd(*, base_url: str, token: str, limit: int, dry_run: bool) -> list[str]:
    cmd = [
        sys.executable,
        "scripts/import_from_control_plane.py",
        "--control-url",
        base_url,
        "--token",
        token,
        "--paper-status",
        "publication_draft",
        "--review-status",
        "finalized",
        "--limit",
        str(limit),
    ]
    if dry_run:
        cmd.append("--dry-run")
    return cmd


def _corpus_checks(corpus: Path) -> list[dict[str, Any]]:
    steps = [
        ("audit_claim_evidence", [sys.executable, "scripts/audit_claim_evidence_contract.py"]),
        ("quality_scan", [sys.executable, "scripts/quality_scan.py"]),
        ("build_index", [sys.executable, "scripts/build_index.py"]),
        ("validate_public_trust_surfaces", [sys.executable, "scripts/validate_public_trust_surfaces.py"]),
    ]
    out = []
    for name, cmd in steps:
        result = _run(cmd, cwd=corpus)
        out.append({"name": name, "stdout_tail": result.stdout[-1200:], "stderr_tail": result.stderr[-1200:]})
    return out


def _validate_release(system: Path, root: Path, corpus: Path, manifest: Path, *, skip_github_metadata: bool) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/generate_ecosystem_manifest.py",
        "--corpus",
        str(corpus),
        "--docs",
        str(root / "enoch-docs"),
        "--output",
        str(manifest),
    ]
    gen = _run(cmd, cwd=system)
    validate_cmd = [
        sys.executable,
        "scripts/validate_public_release.py",
        "--system",
        str(system),
        "--corpus",
        str(corpus),
        "--docs",
        str(root / "enoch-docs"),
        "--profile",
        str(root / "alias8818.github.io"),
        "--owner-profile",
        str(root / "alias8818"),
        "--personal-site",
        str(root / "jeremyblankenship.dev"),
        "--generated-manifest",
        str(manifest),
    ]
    if skip_github_metadata:
        validate_cmd.append("--skip-github-metadata")
    val = _run(validate_cmd, cwd=system)
    return {"generate_stdout": gen.stdout[-1200:], "validate_stdout": val.stdout[-1200:]}


def main() -> int:
    if not _truthy("ENOCH_ENABLE_CORPUS_IMPORT_AUTOPILOT"):
        print(json.dumps({"ok": True, "action": "skipped", "reason": "corpus import autopilot disabled; set ENOCH_ENABLE_CORPUS_IMPORT_AUTOPILOT=1"}, sort_keys=True))
        return 0

    limit = _bounded_int("ENOCH_CORPUS_IMPORT_LIMIT", 1, 1, 2)
    root = _release_root()
    missing = [name for name in REPO_NAMES if not (root / name).is_dir()]
    if missing:
        print(json.dumps({"ok": False, "action": "blocked", "reason": "release repos missing", "missing": missing, "release_root": str(root)}, sort_keys=True), file=sys.stderr)
        return 2

    dirty = [name for name in REPO_NAMES if not _git_clean(root / name)]
    if dirty:
        print(json.dumps({"ok": False, "action": "blocked", "reason": "release repos are dirty before import", "dirty_repos": dirty}, sort_keys=True), file=sys.stderr)
        return 2

    config = _load_config()
    token = os.environ.get("ENOCH_CONTROL_TOKEN") or str(config.get("control_api_bearer_token") or "")
    if not token:
        print(json.dumps({"ok": False, "action": "blocked", "reason": "missing control-plane token"}, sort_keys=True), file=sys.stderr)
        return 2
    base_url = _base_url(config)
    system = root / "enoch-agentic-research-system"
    corpus = root / "enoch-ai-research-corpus"
    skip_github = _truthy("ENOCH_CORPUS_IMPORT_SKIP_GITHUB_METADATA", "1")

    try:
        dry = _run(_import_cmd(base_url=base_url, token=token, limit=limit, dry_run=True), cwd=corpus)
        dry_payload = json.loads(dry.stdout)
    except Exception as exc:  # noqa: BLE001 - fail closed without writes
        print(json.dumps({"ok": False, "action": "dry_run_failed", "reason": f"{type(exc).__name__}: {exc}"}, sort_keys=True), file=sys.stderr)
        return 1
    if dry_payload.get("failed") or not dry_payload.get("imported"):
        print(json.dumps({"ok": False, "action": "blocked", "reason": "bounded import dry-run found no clean importable papers", "dry_run": dry_payload}, sort_keys=True), file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="enoch-corpus-import-preflight-") as tmp:
        tmp_root = Path(tmp)
        tmp_corpus = tmp_root / "enoch-ai-research-corpus"
        _copy_repo_tree(corpus, tmp_corpus)
        live_preflight = _run(_import_cmd(base_url=base_url, token=token, limit=limit, dry_run=False), cwd=tmp_corpus)
        live_payload = json.loads(live_preflight.stdout)
        if live_payload.get("failed"):
            print(json.dumps({"ok": False, "action": "preflight_import_failed", "preflight": live_payload}, sort_keys=True), file=sys.stderr)
            return 1
        checks = _corpus_checks(tmp_corpus)
        release_validation = _validate_release(system, root, tmp_corpus, tmp_root / "enoch-ecosystem.generated.json", skip_github_metadata=skip_github)

    if _truthy("ENOCH_CORPUS_IMPORT_PREFLIGHT_ONLY", "0"):
        print(json.dumps({"ok": True, "action": "preflight_only", "limit": limit, "dry_run": dry_payload, "corpus_checks": checks, "release_validation": release_validation}, sort_keys=True))
        return 0

    live = _run(_import_cmd(base_url=base_url, token=token, limit=limit, dry_run=False), cwd=corpus)
    live_payload = json.loads(live.stdout)
    checks = _corpus_checks(corpus)
    release_validation = _validate_release(system, root, corpus, Path(os.environ.get("ENOCH_ECOSYSTEM_MANIFEST", "/tmp/enoch-ecosystem.generated.json")), skip_github_metadata=skip_github)
    print(json.dumps({"ok": True, "action": "corpus_imported", "limit": limit, "dry_run": dry_payload, "import_result": live_payload, "corpus_checks": checks, "release_validation": release_validation}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
