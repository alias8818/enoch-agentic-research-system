#!/usr/bin/env python3
"""Validate Research Facility source provenance in Postgres.

This validator is intentionally read-only.  It verifies that Research Facility
candidates and follow-up projects have deterministic ``research_sources`` and
``research_lineage`` rows.  It does not infer provenance from historical Notion
rows, titles, or fuzzy matches; missing source truth must be repaired by the
creation path that owns the row.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from datetime import UTC, datetime
from typing import Any

CANDIDATE_SQL = """
select candidate_id, title, generation_mode, source_ids, source_urls, created_at
from enoch.research_candidates
where (%(created_after)s::timestamptz is null or created_at >= %(created_after)s::timestamptz)
order by created_at asc, candidate_id asc
"""

FOLLOWUP_SQL = """
select idea_id, title, source_external_url, source_payload_json, created_at
from enoch.ideas
where source_kind = 'followup_branch'
  and (%(created_after)s::timestamptz is null or created_at >= %(created_after)s::timestamptz)
order by created_at asc, idea_id asc
"""

SOURCE_SQL = """
select source_id, source_kind, title, url, external_id, created_at
from enoch.research_sources
order by created_at asc, source_id asc
"""

LINEAGE_SQL = """
select source_type, source_id, target_type, target_id, relation_type, created_at
from enoch.research_lineage
order by created_at asc, lineage_id asc
"""


@dataclass(frozen=True)
class SourceLineageSnapshot:
    candidates: list[dict[str, Any]]
    followups: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    lineages: list[dict[str, Any]]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return []
        return decoded if isinstance(decoded, list) else []
    return []


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _dict_rows(rows: Iterable[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, Mapping):
            out.append(dict(row))
            continue
        if hasattr(row, "keys"):
            out.append({key: row[key] for key in row.keys()})
            continue
        raise TypeError(f"expected dict-like database row, got {type(row).__name__}")
    return out


def source_id_for_url(url: str) -> str:
    clean = _text(url)
    return f"url-{hashlib.sha256(clean.encode('utf-8')).hexdigest()[:24]}"


def followup_parent_source_id(parent_project_id: str, parent_run_id: str) -> str:
    seed = f"followup-parent-run:{_text(parent_project_id)}:{_text(parent_run_id) or 'latest'}"
    return f"followup-parent-run-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"


def _source_indexes(sources: Sequence[dict[str, Any]]) -> tuple[set[str], dict[str, str]]:
    ids: set[str] = set()
    urls: dict[str, str] = {}
    for source in sources:
        source_id = _text(source.get("source_id"))
        if source_id:
            ids.add(source_id)
        url = _text(source.get("url"))
        if url and source_id:
            urls[url] = source_id
    return ids, urls


def _lineage_keys(lineages: Sequence[dict[str, Any]]) -> set[tuple[str, str, str, str, str]]:
    return {
        (
            _text(row.get("source_type")),
            _text(row.get("source_id")),
            _text(row.get("target_type")),
            _text(row.get("target_id")),
            _text(row.get("relation_type")),
        )
        for row in lineages
    }


def _source_id_candidates_for_url(url: str, source_by_url: Mapping[str, str]) -> list[str]:
    candidates = []
    clean = _text(url)
    if source_by_url.get(clean):
        candidates.append(source_by_url[clean])
    deterministic = source_id_for_url(clean)
    if deterministic not in candidates:
        candidates.append(deterministic)
    return candidates


def validate_snapshot(snapshot: SourceLineageSnapshot) -> list[dict[str, Any]]:
    """Return deterministic source-lineage problems for a fetched snapshot."""

    problems: list[dict[str, Any]] = []
    source_ids, source_by_url = _source_indexes(snapshot.sources)
    lineage = _lineage_keys(snapshot.lineages)

    for candidate in snapshot.candidates:
        candidate_id = _text(candidate.get("candidate_id"))
        title = _text(candidate.get("title"))
        explicit_source_ids = [_text(item) for item in _json_list(candidate.get("source_ids")) if _text(item)]
        source_urls = [_text(item) for item in _json_list(candidate.get("source_urls")) if _text(item)]
        expected_ids: list[tuple[str, str]] = [(source_id, "source_ids") for source_id in explicit_source_ids]
        for url in source_urls:
            url_candidates = _source_id_candidates_for_url(url, source_by_url)
            existing = next((source_id for source_id in url_candidates if source_id in source_ids), "")
            if not existing:
                problems.append(
                    {
                        "kind": "candidate_source_url_missing_source",
                        "candidate_id": candidate_id,
                        "title": title,
                        "source_url": url,
                        "expected_source_id": source_id_for_url(url),
                    }
                )
            else:
                expected_ids.append((existing, "source_urls"))

        for source_id, origin in sorted(set(expected_ids)):
            if source_id not in source_ids:
                problems.append(
                    {
                        "kind": "candidate_source_id_missing_source",
                        "candidate_id": candidate_id,
                        "title": title,
                        "source_id": source_id,
                        "origin": origin,
                    }
                )
                continue
            if ("source", source_id, "candidate", candidate_id, "generated_from") not in lineage:
                problems.append(
                    {
                        "kind": "candidate_source_missing_lineage",
                        "candidate_id": candidate_id,
                        "title": title,
                        "source_id": source_id,
                        "origin": origin,
                    }
                )

    for followup in snapshot.followups:
        project_id = _text(followup.get("idea_id"))
        title = _text(followup.get("title"))
        payload = _json_dict(followup.get("source_payload_json"))
        parent_project_id = _text(payload.get("parent_project_id"))
        parent_run_id = _text(payload.get("parent_run_id"))
        parent_source_id = followup_parent_source_id(parent_project_id, parent_run_id)
        source_url = _text(followup.get("source_external_url"))

        if not parent_project_id:
            problems.append(
                {
                    "kind": "followup_missing_parent_project_id",
                    "project_id": project_id,
                    "title": title,
                }
            )
        if parent_source_id not in source_ids:
            problems.append(
                {
                    "kind": "followup_missing_parent_run_source",
                    "project_id": project_id,
                    "title": title,
                    "parent_project_id": parent_project_id,
                    "parent_run_id": parent_run_id,
                    "expected_source_id": parent_source_id,
                    "source_url": source_url,
                }
            )
        elif ("source", parent_source_id, "candidate", project_id, "generated_from") not in lineage:
            problems.append(
                {
                    "kind": "followup_missing_parent_run_lineage",
                    "project_id": project_id,
                    "title": title,
                    "parent_project_id": parent_project_id,
                    "parent_run_id": parent_run_id,
                    "source_id": parent_source_id,
                }
            )
        if parent_project_id and ("project", parent_project_id, "project", project_id, "followup_parent") not in lineage:
            problems.append(
                {
                    "kind": "followup_missing_parent_project_lineage",
                    "project_id": project_id,
                    "title": title,
                    "parent_project_id": parent_project_id,
                    "parent_run_id": parent_run_id,
                }
            )
    return problems


def build_report(snapshot: SourceLineageSnapshot, *, created_after: str = "") -> dict[str, Any]:
    problems = validate_snapshot(snapshot)
    by_kind: dict[str, int] = {}
    for problem in problems:
        by_kind[problem["kind"]] = by_kind.get(problem["kind"], 0) + 1
    status = "blocked" if problems else "clean"
    return {
        "schema_version": "enoch_source_lineage_report_v1",
        "ok": not problems,
        "status": status,
        "created_after": created_after,
        "checked_at": datetime.now(UTC).isoformat(),
        "counts": {
            "candidates": len(snapshot.candidates),
            "followups": len(snapshot.followups),
            "sources": len(snapshot.sources),
            "lineages": len(snapshot.lineages),
            "problems": len(problems),
        },
        "problem_counts": dict(sorted(by_kind.items())),
        "problems": problems,
    }


def fetch_snapshot(database_url: str, *, created_after: str = "") -> SourceLineageSnapshot:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover - environment problem
        raise SystemExit("psycopg is required; install project dependencies first") from exc

    params = {"created_after": created_after or None}
    def run_query(conn: Any, sql: str) -> list[dict[str, Any]]:
        query_params = params if "%(created_after)s" in sql else None
        return _dict_rows(conn.execute(sql, query_params).fetchall())

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        return SourceLineageSnapshot(
            candidates=run_query(conn, CANDIDATE_SQL),
            followups=run_query(conn, FOLLOWUP_SQL),
            sources=run_query(conn, SOURCE_SQL),
            lineages=run_query(conn, LINEAGE_SQL),
        )


def write_report(report: Mapping[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    tmp.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


def _print_human(report: Mapping[str, Any], *, max_rows: int) -> None:
    counts = report["counts"]
    print(
        "source lineage validator:",
        "PASS" if report["ok"] else "FAIL",
        json.dumps(counts, sort_keys=True),
    )
    problem_counts = report.get("problem_counts") or {}
    if problem_counts:
        print("problem counts:", json.dumps(problem_counts, sort_keys=True))
    for problem in list(report.get("problems") or [])[:max_rows]:
        print("-", json.dumps(problem, sort_keys=True))
    remaining = int(counts.get("problems") or 0) - max_rows
    if remaining > 0:
        print(f"... {remaining} additional problem(s) omitted")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Research Facility source/lineage provenance in Postgres.")
    parser.add_argument("--database-url", default=os.environ.get("ENOCH_SOURCE_LINEAGE_DATABASE_URL") or os.environ.get("ENOCH_SUPABASE_DATABASE_URL") or os.environ.get("DATABASE_URL") or "", help="Postgres URL. Defaults to ENOCH_SOURCE_LINEAGE_DATABASE_URL, ENOCH_SUPABASE_DATABASE_URL, or DATABASE_URL.")
    parser.add_argument("--created-after", default=os.environ.get("ENOCH_SOURCE_LINEAGE_CREATED_AFTER", ""), help="Only require rows created at or after this timestamptz. Useful while historical gaps remain documented.")
    parser.add_argument("--json", action="store_true", help="Print the full report as JSON.")
    parser.add_argument("--output", default="", help="Optional path to write the JSON report.")
    parser.add_argument("--max-problems", type=int, default=0, help="Allowed problem count before failing. Defaults to 0.")
    parser.add_argument("--show-problems", type=int, default=25, help="Max problem rows to print in human output.")
    args = parser.parse_args(argv)

    if not args.database_url:
        raise SystemExit("database URL required via --database-url or ENOCH_SOURCE_LINEAGE_DATABASE_URL/ENOCH_SUPABASE_DATABASE_URL/DATABASE_URL")
    snapshot = fetch_snapshot(args.database_url, created_after=args.created_after)
    report = build_report(snapshot, created_after=args.created_after)
    if args.output:
        write_report(report, args.output)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        _print_human(report, max_rows=max(0, args.show_problems))
    return 0 if int(report["counts"]["problems"]) <= args.max_problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
