#!/usr/bin/env python3
"""Dry-run-first storage maintenance for Enoch worker project directories.

The script only deletes reproducible local build/runtime clutter by default:
project .venv directories and Python/tool cache directories. It intentionally
leaves scientific artifacts, models, results, evidence bundles, and ledgers
untouched.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_PROJECT_ROOT = Path.home() / "projects/enoch_testing_ground/projects"
RECREATABLE_DIR_NAMES = frozenset(
    {
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".hypothesis",
        "node_modules",
    }
)
HIGH_VALUE_NAMES = frozenset(
    {
        ".enoch",
        ".omx",
        "papers",
        "evidence",
        "evidence_bundle.json",
        "claim_ledger.json",
        "project_decision.json",
        "run_notes.md",
        "metrics.json",
        "models",
        "artifacts",
        "results",
        "runs",
        "data",
        "datasets",
        "external",
    }
)


@dataclass(frozen=True)
class CleanupCandidate:
    path: Path
    reason: str
    size_bytes: int
    protected: bool = False
    protect_reason: str = ""


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def directory_size_bytes(path: Path) -> int:
    """Return allocated bytes for a directory tree, not apparent size.

    Worker environments use package-manager caches and hardlink-heavy Python
    environments. Apparent size can materially overstate disk pressure, so use
    POSIX allocated blocks when available.
    """
    total = 0
    seen: set[tuple[int, int]] = set()
    for child in path.rglob("*"):
        try:
            if child.is_symlink() or not child.is_file():
                continue
            stat = child.stat()
            inode = (stat.st_dev, stat.st_ino)
            if inode in seen:
                continue
            seen.add(inode)
            blocks = getattr(stat, "st_blocks", 0)
            total += int(blocks) * 512 if blocks else stat.st_size
        except OSError:
            continue
    return total


def unique_allocated_bytes(candidates: Iterable[CleanupCandidate]) -> int:
    """Return allocated bytes across candidates without double-counting hardlinks."""
    total = 0
    seen: set[tuple[int, int]] = set()
    for candidate in candidates:
        for child in candidate.path.rglob("*"):
            try:
                if child.is_symlink() or not child.is_file():
                    continue
                stat = child.stat()
                inode = (stat.st_dev, stat.st_ino)
                if inode in seen:
                    continue
                seen.add(inode)
                blocks = getattr(stat, "st_blocks", 0)
                total += int(blocks) * 512 if blocks else stat.st_size
            except OSError:
                continue
    return total


def human_bytes(size: int) -> str:
    value = float(size)
    for suffix in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or suffix == "TiB":
            return f"{value:.1f} {suffix}" if suffix != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def load_protected_projects(paths: Iterable[Path], explicit: Iterable[str]) -> set[str]:
    protected = {item.strip() for item in explicit if item.strip()}
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            protected.add(line)
    return protected


def _project_name_for(path: Path, project_root: Path) -> str:
    try:
        return path.relative_to(project_root).parts[0]
    except (ValueError, IndexError):
        return ""


def discover_candidates(
    project_root: Path,
    *,
    protected_projects: set[str] | None = None,
    include_node_modules: bool = False,
) -> list[CleanupCandidate]:
    root = project_root.expanduser().resolve(strict=True)
    protected_projects = protected_projects or set()
    candidates: list[CleanupCandidate] = []
    names = set(RECREATABLE_DIR_NAMES)
    if not include_node_modules:
        names.discard("node_modules")

    for current, dirnames, _filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        pruned: list[str] = []
        for dirname in list(dirnames):
            child = current_path / dirname
            if child.is_symlink():
                continue
            if not _is_relative_to(child.resolve(strict=False), root):
                continue
            if dirname in names:
                project = _project_name_for(child, root)
                protected = project in protected_projects
                candidates.append(
                    CleanupCandidate(
                        path=child,
                        reason=f"recreatable {dirname} directory",
                        size_bytes=directory_size_bytes(child),
                        protected=protected,
                        protect_reason=f"project {project} is protected"
                        if protected
                        else "",
                    )
                )
                # Critical: do not descend into a candidate. Its size already
                # includes descendants, and selecting nested caches would
                # double-count and risk repeated deletion attempts.
                continue
            if dirname in HIGH_VALUE_NAMES:
                continue
            pruned.append(dirname)
        dirnames[:] = pruned
    return sorted(candidates, key=lambda item: item.size_bytes, reverse=True)


def apply_candidates(candidates: Iterable[CleanupCandidate]) -> tuple[int, int]:
    removed = 0
    bytes_removed = 0
    for candidate in candidates:
        if candidate.protected:
            continue
        shutil.rmtree(candidate.path)
        removed += 1
        bytes_removed += candidate.size_bytes
    return removed, bytes_removed


def build_report(candidates: list[CleanupCandidate]) -> dict[str, object]:
    deletable = [item for item in candidates if not item.protected]
    protected = [item for item in candidates if item.protected]
    by_name: dict[str, dict[str, object]] = {}
    for item in candidates:
        bucket = by_name.setdefault(
            item.path.name, {"count": 0, "candidate_bytes_upper_bound": 0}
        )
        bucket["count"] = int(bucket["count"]) + 1
        bucket["candidate_bytes_upper_bound"] = (
            int(bucket["candidate_bytes_upper_bound"]) + item.size_bytes
        )

    return {
        "candidate_count": len(candidates),
        "deletable_count": len(deletable),
        "protected_count": len(protected),
        "deletable_bytes": unique_allocated_bytes(deletable),
        "protected_bytes": unique_allocated_bytes(protected),
        "deletable_candidate_bytes_upper_bound": sum(
            item.size_bytes for item in deletable
        ),
        "protected_candidate_bytes_upper_bound": sum(
            item.size_bytes for item in protected
        ),
        "by_name": by_name,
        "top": [
            {
                "path": str(item.path),
                "reason": item.reason,
                "size_bytes": item.size_bytes,
                "size": human_bytes(item.size_bytes),
                "protected": item.protected,
                "protect_reason": item.protect_reason,
            }
            for item in candidates[:50]
        ],
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument(
        "--apply", action="store_true", help="delete candidates; default is dry-run"
    )
    parser.add_argument("--include-node-modules", action="store_true")
    parser.add_argument("--protect-project", action="append", default=[])
    parser.add_argument("--protect-file", action="append", type=Path, default=[])
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable report"
    )
    parser.add_argument(
        "--min-free-gib",
        type=float,
        default=0.0,
        help="with --apply, skip cleanup if filesystem already has this much free space",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    root = args.project_root.expanduser().resolve(strict=True)
    protected = load_protected_projects(args.protect_file, args.protect_project)
    candidates = discover_candidates(
        root,
        protected_projects=protected,
        include_node_modules=args.include_node_modules,
    )
    report = build_report(candidates)
    if args.apply and args.min_free_gib > 0:
        free_gib = shutil.disk_usage(root).free / (1024**3)
        if free_gib >= args.min_free_gib:
            report["skipped"] = (
                f"free space {free_gib:.1f} GiB >= threshold {args.min_free_gib:.1f} GiB"
            )
            args.apply = False
    if args.apply:
        removed, bytes_removed = apply_candidates(candidates)
        report["applied"] = True
        report["removed_count"] = removed
        report["removed_bytes"] = bytes_removed
    else:
        report["applied"] = False
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        mode = "APPLY" if report["applied"] else "DRY RUN"
        print(
            f"{mode}: {report['deletable_count']} deletable candidate(s), {human_bytes(int(report['deletable_bytes']))} reclaimable"
        )
        if report.get("protected_count"):
            print(
                f"Protected: {report['protected_count']} candidate(s), {human_bytes(int(report['protected_bytes']))}"
            )
        for item in report["top"][:20]:
            marker = "PROTECTED" if item["protected"] else "delete"
            print(f"{marker:9} {item['size']:>10} {item['path']} — {item['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
