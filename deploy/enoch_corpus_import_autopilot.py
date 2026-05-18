#!/usr/bin/env python3
"""Run one capped public corpus-import automation tick.

The service is inert unless ENOCH_ENABLE_CORPUS_IMPORT_AUTOPILOT=1 is set.
A tick is intentionally conservative: it first performs a real import into a
throwaway corpus copy, rebuilds indexes/reports, regenerates the ecosystem
manifest, and runs the public-release validator. It writes to the canonical
repos only after that preflight passes. Live writes still stop before Git
commits unless ENOCH_CORPUS_IMPORT_AUTOCOMMIT=1 is set, and pushes require
ENOCH_CORPUS_IMPORT_PUSH=1.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any
from urllib.request import Request, urlopen


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


def _bounded_float(name: str, default: float, lower: float, upper: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
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


def _ff_only_repos(root: Path) -> list[str]:
    """Fast-forward clean release repos before an automated import tick.

    The corpus autopilot spans several public repos. If another docs/release
    task has pushed to one of them, a later count-refresh push can fail after
    only some repos were pushed. Pulling with --ff-only before writes keeps the
    local release bundle current without hiding merge conflicts.
    """

    updated: list[str] = []
    for name in REPO_NAMES:
        repo = root / name
        before = _run(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()
        _run(["git", "pull", "--ff-only"], cwd=repo)
        after = _run(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()
        if after != before:
            updated.append(name)
    return updated


def _git_changed_repos(root: Path) -> list[str]:
    changed: list[str] = []
    for name in REPO_NAMES:
        result = _run(["git", "status", "--porcelain"], cwd=root / name)
        if result.stdout.strip():
            changed.append(name)
    return changed


def _commit_message(repo_name: str, import_result: dict[str, Any], count_update: dict[str, Any]) -> str:
    imported = int(import_result.get("imported") or 0)
    stats = count_update.get("stats") if isinstance(count_update.get("stats"), dict) else {}
    total = count_update.get("artifact_count") or count_update.get("total_artifacts") or stats.get("artifact_count") or "current"
    if repo_name == "enoch-ai-research-corpus":
        subject = f"Import {imported} Enoch corpus artifact" if imported == 1 else f"Import {imported} Enoch corpus artifacts"
        body = f"Import {imported} finalized publication draft(s) from the control plane.\n\nCorpus artifact count after validation: {total}.\n"
    else:
        subject = "Refresh Enoch corpus release counts"
        body = f"Refresh public release surfaces after importing {imported} finalized publication draft(s).\n\nCorpus artifact count after validation: {total}.\n"
    return f"{subject}\n\n{body}"


def _commit_changed_repos(root: Path, import_result: dict[str, Any], count_update: dict[str, Any]) -> list[dict[str, str]]:
    commits: list[dict[str, str]] = []
    for name in _git_changed_repos(root):
        repo = root / name
        _run(["git", "add", "-A"], cwd=repo)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(_commit_message(name, import_result, count_update))
            msg_path = Path(handle.name)
        try:
            _run(["git", "commit", "-F", str(msg_path)], cwd=repo)
        finally:
            msg_path.unlink(missing_ok=True)
        sha = _run(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()
        commits.append({"repo": name, "sha": sha})
    return commits


def _push_commits(root: Path, commits: list[dict[str, str]]) -> list[dict[str, str]]:
    pushed: list[dict[str, str]] = []
    for item in commits:
        _run(["git", "push"], cwd=root / item["repo"])
        pushed.append(item)
    return pushed


def _sync_corpus_ledger(system: Path, corpus: Path) -> dict[str, Any]:
    result = _run(
        [
            sys.executable,
            "scripts/sync_corpus_import_ledger.py",
            "--corpus",
            str(corpus),
            "--apply",
            "--prune-stale",
        ],
        cwd=system,
    )
    return json.loads(result.stdout)


def _github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if token:
        return token.strip()
    token_file = os.environ.get("ENOCH_GITHUB_TOKEN_FILE")
    if token_file:
        return Path(token_file).expanduser().read_text(encoding="utf-8").strip()
    return ""


def _update_github_metadata(artifact_count: int) -> dict[str, Any]:
    token = _github_token()
    if not token:
        raise RuntimeError("missing GitHub token for metadata update")
    payload = json.dumps(
        {
            "description": f"{artifact_count} AI-generated research artifacts produced by Enoch with provenance metadata, evidence bundles, claim-ledger files, and public audit reports.",
            "homepage": "https://alias8818.github.io/enoch-agentic-research-system/",
        }
    ).encode("utf-8")
    request = Request(
        "https://api.github.com/repos/alias8818/enoch-ai-research-corpus",
        data=payload,
        method="PATCH",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "enoch-corpus-import-autopilot/1.0",
        },
    )
    with urlopen(request, timeout=30) as response:
        metadata = json.loads(response.read().decode("utf-8"))
    return {"repo": "alias8818/enoch-ai-research-corpus", "description": metadata.get("description"), "homepage": metadata.get("homepage")}


def _copy_repo_tree(src: Path, dst: Path) -> None:
    def ignore(_dir: str, names: list[str]) -> set[str]:
        return {name for name in names if name in {".git", ".venv", "node_modules", ".pytest_cache", "__pycache__"}}

    shutil.copytree(src, dst, ignore=ignore)


def _copy_release_root(src_root: Path, dst_root: Path) -> None:
    for name in REPO_NAMES:
        _copy_repo_tree(src_root / name, dst_root / name)


IMPORT_WRAPPER = (
    "import os, runpy, sys; "
    "script = sys.argv[1]; "
    "sys.argv = sys.argv[1:]; "
    "token_file = os.environ.pop('ENOCH_CONTROL_TOKEN_FILE'); "
    "os.environ['ENOCH_CONTROL_TOKEN'] = open(token_file, encoding='utf-8').read().strip(); "
    "runpy.run_path(script, run_name='__main__')"
)


def _import_cmd(*, base_url: str, limit: int, dry_run: bool) -> list[str]:
    cmd = [
        sys.executable,
        "-c",
        IMPORT_WRAPPER,
        "scripts/import_from_control_plane.py",
        "--control-url",
        base_url,
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


@contextmanager
def _control_token_file(token: str):
    fd, path = tempfile.mkstemp(prefix="enoch-control-token-", text=True)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(token)
        yield Path(path)
    finally:
        Path(path).unlink(missing_ok=True)


def _import_env(token_file: Path) -> dict[str, str]:
    # Pass only the pathname in the child initial environment. The wrapper reads
    # the 0600 token file and injects ENOCH_CONTROL_TOKEN in-process before
    # running the corpus importer, avoiding bearer-token exposure in argv,
    # subprocess exceptions, and the child's initial /proc environment.
    return {"ENOCH_CONTROL_TOKEN_FILE": str(token_file), "ENOCH_CONTROL_TOKEN": ""}


def _redact_command(cmd: object) -> object:
    if not isinstance(cmd, list):
        return cmd
    redacted: list[object] = []
    skip_next = False
    for item in cmd:
        text = str(item)
        if skip_next:
            redacted.append("<redacted>")
            skip_next = False
            continue
        redacted.append(item)
        if text in {"--token", "--github-token", "--api-key"}:
            skip_next = True
    return redacted


def _exception_summary(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        return json.dumps(
            {
                "type": type(exc).__name__,
                "returncode": exc.returncode,
                "cmd": _redact_command(exc.cmd),
                "stdout_tail": str(exc.output or "")[-800:],
                "stderr_tail": str(exc.stderr or "")[-800:],
            },
            sort_keys=True,
        )
    return f"{type(exc).__name__}: {exc}"


def _run_import_dry_run_with_retries(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> tuple[subprocess.CompletedProcess[str], int]:
    attempts = _bounded_int("ENOCH_CORPUS_IMPORT_DRY_RUN_RETRIES", 3, 1, 5)
    delay = _bounded_float("ENOCH_CORPUS_IMPORT_DRY_RUN_RETRY_DELAY_SEC", 3.0, 0.0, 30.0)
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return _run(cmd, cwd=cwd, env=env), attempt
        except Exception as exc:  # noqa: BLE001 - retry bounded preflight only
            last_exc = exc
            if attempt >= attempts:
                break
            if delay > 0:
                time.sleep(delay)
    assert last_exc is not None
    raise RuntimeError(_exception_summary(last_exc)) from last_exc


def _run_named_steps(cwd: Path, steps: list[tuple[str, list[str]]]) -> list[dict[str, Any]]:
    out = []
    for name, cmd in steps:
        result = _run(cmd, cwd=cwd)
        out.append({"name": name, "stdout_tail": result.stdout[-1200:], "stderr_tail": result.stderr[-1200:]})
    return out


def _corpus_rebuild(corpus: Path) -> list[dict[str, Any]]:
    steps = [
        ("audit_claim_evidence", [sys.executable, "scripts/audit_claim_evidence_contract.py"]),
        ("quality_scan", [sys.executable, "scripts/quality_scan.py"]),
        ("build_index", [sys.executable, "scripts/build_index.py"]),
    ]
    return _run_named_steps(corpus, steps)


def _corpus_trust_checks(corpus: Path) -> list[dict[str, Any]]:
    return _run_named_steps(corpus, [("validate_public_trust_surfaces", [sys.executable, "scripts/validate_public_trust_surfaces.py"])])


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


def _update_public_counts(system: Path, root: Path, manifest: Path) -> dict[str, Any]:
    result = _run(
        [
            sys.executable,
            "scripts/update_public_release_counts.py",
            "--root",
            str(root),
            "--generated-manifest",
            str(manifest),
        ],
        cwd=system,
    )
    return json.loads(result.stdout)


def _is_clean_noop_dry_run(payload: dict[str, Any]) -> bool:
    """Return true when there is simply nothing importable right now."""

    return (
        not payload.get("failed")
        and int(payload.get("imported") or 0) == 0
        and int(payload.get("updated") or 0) == 0
        and not payload.get("errors")
    )


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
    fast_forwarded: list[str] = []

    config = _load_config()
    token = os.environ.get("ENOCH_CONTROL_TOKEN") or str(config.get("control_api_bearer_token") or "")
    if not token:
        print(json.dumps({"ok": False, "action": "blocked", "reason": "missing control-plane token"}, sort_keys=True), file=sys.stderr)
        return 2
    base_url = _base_url(config)
    system = root / "enoch-agentic-research-system"
    corpus = root / "enoch-ai-research-corpus"
    skip_github = _truthy("ENOCH_CORPUS_IMPORT_SKIP_GITHUB_METADATA", "1")

    with _control_token_file(token) as token_file:

        try:
            dry, dry_run_attempts = _run_import_dry_run_with_retries(_import_cmd(base_url=base_url, limit=limit, dry_run=True), cwd=corpus, env=_import_env(token_file))
            dry_payload = json.loads(dry.stdout)
        except Exception as exc:  # noqa: BLE001 - fail closed without writes
            print(json.dumps({"ok": False, "action": "dry_run_failed", "reason": _exception_summary(exc)}, sort_keys=True), file=sys.stderr)
            return 1
        if dry_payload.get("failed"):
            print(json.dumps({"ok": False, "action": "blocked", "reason": "bounded import dry-run failed", "dry_run": dry_payload}, sort_keys=True), file=sys.stderr)
            return 1
        if not dry_payload.get("imported"):
            if _is_clean_noop_dry_run(dry_payload):
                ledger_sync: dict[str, Any] = {}
                if _truthy("ENOCH_CORPUS_IMPORT_SYNC_LEDGER", "0"):
                    ledger_sync = _sync_corpus_ledger(system, corpus)
                print(json.dumps({"ok": True, "action": "skipped", "reason": "no clean importable papers", "dry_run": dry_payload, "dry_run_attempts": dry_run_attempts, "fast_forwarded": fast_forwarded, "ledger_sync": ledger_sync}, sort_keys=True))
                return 0
            print(json.dumps({"ok": False, "action": "blocked", "reason": "bounded import dry-run found no clean importable papers", "dry_run": dry_payload, "dry_run_attempts": dry_run_attempts, "fast_forwarded": fast_forwarded}, sort_keys=True), file=sys.stderr)
            return 1

        with tempfile.TemporaryDirectory(prefix="enoch-corpus-import-preflight-") as tmp:
            tmp_root = Path(tmp)
            _copy_release_root(root, tmp_root)
            tmp_system = tmp_root / "enoch-agentic-research-system"
            tmp_corpus = tmp_root / "enoch-ai-research-corpus"
            live_preflight = _run(_import_cmd(base_url=base_url, limit=limit, dry_run=False), cwd=tmp_corpus, env=_import_env(token_file))
            live_payload = json.loads(live_preflight.stdout)
            if live_payload.get("failed"):
                print(json.dumps({"ok": False, "action": "preflight_import_failed", "preflight": live_payload}, sort_keys=True), file=sys.stderr)
                return 1
            checks = _corpus_rebuild(tmp_corpus)
            count_update = _update_public_counts(tmp_system, tmp_root, tmp_root / "enoch-ecosystem.generated.json")
            checks.extend(_corpus_trust_checks(tmp_corpus))
            release_validation = _validate_release(tmp_system, tmp_root, tmp_corpus, tmp_root / "enoch-ecosystem.generated.json", skip_github_metadata=True)

        if _truthy("ENOCH_CORPUS_IMPORT_PREFLIGHT_ONLY", "0"):
            print(json.dumps({"ok": True, "action": "preflight_only", "limit": limit, "dry_run": dry_payload, "dry_run_attempts": dry_run_attempts, "preflight_import": live_payload, "count_update": count_update, "corpus_checks": checks, "release_validation": release_validation, "fast_forwarded": fast_forwarded}, sort_keys=True))
            return 0

        live = _run(_import_cmd(base_url=base_url, limit=limit, dry_run=False), cwd=corpus, env=_import_env(token_file))
        live_payload = json.loads(live.stdout)
        checks = _corpus_rebuild(corpus)
        count_update = _update_public_counts(system, root, Path(os.environ.get("ENOCH_ECOSYSTEM_MANIFEST", "/tmp/enoch-ecosystem.generated.json")))
        checks.extend(_corpus_trust_checks(corpus))
        github_metadata: dict[str, Any] = {}
        if _truthy("ENOCH_CORPUS_IMPORT_UPDATE_GITHUB_METADATA", "0"):
            stats = count_update.get("stats") if isinstance(count_update.get("stats"), dict) else {}
            artifact_count = int(stats.get("artifact_count") or count_update.get("artifact_count") or 0)
            if artifact_count <= 0:
                raise RuntimeError("could not determine artifact count for GitHub metadata update")
            github_metadata = _update_github_metadata(artifact_count)
        release_validation = _validate_release(system, root, corpus, Path(os.environ.get("ENOCH_ECOSYSTEM_MANIFEST", "/tmp/enoch-ecosystem.generated.json")), skip_github_metadata=skip_github)
        changed_repos = _git_changed_repos(root)
        commits: list[dict[str, str]] = []
        pushed: list[dict[str, str]] = []
        if _truthy("ENOCH_CORPUS_IMPORT_AUTOCOMMIT", "0"):
            commits = _commit_changed_repos(root, live_payload, count_update)
            if _truthy("ENOCH_CORPUS_IMPORT_PUSH", "0"):
                pushed = _push_commits(root, commits)
        ledger_sync: dict[str, Any] = {}
        if _truthy("ENOCH_CORPUS_IMPORT_SYNC_LEDGER", "0"):
            if _truthy("ENOCH_CORPUS_IMPORT_PUSH", "0") and not pushed:
                raise RuntimeError("ledger sync requires pushed commits when ENOCH_CORPUS_IMPORT_PUSH=1")
            ledger_sync = _sync_corpus_ledger(system, corpus)
        print(json.dumps({"ok": True, "action": "corpus_imported", "limit": limit, "dry_run": dry_payload, "dry_run_attempts": dry_run_attempts, "import_result": live_payload, "count_update": count_update, "corpus_checks": checks, "github_metadata": github_metadata, "release_validation": release_validation, "changed_repos": changed_repos, "commits": commits, "pushed": pushed, "ledger_sync": ledger_sync, "fast_forwarded": fast_forwarded}, sort_keys=True))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
