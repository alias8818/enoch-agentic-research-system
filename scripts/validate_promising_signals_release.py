#!/usr/bin/env python3
"""Validate enoch-promising-signals as data without executing its scripts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

try:
    from validate_public_release import check_public_secret_tokens
except ModuleNotFoundError:
    from scripts.validate_public_release import check_public_secret_tokens


PUBLIC_SIGNAL_PATHS = (
    "README.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "data/manifest.json",
    "data/ranking.json",
    "data/signals.jsonl",
    "docs/export-policy.md",
    "schemas/promising-signal.schema.json",
    "signals/index.md",
)


def _fail(message: str, failures: list[str]) -> None:
    failures.append(message)


def _load_json(path: Path, failures: list[str]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"invalid JSON {path}: {type(exc).__name__}: {exc}", failures)
        return None


def _check_required_paths(root: Path, failures: list[str]) -> list[Path]:
    paths: list[Path] = []
    for rel in PUBLIC_SIGNAL_PATHS:
        path = root / rel
        if not path.is_file():
            _fail(f"missing promising-signals public file: {rel}", failures)
            continue
        paths.append(path)
    return paths


def _check_jsonl(path: Path, failures: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        _fail(f"unreadable promising-signals JSONL {path}: {exc}", failures)
        return rows
    if not lines:
        _fail(f"empty promising-signals JSONL: {path}", failures)
        return rows
    for index, line in enumerate(lines, start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            _fail(f"invalid JSONL row {path}:{index}: {exc}", failures)
            continue
        if not isinstance(row, dict):
            _fail(f"JSONL row is not an object {path}:{index}", failures)
            continue
        rows.append(row)
    return rows


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _check_manifest_paths(
    root: Path, manifest: dict[str, Any], failures: list[str]
) -> list[Path]:
    paths: list[Path] = []
    for key in ("data_file", "ranking_file", "schema_file", "index_file", "ranked_index_file"):
        rel = _as_text(manifest.get(key))
        if not rel:
            _fail(f"promising-signals manifest {key} must be set", failures)
            continue
        path = root / rel
        if not path.is_file():
            _fail(f"missing promising-signals manifest file {key}: {rel}", failures)
            continue
        paths.append(path)
    return paths


def _check_manifest(
    root: Path, manifest: Any, signal_rows: list[dict[str, Any]], failures: list[str]
) -> list[Path]:
    if not isinstance(manifest, dict):
        _fail("promising-signals manifest must be an object", failures)
        return []
    manifest_paths = _check_manifest_paths(root, manifest, failures)
    if manifest.get("data_file") != "data/signals.jsonl":
        _fail("promising-signals manifest data_file must be data/signals.jsonl", failures)
    project_ids = manifest.get("project_ids")
    if not isinstance(project_ids, list) or not project_ids:
        _fail("promising-signals manifest project_ids must be a non-empty list", failures)
        return
    row_project_ids = {_as_text(row.get("project_id")) for row in signal_rows}
    missing_rows = sorted(_as_text(project_id) for project_id in project_ids if _as_text(project_id) not in row_project_ids)
    if missing_rows:
        _fail(f"manifest project_ids missing from signals.jsonl: {missing_rows[:5]}", failures)
    missing_markdown = [
        project_id for project_id in project_ids if not list((root / "signals").glob(f"{project_id}.md"))
    ]
    if missing_markdown:
        _fail(f"manifest project_ids missing signal markdown: {missing_markdown[:5]}", failures)
    return manifest_paths


def _check_ranking(ranking: Any, signal_rows: list[dict[str, Any]], failures: list[str]) -> None:
    if not isinstance(ranking, dict):
        _fail("promising-signals ranking must be an object", failures)
        return
    items = ranking.get("items")
    if not isinstance(items, list) or not items:
        _fail("promising-signals ranking items must be a non-empty list", failures)
        return
    row_project_ids = {_as_text(row.get("project_id")) for row in signal_rows}
    missing_rows = sorted(
        _as_text(item.get("project_id"))
        for item in items
        if isinstance(item, dict) and _as_text(item.get("project_id")) not in row_project_ids
    )
    if missing_rows:
        _fail(f"ranking project_ids missing from signals.jsonl: {missing_rows[:5]}", failures)


def validate_promising_signals(root: Path) -> dict[str, Any]:
    root = root.expanduser().resolve()
    failures: list[str] = []
    public_paths = _check_required_paths(root, failures)
    manifest = _load_json(root / "data" / "manifest.json", failures)
    ranking = _load_json(root / "data" / "ranking.json", failures)
    signal_rows = _check_jsonl(root / "data" / "signals.jsonl", failures)
    manifest_paths = _check_manifest(root, manifest, signal_rows, failures)
    _check_ranking(ranking, signal_rows, failures)
    public_scan_paths = sorted({*public_paths, *manifest_paths, *sorted((root / "signals").glob("*.md"))})
    check_public_secret_tokens(public_scan_paths, failures)
    return {
        "ok": not failures,
        "promising_root": str(root),
        "signal_count": len(signal_rows),
        "checked_public_paths": len(public_paths),
        "failures": failures,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--promising", required=True, help="Path to enoch-promising-signals checkout")
    args = parser.parse_args(argv)
    report = validate_promising_signals(Path(args.promising))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
