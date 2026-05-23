#!/usr/bin/env python3
"""Deterministically backfill safe fields for promising-signal export rows.

The script is intentionally conservative: it emits a report and a sanitized
backfilled row set, but it does not mutate Postgres. Recovered values are facts
already present in queue/project metadata, research candidate/source metadata,
or structured project-decision payloads.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
EXPORTER_PATH = SCRIPT_DIR / "export_promising_signals.py"
spec = importlib.util.spec_from_file_location("export_promising_signals", EXPORTER_PATH)
assert spec and spec.loader
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


def _load_rows(
    input_json: Path | None, project_ids: list[str], query: str
) -> list[dict[str, Any]]:
    if input_json:
        rows = json.loads(input_json.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise SystemExit("--input-json must contain a JSON list")
        return rows
    return exporter._fetch_postgres_rows(project_ids, query)


def _sanitized_backfilled_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clean_rows = exporter.clean_export_rows(rows)
    sanitized: list[dict[str, Any]] = []
    for row in clean_rows:
        copied = dict(row)
        if "artifact_root" in copied:
            copied["artifact_root"] = exporter._safe_path_text(
                copied.get("artifact_root")
            )
        if "artifact_paths" in copied:
            copied["artifact_paths"] = [
                exporter._safe_path_text(item)
                for item in exporter._list(copied.get("artifact_paths"))
            ]
        copied = json.loads(json.dumps(copied, default=str))
        sanitized.append(copied)
    sanitized.sort(
        key=lambda item: (
            str(item.get("project_id") or ""),
            str(item.get("run_id") or item.get("current_run_id") or ""),
        )
    )
    return sanitized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-json",
        type=Path,
        help="JSON array of control-plane rows for offline/deterministic backfill",
    )
    parser.add_argument("--project-id", action="append", default=[])
    parser.add_argument("--query", default="")
    parser.add_argument("--report-json", required=True, type=Path)
    parser.add_argument("--report-markdown", type=Path)
    parser.add_argument("--backfilled-rows-json", type=Path)
    parser.add_argument(
        "--output-repo",
        type=Path,
        help="Optional promising-signals repo to rewrite from the clean backfilled row set",
    )
    args = parser.parse_args(argv)

    rows = _load_rows(args.input_json, args.project_id, args.query)
    report = exporter.audit_backfill(rows)

    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if args.report_markdown:
        args.report_markdown.parent.mkdir(parents=True, exist_ok=True)
        args.report_markdown.write_text(
            exporter.audit_backfill_markdown(report) + "\n", encoding="utf-8"
        )
    if args.backfilled_rows_json:
        args.backfilled_rows_json.parent.mkdir(parents=True, exist_ok=True)
        args.backfilled_rows_json.write_text(
            json.dumps(_sanitized_backfilled_rows(rows), indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    if args.output_repo:
        exporter.write_export(exporter.clean_export_rows(rows), args.output_repo)

    print(json.dumps({"ok": True, **report["summary"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
