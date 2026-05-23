#!/usr/bin/env python3
"""Validate that a deployed Enoch runtime matches a source checkout.

The production control-plane runtime may be a copied tree instead of a git
checkout. This validator makes that explicit by comparing deterministic file
hashes from a source checkout to the runtime directory and, optionally,
checking the source checkout commit against an expected commit/ref.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Sequence


DEFAULT_PATHS = [
    "enoch_control_plane",
    "deploy",
    "scripts",
    "pyproject.toml",
    "uv.lock",
    "VERSION",
]

EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "artifacts",
    "enoch_control_plane.egg-info",
    "node_modules",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_rev_parse(repo: Path, ref: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", ref],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout.strip()


def _git_status_porcelain(repo: Path) -> str:
    return subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout.strip()


def _iter_relative_files(root: Path, selected_paths: Sequence[str]) -> list[str]:
    files: set[str] = set()
    for raw in selected_paths:
        rel = Path(raw)
        if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
            raise ValueError(f"unsafe relative path: {raw}")
        candidate = root / rel
        if candidate.is_file():
            files.add(rel.as_posix())
            continue
        if candidate.is_dir():
            for path in candidate.rglob("*"):
                if not path.is_file():
                    continue
                file_rel = path.relative_to(root)
                if any(part in EXCLUDED_PARTS for part in file_rel.parts):
                    continue
                if path.suffix in EXCLUDED_SUFFIXES:
                    continue
                files.add(file_rel.as_posix())
            continue
        files.add(rel.as_posix())
    return sorted(files)


def _validate_expected_commit(
    source: Path, expected_commit: str
) -> tuple[str, str, list[str]]:
    failures: list[str] = []
    try:
        source_commit = _git_rev_parse(source, "HEAD")
        resolved_expected_commit = _git_rev_parse(source, expected_commit)
        dirty_status = _git_status_porcelain(source)
    except (OSError, subprocess.CalledProcessError) as exc:
        failures.append(f"git commit check failed: {type(exc).__name__}: {exc}")
        return "", "", failures

    if source_commit != resolved_expected_commit:
        failures.append(
            "source commit drift: HEAD "
            f"{source_commit} != {expected_commit} {resolved_expected_commit}"
        )
    if dirty_status:
        failures.append("source checkout is dirty")
    return source_commit, resolved_expected_commit, failures


def _validate_deploy_file(
    source: Path, runtime: Path, rel: str
) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    source_path = source / rel
    runtime_path = runtime / rel
    if not source_path.exists():
        failures.append(f"missing source file: {rel}")
        return {"path": rel, "ok": False, "reason": "missing_source"}, failures
    if not runtime_path.exists():
        failures.append(f"missing runtime file: {rel}")
        return (
            {
                "path": rel,
                "ok": False,
                "reason": "missing_runtime",
                "source_sha256": _sha256(source_path),
            },
            failures,
        )
    if not runtime_path.is_file():
        failures.append(f"runtime path is not a file: {rel}")
        return {"path": rel, "ok": False, "reason": "runtime_not_file"}, failures

    source_hash = _sha256(source_path)
    runtime_hash = _sha256(runtime_path)
    ok = source_hash == runtime_hash
    if not ok:
        failures.append(f"hash drift: {rel}")
    return (
        {
            "path": rel,
            "ok": ok,
            "source_sha256": source_hash,
            "runtime_sha256": runtime_hash,
        },
        failures,
    )


def validate_runtime(
    *,
    source: Path,
    runtime: Path,
    paths: Sequence[str] | None = None,
    expected_commit: str = "",
) -> dict[str, Any]:
    source = source.expanduser().resolve()
    runtime = runtime.expanduser().resolve()
    selected_paths = list(paths or DEFAULT_PATHS)
    failures: list[str] = []
    files: list[dict[str, Any]] = []
    source_commit = ""
    resolved_expected_commit = ""

    if expected_commit:
        source_commit, resolved_expected_commit, commit_failures = (
            _validate_expected_commit(source, expected_commit)
        )
        failures.extend(commit_failures)

    try:
        relative_files = _iter_relative_files(source, selected_paths)
    except ValueError as exc:
        relative_files = []
        failures.append(str(exc))

    for rel in relative_files:
        entry, file_failures = _validate_deploy_file(source, runtime, rel)
        files.append(entry)
        failures.extend(file_failures)

    return {
        "ok": not failures,
        "source": str(source),
        "runtime": str(runtime),
        "expected_commit": resolved_expected_commit or expected_commit,
        "source_commit": source_commit,
        "checked_paths": selected_paths,
        "file_count": len(files),
        "files": files,
        "failures": failures,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", default="/opt/enoch-release/enoch-agentic-research-system"
    )
    parser.add_argument("--runtime", default="/opt/enoch-control-plane")
    parser.add_argument(
        "--expected-commit",
        default="",
        help="Optional git ref or SHA that source HEAD must match.",
    )
    parser.add_argument(
        "--path",
        action="append",
        dest="paths",
        help="Relative path to verify. May be repeated.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Omit per-file rows from JSON output.",
    )
    args = parser.parse_args(argv)

    report = validate_runtime(
        source=Path(args.source),
        runtime=Path(args.runtime),
        paths=args.paths,
        expected_commit=args.expected_commit,
    )
    if args.summary_only:
        report = {key: value for key, value in report.items() if key != "files"}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
