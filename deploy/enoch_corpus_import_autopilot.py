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
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from enoch_control_plane.url_safety import secure_default_service_url
from enoch_control_plane.url_safety import urlopen_validated


REPO_NAMES = [
    "enoch-agentic-research-system",
    "enoch-ai-research-corpus",
    "enoch-promising-signals",
    "enoch-docs",
    "alias8818.github.io",
    "alias8818",
    "jeremyblankenship.dev",
]


def _truthy(name: str, default: str = "0") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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
    path = Path(
        os.environ.get("ENOCH_CONFIG")
        or os.environ.get(
            "ENOCH_CONTROL_PLANE_CONFIG", "/etc/enoch-control-plane/config.json"
        )
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _base_url(config: dict[str, Any]) -> str:
    host = str(config.get("listen_host") or "127.0.0.1")
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return os.environ.get("ENOCH_CONTROL_URL") or secure_default_service_url(
        host, int(config.get("listen_port") or 8787)
    )


def _get_json(base_url: str, path: str, token: str, *, timeout: int = 30) -> dict:
    req = Request(
        f"{base_url}{path}",
        method="GET",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urlopen_validated(
        req,
        timeout=timeout,
        field_name="deploy/enoch_corpus_import_autopilot.py url",
        allow_private=True,
    ) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _release_root() -> Path:
    return (
        Path(
            os.environ.get(
                "ENOCH_RELEASE_ROOT", "/home/jeremy/Desktop/projects/enoch-release"
            )
        )
        .expanduser()
        .resolve()
    )


def _run(
    cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        cmd, cwd=str(cwd), env=merged, text=True, capture_output=True, check=True
    )


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


def _commit_message(
    repo_name: str, import_result: dict[str, Any], count_update: dict[str, Any]
) -> str:
    imported = int(import_result.get("imported") or 0)
    stats = (
        count_update.get("stats") if isinstance(count_update.get("stats"), dict) else {}
    )
    total = (
        count_update.get("artifact_count")
        or count_update.get("total_artifacts")
        or stats.get("artifact_count")
        or "current"
    )
    if repo_name == "enoch-ai-research-corpus":
        subject = (
            f"Import {imported} Enoch corpus artifact"
            if imported == 1
            else f"Import {imported} Enoch corpus artifacts"
        )
        body = f"Import {imported} finalized publication draft(s) from the control plane.\n\nCorpus artifact count after validation: {total}.\n"
    elif repo_name == "enoch-promising-signals":
        subject = "Refresh Enoch promising signals"
        body = (
            "Refresh bounded useful/promising signal exports from the control plane.\n\n"
            f"Corpus artifact count after validation: {total}.\n"
        )
    else:
        subject = "Refresh Enoch corpus release counts"
        body = f"Refresh public release surfaces after importing {imported} finalized publication draft(s).\n\nCorpus artifact count after validation: {total}.\n"
    return f"{subject}\n\n{body}"


def _commit_changed_repos(
    root: Path, import_result: dict[str, Any], count_update: dict[str, Any]
) -> list[dict[str, str]]:
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
        try:
            _run(["git", "push"], cwd=root / item["repo"])
        except subprocess.CalledProcessError as exc:
            pushed.append(
                {
                    **item,
                    "ok": "false",
                    "action": "push_skipped",
                    "error": _exception_summary(exc),
                }
            )
            continue
        pushed.append({**item, "ok": "true"})
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
    with urlopen_validated(
        request,
        timeout=30,
        field_name="deploy/enoch_corpus_import_autopilot.py url",
        allow_private=False,
    ) as response:
        metadata = json.loads(response.read().decode("utf-8"))
    return {
        "repo": "alias8818/enoch-ai-research-corpus",
        "description": metadata.get("description"),
        "homepage": metadata.get("homepage"),
    }


def _update_promising_github_metadata(signal_count: int) -> dict[str, Any]:
    token = _github_token()
    if not token:
        raise RuntimeError("missing GitHub token for promising signals metadata update")
    payload = json.dumps(
        {
            "description": f"{signal_count} bounded Enoch promising signals preserved for larger-compute follow-up; not validated papers, not peer reviewed, and separate from the paper corpus.",
            "homepage": "https://alias8818.github.io/enoch-agentic-research-system/",
        }
    ).encode("utf-8")
    request = Request(
        "https://api.github.com/repos/alias8818/enoch-promising-signals",
        data=payload,
        method="PATCH",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "enoch-corpus-import-autopilot/1.0",
        },
    )
    with urlopen_validated(
        request,
        timeout=30,
        field_name="deploy/enoch_corpus_import_autopilot.py promising signals url",
        allow_private=False,
    ) as response:
        metadata = json.loads(response.read().decode("utf-8"))
    return {
        "repo": "alias8818/enoch-promising-signals",
        "description": metadata.get("description"),
        "homepage": metadata.get("homepage"),
    }


def _copy_repo_tree(src: Path, dst: Path) -> None:
    def ignore(_dir: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in {".git", ".venv", "node_modules", ".pytest_cache", "__pycache__"}
        }

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


def _ecosystem_manifest_path() -> Path:
    override = os.environ.get("ENOCH_ECOSYSTEM_MANIFEST")
    if override:
        return Path(override)
    fd, path = tempfile.mkstemp(
        prefix="enoch-ecosystem.generated.",
        suffix=".json",
    )
    os.close(fd)
    return Path(path)


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


def _run_import_dry_run_with_retries(
    cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None
) -> tuple[subprocess.CompletedProcess[str], int]:
    attempts = _bounded_int("ENOCH_CORPUS_IMPORT_DRY_RUN_RETRIES", 3, 1, 5)
    delay = _bounded_float(
        "ENOCH_CORPUS_IMPORT_DRY_RUN_RETRY_DELAY_SEC", 3.0, 0.0, 30.0
    )
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
    if last_exc is None:
        raise RuntimeError("preflight retry exhausted without captured exception")
    raise RuntimeError(_exception_summary(last_exc)) from last_exc


def _run_named_steps(
    cwd: Path, steps: list[tuple[str, list[str]]]
) -> list[dict[str, Any]]:
    out = []
    for name, cmd in steps:
        result = _run(cmd, cwd=cwd)
        out.append(
            {
                "name": name,
                "stdout_tail": result.stdout[-1200:],
                "stderr_tail": result.stderr[-1200:],
            }
        )
    return out


def _corpus_rebuild(corpus: Path) -> list[dict[str, Any]]:
    steps = [
        (
            "audit_claim_evidence",
            [sys.executable, "scripts/audit_claim_evidence_contract.py"],
        ),
        ("quality_scan", [sys.executable, "scripts/quality_scan.py"]),
        ("build_index", [sys.executable, "scripts/build_index.py"]),
    ]
    return _run_named_steps(corpus, steps)


def _corpus_trust_checks(corpus: Path) -> list[dict[str, Any]]:
    return _run_named_steps(
        corpus,
        [
            (
                "validate_public_trust_surfaces",
                [sys.executable, "scripts/validate_public_trust_surfaces.py"],
            )
        ],
    )


def _validate_release(
    system: Path,
    root: Path,
    corpus: Path,
    manifest: Path,
    *,
    skip_github_metadata: bool,
) -> dict[str, Any]:
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
    promising = root / "enoch-promising-signals"
    if promising.exists():
        cmd.extend(["--promising", str(promising)])
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
    if promising.exists():
        validate_cmd.extend(["--promising", str(promising)])
    if skip_github_metadata:
        validate_cmd.append("--skip-github-metadata")
    val = _run(validate_cmd, cwd=system)
    return {
        "generate_stdout": gen.stdout[-1200:],
        "validate_stdout": val.stdout[-1200:],
    }


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


def _refresh_promising_signals(system: Path, root: Path) -> dict[str, Any]:
    if not _truthy("ENOCH_CORPUS_IMPORT_REFRESH_PROMISING_SIGNALS", "1"):
        return {"ok": True, "action": "skipped", "reason": "disabled"}
    database_url = (
        os.environ.get("ENOCH_PROMISING_SIGNALS_DATABASE_URL")
        or os.environ.get("ENOCH_CONTROL_DATABASE_URL")
        or os.environ.get("ENOCH_SUPABASE_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or ""
    )
    if not database_url:
        return {
            "ok": True,
            "action": "skipped",
            "reason": "missing database url",
        }
    promising = root / "enoch-promising-signals"
    if not promising.exists():
        return {
            "ok": True,
            "action": "skipped",
            "reason": "missing enoch-promising-signals repo",
        }

    export = _run(
        [
            sys.executable,
            "scripts/export_promising_signals.py",
            "--output-repo",
            str(promising),
            "--clean-only",
        ],
        cwd=system,
        env={
            "ENOCH_SUPABASE_DATABASE_URL": database_url,
            "ENOCH_PROMISING_SIGNALS_SOURCE_CUTOFF": os.environ.get(
                "ENOCH_PROMISING_SIGNALS_SOURCE_CUTOFF", "2026-05-19T17:51:00Z"
            ),
        },
    )
    release_gate = _run(
        [
            sys.executable,
            "scripts/export_promising_signals.py",
            "--output-repo",
            str(promising),
            "--validate-output-repo",
        ],
        cwd=system,
        env={
            "ENOCH_SUPABASE_DATABASE_URL": database_url,
            "ENOCH_PROMISING_SIGNALS_SOURCE_CUTOFF": os.environ.get(
                "ENOCH_PROMISING_SIGNALS_SOURCE_CUTOFF", "2026-05-19T17:51:00Z"
            ),
        },
    )
    validation = _run(
        [
            sys.executable,
            "scripts/validate_promising_signals_release.py",
            "--promising",
            str(promising),
        ],
        cwd=system,
    )
    manifest = json.loads(
        (promising / "data" / "manifest.json").read_text(encoding="utf-8")
    )
    export_payload = json.loads(export.stdout or "{}")
    release_gate_payload = json.loads(release_gate.stdout or "{}")
    validation_payload = json.loads(validation.stdout or "{}")
    return {
        "ok": True,
        "action": "promising_signals_refreshed",
        "export_count": export_payload.get("count"),
        "release_gate_count": release_gate_payload.get("count"),
        "validation_count": validation_payload.get("signal_count"),
        "manifest_record_count": manifest.get("record_count"),
        "selection_summary": manifest.get("selection_summary"),
    }


def _control_plane_root() -> Path:
    return Path(
        os.environ.get("ENOCH_CONTROL_PLANE_ROOT")
        or Path(__file__).resolve().parents[1]
    ).resolve()


def _refresh_paper_material_graph(
    root: Path, *, control_plane_root: Path | None = None
) -> dict[str, Any]:
    if not _truthy("ENOCH_CORPUS_IMPORT_REFRESH_PAPER_MATERIAL_GRAPH", "1"):
        return {"ok": True, "action": "skipped", "reason": "disabled"}
    control_plane = (control_plane_root or _control_plane_root()).resolve()
    script = control_plane / "deploy" / "enoch_paper_material_graph.sh"
    output_dir = (
        root / "enoch-agentic-research-system" / "docs" / "paper-material-graph"
    )
    result = _run(
        [str(script)],
        cwd=control_plane,
        env={
            "ENOCH_ENABLE_PAPER_MATERIAL_GRAPH": "1",
            "ENOCH_RELEASE_ROOT": str(root),
            "ENOCH_CONTROL_PLANE_ROOT": str(control_plane),
            "ENOCH_PAPER_MATERIAL_GRAPH_DIR": str(output_dir),
        },
    )
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        payload = {"ok": True, "stdout_tail": result.stdout[-1200:]}
    payload.setdefault("ok", True)
    payload["action"] = "paper_material_graph_refreshed"
    return payload


def _is_clean_noop_dry_run(payload: dict[str, Any]) -> bool:
    """Return true when there is simply nothing importable right now."""

    return (
        not payload.get("failed")
        and int(payload.get("imported") or 0) == 0
        and int(payload.get("updated") or 0) == 0
        and not payload.get("errors")
    )


def _main_autopilot_disabled_exit() -> int | None:
    if _truthy("ENOCH_ENABLE_CORPUS_IMPORT_AUTOPILOT"):
        return None
    print(
        json.dumps(
            {
                "ok": True,
                "action": "skipped",
                "reason": "corpus import autopilot disabled; set ENOCH_ENABLE_CORPUS_IMPORT_AUTOPILOT=1",
            },
            sort_keys=True,
        )
    )
    return 0


def _main_missing_release_repos_exit(root: Path) -> int | None:
    missing = [name for name in REPO_NAMES if not (root / name).is_dir()]
    if not missing:
        return None
    print(
        json.dumps(
            {
                "ok": False,
                "action": "blocked",
                "reason": "release repos missing",
                "missing": missing,
                "release_root": str(root),
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return 2


def _main_dirty_release_repos_exit(root: Path) -> int | None:
    dirty = [name for name in REPO_NAMES if not _git_clean(root / name)]
    if not dirty:
        return None
    print(
        json.dumps(
            {
                "ok": False,
                "action": "blocked",
                "reason": "release repos are dirty before import",
                "dirty_repos": dirty,
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return 2


def _resolve_control_token(config: dict[str, Any]) -> str:
    return os.environ.get("ENOCH_CONTROL_TOKEN") or str(
        config.get("control_api_bearer_token") or ""
    )


def _control_hold_skip_result(base_url: str, token: str) -> dict[str, Any] | None:
    if _truthy("ENOCH_CORPUS_IMPORT_RUN_WHILE_HELD", "0"):
        return None
    try:
        status = _get_json(base_url, "/control/api/status", token, timeout=10)
    except (OSError, ValueError) as exc:
        return {
            "ok": True,
            "action": "skipped",
            "reason": "corpus import autopilot skipped because control-plane hold status could not be verified",
            "control_status_unreachable": True,
            "error": _exception_summary(exc),
        }
    flags = status.get("flags") if isinstance(status, dict) else {}
    if not isinstance(flags, dict):
        return None
    held_by: list[str] = []
    if bool(flags.get("maintenance_mode")):
        held_by.append("maintenance_mode")
    if bool(flags.get("queue_paused")):
        held_by.append("queue_paused")
    if not held_by:
        return None
    return {
        "ok": True,
        "action": "skipped",
        "reason": f"corpus import autopilot skipped while control plane is held: {', '.join(held_by)}",
        "hold_state": {
            "queue_paused": bool(flags.get("queue_paused")),
            "maintenance_mode": bool(flags.get("maintenance_mode")),
            "pause_reason": str(flags.get("pause_reason") or ""),
            "paused_at": str(flags.get("paused_at") or ""),
            "paused_by": str(flags.get("paused_by") or ""),
        },
    }


def _main_control_hold_exit(base_url: str, token: str) -> int | None:
    result = _control_hold_skip_result(base_url, token)
    if result is None:
        return None
    print(json.dumps(result, sort_keys=True))
    return 0


def _main_missing_token_exit(token: str) -> int | None:
    if token:
        return None
    print(
        json.dumps(
            {
                "ok": False,
                "action": "blocked",
                "reason": "missing control-plane token",
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return 2


def _run_dry_run_import(
    *,
    base_url: str,
    limit: int,
    corpus: Path,
    token_file: Path,
) -> tuple[dict[str, Any], int]:
    dry, dry_run_attempts = _run_import_dry_run_with_retries(
        _import_cmd(base_url=base_url, limit=limit, dry_run=True),
        cwd=corpus,
        env=_import_env(token_file),
    )
    return json.loads(dry.stdout), dry_run_attempts


def _print_dry_run_failed_exit(exc: Exception) -> int:
    print(
        json.dumps(
            {
                "ok": False,
                "action": "dry_run_failed",
                "reason": _exception_summary(exc),
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return 1


def _dry_run_bounded_failed_exit(dry_payload: dict[str, Any]) -> int | None:
    if not dry_payload.get("failed"):
        return None
    print(
        json.dumps(
            {
                "ok": False,
                "action": "blocked",
                "reason": "bounded import dry-run failed",
                "dry_run": dry_payload,
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return 1


def _no_import_dry_run_exit(
    *,
    root: Path,
    dry_payload: dict[str, Any],
    dry_run_attempts: int,
    fast_forwarded: list[str],
    system: Path,
    corpus: Path,
    skip_github: bool,
) -> int | None:
    if dry_payload.get("imported"):
        return None
    if _is_clean_noop_dry_run(dry_payload):
        ledger_sync: dict[str, Any] = {}
        promising_signals = _refresh_promising_signals(system, root)
        count_update: dict[str, Any] = {}
        github_metadata: dict[str, Any] = {}
        release_validation: dict[str, Any] = {}
        paper_material_graph: dict[str, Any] = {}
        changed_repos: list[str] = []
        commits: list[dict[str, str]] = []
        pushed: list[dict[str, str]] = []
        if promising_signals.get("action") == "promising_signals_refreshed":
            ecosystem_manifest = _ecosystem_manifest_path()
            count_update = _update_public_counts(system, root, ecosystem_manifest)
            paper_material_graph = _refresh_paper_material_graph(root)
            github_metadata = _maybe_github_metadata(count_update)
            release_validation = _validate_release(
                system,
                root,
                corpus,
                ecosystem_manifest,
                skip_github_metadata=skip_github
                or _github_metadata_update_unavailable(github_metadata),
            )
            changed_repos = _git_changed_repos(root)
            commits, pushed = _autocommit_and_push(root, dry_payload, count_update)
        if _truthy("ENOCH_CORPUS_IMPORT_SYNC_LEDGER", "0"):
            ledger_sync = _maybe_ledger_sync(system, corpus, pushed)
        print(
            json.dumps(
                {
                    "ok": True,
                    "action": "skipped",
                    "reason": "no clean importable papers",
                    "dry_run": dry_payload,
                    "dry_run_attempts": dry_run_attempts,
                    "fast_forwarded": fast_forwarded,
                    "ledger_sync": ledger_sync,
                    "promising_signals": promising_signals,
                    "count_update": count_update,
                    "github_metadata": github_metadata,
                    "release_validation": release_validation,
                    "paper_material_graph": paper_material_graph,
                    "changed_repos": changed_repos,
                    "commits": commits,
                    "pushed": pushed,
                },
                sort_keys=True,
            )
        )
        return 0
    print(
        json.dumps(
            {
                "ok": False,
                "action": "blocked",
                "reason": "bounded import dry-run found no clean importable papers",
                "dry_run": dry_payload,
                "dry_run_attempts": dry_run_attempts,
                "fast_forwarded": fast_forwarded,
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return 1


def _run_preflight_import(
    *,
    root: Path,
    base_url: str,
    limit: int,
    token_file: Path,
) -> tuple[int | None, dict[str, Any] | None]:
    with tempfile.TemporaryDirectory(prefix="enoch-corpus-import-preflight-") as tmp:
        tmp_root = Path(tmp)
        _copy_release_root(root, tmp_root)
        tmp_system = tmp_root / "enoch-agentic-research-system"
        tmp_corpus = tmp_root / "enoch-ai-research-corpus"
        live_preflight = _run(
            _import_cmd(base_url=base_url, limit=limit, dry_run=False),
            cwd=tmp_corpus,
            env=_import_env(token_file),
        )
        live_payload = json.loads(live_preflight.stdout)
        if live_payload.get("failed"):
            print(
                json.dumps(
                    {
                        "ok": False,
                        "action": "preflight_import_failed",
                        "preflight": live_payload,
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 1, None
        checks = _corpus_rebuild(tmp_corpus)
        count_update = _update_public_counts(
            tmp_system, tmp_root, tmp_root / "enoch-ecosystem.generated.json"
        )
        checks.extend(_corpus_trust_checks(tmp_corpus))
        paper_material_graph = _refresh_paper_material_graph(tmp_root)
        release_validation = _validate_release(
            tmp_system,
            tmp_root,
            tmp_corpus,
            tmp_root / "enoch-ecosystem.generated.json",
            skip_github_metadata=True,
        )
    return None, {
        "live_payload": live_payload,
        "checks": checks,
        "count_update": count_update,
        "paper_material_graph": paper_material_graph,
        "release_validation": release_validation,
    }


def _print_preflight_only_result(
    *,
    limit: int,
    dry_payload: dict[str, Any],
    dry_run_attempts: int,
    preflight: dict[str, Any],
    fast_forwarded: list[str],
) -> int:
    print(
        json.dumps(
            {
                "ok": True,
                "action": "preflight_only",
                "limit": limit,
                "dry_run": dry_payload,
                "dry_run_attempts": dry_run_attempts,
                "preflight_import": preflight["live_payload"],
                "count_update": preflight["count_update"],
                "corpus_checks": preflight["checks"],
                "paper_material_graph": preflight["paper_material_graph"],
                "release_validation": preflight["release_validation"],
                "fast_forwarded": fast_forwarded,
            },
            sort_keys=True,
        )
    )
    return 0


def _maybe_github_metadata(count_update: dict[str, Any]) -> dict[str, Any]:
    if not _truthy("ENOCH_CORPUS_IMPORT_UPDATE_GITHUB_METADATA", "0"):
        return {}
    stats_raw = count_update.get("stats")
    stats: dict[str, Any] = stats_raw if isinstance(stats_raw, dict) else {}
    artifact_count = int(
        stats.get("artifact_count") or count_update.get("artifact_count") or 0
    )
    if artifact_count <= 0:
        raise RuntimeError(
            "could not determine artifact count for GitHub metadata update"
        )
    try:
        metadata: dict[str, Any] = {"corpus": _update_github_metadata(artifact_count)}
    except (HTTPError, URLError, RuntimeError, ValueError) as exc:
        return {
            "ok": False,
            "action": "skipped",
            "reason": "github metadata update unavailable",
            "error": f"{type(exc).__name__}: {exc}",
        }
    promising_signal_count = int(stats.get("promising_signal_count") or 0)
    if promising_signal_count > 0:
        try:
            metadata["promising_signals"] = _update_promising_github_metadata(
                promising_signal_count
            )
        except (HTTPError, URLError, RuntimeError, ValueError) as exc:
            metadata["promising_signals"] = {
                "ok": False,
                "action": "skipped",
                "reason": "github promising signals metadata update unavailable",
                "error": f"{type(exc).__name__}: {exc}",
            }
    return metadata


def _github_metadata_update_unavailable(github_metadata: dict[str, Any]) -> bool:
    if not github_metadata:
        return False
    if github_metadata.get("ok") is False:
        return True
    for value in github_metadata.values():
        if isinstance(value, dict) and value.get("ok") is False:
            return True
    return False


def _autocommit_and_push(
    root: Path,
    live_payload: dict[str, Any],
    count_update: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    commits: list[dict[str, str]] = []
    pushed: list[dict[str, str]] = []
    if _truthy("ENOCH_CORPUS_IMPORT_AUTOCOMMIT", "0"):
        commits = _commit_changed_repos(root, live_payload, count_update)
        if _truthy("ENOCH_CORPUS_IMPORT_PUSH", "0"):
            pushed = _push_commits(root, commits)
    return commits, pushed


def _maybe_ledger_sync(
    system: Path,
    corpus: Path,
    pushed: list[dict[str, str]],
) -> dict[str, Any]:
    if not _truthy("ENOCH_CORPUS_IMPORT_SYNC_LEDGER", "0"):
        return {}
    if _truthy("ENOCH_CORPUS_IMPORT_PUSH", "0") and not pushed:
        raise RuntimeError(
            "ledger sync requires pushed commits when ENOCH_CORPUS_IMPORT_PUSH=1"
        )
    failed_pushes = [item for item in pushed if item.get("ok") != "true"]
    if _truthy("ENOCH_CORPUS_IMPORT_PUSH", "0") and failed_pushes:
        repos = ", ".join(
            str(item.get("repo") or "<unknown>") for item in failed_pushes
        )
        ledger_sync = _sync_corpus_ledger(system, corpus)
        ledger_sync.setdefault("warnings", []).append(
            f"push unavailable for {repos}; ledger sync completed but publication push remains advisory"
        )
        ledger_sync["push_blocker"] = repos
        return ledger_sync
    return _sync_corpus_ledger(system, corpus)


def _execute_live_corpus_import(
    *,
    root: Path,
    system: Path,
    corpus: Path,
    base_url: str,
    limit: int,
    token_file: Path,
    skip_github: bool,
    dry_payload: dict[str, Any],
    dry_run_attempts: int,
    fast_forwarded: list[str],
) -> int:
    ecosystem_manifest = _ecosystem_manifest_path()
    live = _run(
        _import_cmd(base_url=base_url, limit=limit, dry_run=False),
        cwd=corpus,
        env=_import_env(token_file),
    )
    live_payload = json.loads(live.stdout)
    checks = _corpus_rebuild(corpus)
    count_update = _update_public_counts(system, root, ecosystem_manifest)
    checks.extend(_corpus_trust_checks(corpus))
    github_metadata = _maybe_github_metadata(count_update)
    paper_material_graph = _refresh_paper_material_graph(root)
    release_validation = _validate_release(
        system,
        root,
        corpus,
        ecosystem_manifest,
        skip_github_metadata=skip_github
        or _github_metadata_update_unavailable(github_metadata),
    )
    changed_repos = _git_changed_repos(root)
    commits, pushed = _autocommit_and_push(root, live_payload, count_update)
    ledger_sync = _maybe_ledger_sync(system, corpus, pushed)
    print(
        json.dumps(
            {
                "ok": True,
                "action": "corpus_imported",
                "limit": limit,
                "dry_run": dry_payload,
                "dry_run_attempts": dry_run_attempts,
                "import_result": live_payload,
                "count_update": count_update,
                "corpus_checks": checks,
                "github_metadata": github_metadata,
                "release_validation": release_validation,
                "paper_material_graph": paper_material_graph,
                "changed_repos": changed_repos,
                "commits": commits,
                "pushed": pushed,
                "ledger_sync": ledger_sync,
                "fast_forwarded": fast_forwarded,
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    exit_code = _main_autopilot_disabled_exit()
    if exit_code is not None:
        return exit_code

    config = _load_config()
    token = _resolve_control_token(config)
    exit_code = _main_missing_token_exit(token)
    if exit_code is not None:
        return exit_code

    base_url = _base_url(config)
    exit_code = _main_control_hold_exit(base_url, token)
    if exit_code is not None:
        return exit_code

    limit = _bounded_int("ENOCH_CORPUS_IMPORT_LIMIT", 1, 1, 2)
    root = _release_root()

    exit_code = _main_missing_release_repos_exit(root)
    if exit_code is not None:
        return exit_code

    exit_code = _main_dirty_release_repos_exit(root)
    if exit_code is not None:
        return exit_code

    fast_forwarded: list[str] = []
    system = root / "enoch-agentic-research-system"
    corpus = root / "enoch-ai-research-corpus"
    skip_github = _truthy("ENOCH_CORPUS_IMPORT_SKIP_GITHUB_METADATA", "1")

    with _control_token_file(token) as token_file:
        try:
            dry_payload, dry_run_attempts = _run_dry_run_import(
                base_url=base_url,
                limit=limit,
                corpus=corpus,
                token_file=token_file,
            )
        except Exception as exc:  # noqa: BLE001 - fail closed without writes
            return _print_dry_run_failed_exit(exc)

        exit_code = _dry_run_bounded_failed_exit(dry_payload)
        if exit_code is not None:
            return exit_code

        exit_code = _no_import_dry_run_exit(
            root=root,
            dry_payload=dry_payload,
            dry_run_attempts=dry_run_attempts,
            fast_forwarded=fast_forwarded,
            system=system,
            corpus=corpus,
            skip_github=skip_github,
        )
        if exit_code is not None:
            return exit_code

        exit_code, preflight = _run_preflight_import(
            root=root,
            base_url=base_url,
            limit=limit,
            token_file=token_file,
        )
        if exit_code is not None:
            return exit_code
        if preflight is None:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "action": "preflight_import_failed",
                        "reason": "preflight returned no result",
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 1

        if _truthy("ENOCH_CORPUS_IMPORT_PREFLIGHT_ONLY", "0"):
            return _print_preflight_only_result(
                limit=limit,
                dry_payload=dry_payload,
                dry_run_attempts=dry_run_attempts,
                preflight=preflight,
                fast_forwarded=fast_forwarded,
            )

        return _execute_live_corpus_import(
            root=root,
            system=system,
            corpus=corpus,
            base_url=base_url,
            limit=limit,
            token_file=token_file,
            skip_github=skip_github,
            dry_payload=dry_payload,
            dry_run_attempts=dry_run_attempts,
            fast_forwarded=fast_forwarded,
        )


if __name__ == "__main__":
    raise SystemExit(main())
