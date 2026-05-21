#!/usr/bin/env python3
"""Fail fast when dashboard source changes without committed asset updates.

Dashboard V2 ships source in ``dashboard/`` and committed static bundles in
``enoch_control_plane/control_plane/dashboard_v2/``. CI rebuilds source and
compares hashes; this check catches the common agent mistake earlier with a
clear remediation message.

See docs/dashboard-v2-asset-clca.md.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import PurePosixPath

ASSET_PREFIX = "enoch_control_plane/control_plane/dashboard_v2/"
BUILD_AFFECTING_PREFIXES = (
    "dashboard/src/",
    "dashboard/index.html",
    "dashboard/package.json",
    "dashboard/package-lock.json",
    "dashboard/vite.config.ts",
)
BUILD_AFFECTING_NAMES = (
    "dashboard/tsconfig.json",
    "dashboard/tsconfig.app.json",
    "dashboard/tsconfig.node.json",
)
NON_BUILD_SUFFIXES = (
    ".test.ts",
    ".test.tsx",
    ".spec.ts",
)
NON_BUILD_PATH_PARTS = (
    "dashboard/test-results/",
    "dashboard/playwright-report/",
    "dashboard/e2e/",
)


def _git_changed_files(base_ref: str) -> list[str]:
    for spec in (f"{base_ref}...HEAD", f"{base_ref}..HEAD"):
        result = subprocess.run(
            ["git", "diff", "--name-only", spec],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    raise subprocess.CalledProcessError(
        1,
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        result.stderr or f"unable to diff against base ref {base_ref}",
    )


def affects_build_output(path: str) -> bool:
    normalized = PurePosixPath(path.replace("\\", "/")).as_posix()
    if normalized.startswith(ASSET_PREFIX):
        return False
    if any(part in normalized for part in NON_BUILD_PATH_PARTS):
        return False
    if normalized.endswith(NON_BUILD_SUFFIXES):
        return False
    if normalized in BUILD_AFFECTING_NAMES:
        return True
    if normalized.startswith("dashboard/tsconfig."):
        return True
    return any(normalized.startswith(prefix) for prefix in BUILD_AFFECTING_PREFIXES)


def affects_committed_assets(path: str) -> bool:
    return PurePosixPath(path.replace("\\", "/")).as_posix().startswith(ASSET_PREFIX)


def evaluate_pairing(changed_files: list[str]) -> dict[str, object]:
    source_changed = sorted({path for path in changed_files if affects_build_output(path)})
    asset_changed = sorted({path for path in changed_files if affects_committed_assets(path)})
    ok = not source_changed or bool(asset_changed)
    return {
        "ok": ok,
        "source_changed": source_changed,
        "asset_changed": asset_changed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default="origin/main",
        help="Git ref to diff against (default: origin/main).",
    )
    parser.add_argument(
        "--changed-file",
        action="append",
        default=[],
        help="Explicit changed path for tests (repeatable). Skips git diff when set.",
    )
    args = parser.parse_args(argv)

    changed = args.changed_file or _git_changed_files(args.base)
    report = evaluate_pairing(changed)

    if report["ok"]:
        if report["source_changed"]:
            print(
                "Dashboard V2 source/asset pairing OK "
                f"({len(report['source_changed'])} source file(s), "
                f"{len(report['asset_changed'])} asset file(s) changed)."
            )
        else:
            print("Dashboard V2 source/asset pairing OK (no build-affecting dashboard source changes).")
        return 0

    print("Dashboard V2 source/asset pairing FAILED:", file=sys.stderr)
    print(
        "Build-affecting dashboard source changed without committed dashboard_v2 assets.",
        file=sys.stderr,
    )
    for path in report["source_changed"]:
        print(f"- source: {path}", file=sys.stderr)
    print(
        "\nRebuild and commit committed assets:\n"
        "  ./scripts/rebuild_dashboard_v2_assets.sh\n"
        "See docs/dashboard-v2-asset-clca.md",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
