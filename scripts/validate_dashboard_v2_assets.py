#!/usr/bin/env python3
"""Validate committed Dashboard V2 assets match a fresh dashboard build.

Dashboard source lives in ``dashboard/``. Built static files are committed under
``enoch_control_plane/control_plane/dashboard_v2/`` and served by the control
plane. This script rebuilds into a temporary output directory and compares
SHA-256 hashes so source changes cannot merge without a matching asset rebuild.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

DASHBOARD_REL = Path("dashboard")
DASHBOARD_V2_REL = Path("enoch_control_plane/control_plane/dashboard_v2")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_tree_hashes(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    if not root.is_dir():
        raise ValueError(f"expected directory: {root}")

    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        hashes[rel] = _sha256(path)
    return hashes


def compare_asset_trees(*, committed_root: Path, built_root: Path) -> dict[str, Any]:
    committed_hashes = collect_tree_hashes(committed_root)
    built_hashes = collect_tree_hashes(built_root)
    failures: list[str] = []

    if not committed_hashes:
        failures.append(f"missing committed assets under {committed_root}")

    all_paths = sorted(set(committed_hashes) | set(built_hashes))
    files: list[dict[str, Any]] = []
    for rel in all_paths:
        committed_hash = committed_hashes.get(rel)
        built_hash = built_hashes.get(rel)
        if committed_hash is None:
            failures.append(f"unexpected built file: {rel}")
            files.append({"path": rel, "ok": False, "reason": "unexpected_built"})
            continue
        if built_hash is None:
            failures.append(f"missing built file: {rel}")
            files.append(
                {
                    "path": rel,
                    "ok": False,
                    "reason": "missing_built",
                    "committed_sha256": committed_hash,
                }
            )
            continue
        ok = committed_hash == built_hash
        if not ok:
            failures.append(f"hash drift: {rel}")
        files.append(
            {
                "path": rel,
                "ok": ok,
                "committed_sha256": committed_hash,
                "built_sha256": built_hash,
            }
        )

    return {
        "ok": not failures,
        "committed_root": str(committed_root),
        "built_root": str(built_root),
        "file_count": len(all_paths),
        "files": files,
        "failures": failures,
    }


def validate_dashboard_v2_assets(
    *,
    repo_root: Path,
    run_build: bool = True,
    build_out_dir: Path | None = None,
    skip_npm_ci: bool = False,
) -> dict[str, Any]:
    repo_root = repo_root.expanduser().resolve()
    committed_root = repo_root / DASHBOARD_V2_REL

    if not committed_root.is_dir():
        return {
            "ok": False,
            "committed_root": str(committed_root),
            "built_root": "",
            "file_count": 0,
            "files": [],
            "failures": [f"missing committed assets directory: {committed_root}"],
        }

    if not run_build:
        return {
            "ok": True,
            "committed_root": str(committed_root),
            "built_root": "",
            "file_count": len(collect_tree_hashes(committed_root)),
            "files": [],
            "failures": [],
        }

    if build_out_dir is None:
        with tempfile.TemporaryDirectory(prefix="dashboard-v2-build-") as tmp:
            out_dir = Path(tmp)
            _run_build(repo_root, out_dir, skip_npm_ci=skip_npm_ci)
            return compare_asset_trees(
                committed_root=committed_root, built_root=out_dir
            )

    out_dir = build_out_dir.expanduser().resolve()
    _run_build(repo_root, out_dir, skip_npm_ci=skip_npm_ci)
    return compare_asset_trees(committed_root=committed_root, built_root=out_dir)


def _run_build(repo_root: Path, out_dir: Path, *, skip_npm_ci: bool) -> None:
    dashboard_dir = repo_root / DASHBOARD_REL
    if not dashboard_dir.is_dir():
        raise FileNotFoundError(f"missing dashboard source directory: {dashboard_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)
    if not skip_npm_ci:
        subprocess.run(["npm", "ci"], cwd=dashboard_dir, check=True)
    subprocess.run(["npx", "tsc", "-b"], cwd=dashboard_dir, check=True)
    subprocess.run(
        ["npx", "vite", "build", "--outDir", str(out_dir.resolve())],
        cwd=dashboard_dir,
        check=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root containing dashboard/ and committed dashboard_v2/ assets.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip npm build; only inspect committed asset tree (mainly for tests).",
    )
    parser.add_argument(
        "--skip-npm-ci",
        action="store_true",
        help="Skip npm ci before build (use when CI already installed dashboard deps).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON report on stdout.",
    )
    args = parser.parse_args(argv)

    try:
        report = validate_dashboard_v2_assets(
            repo_root=args.repo_root,
            run_build=not args.skip_build,
            skip_npm_ci=args.skip_npm_ci,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        report = {
            "ok": False,
            "committed_root": str((args.repo_root / DASHBOARD_V2_REL).resolve()),
            "built_root": "",
            "file_count": 0,
            "files": [],
            "failures": [f"dashboard build failed: {type(exc).__name__}: {exc}"],
        }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif report["ok"]:
        print(
            "Dashboard V2 asset validation passed "
            f"({report['file_count']} committed file(s) match fresh build)."
        )
    else:
        print("Dashboard V2 asset validation failed:", file=sys.stderr)
        for failure in report["failures"]:
            print(f"- {failure}", file=sys.stderr)
        print(
            "Rebuild with: cd dashboard && npm ci && npm run build, "
            "then commit enoch_control_plane/control_plane/dashboard_v2/.",
            file=sys.stderr,
        )

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
