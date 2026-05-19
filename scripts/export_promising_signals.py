#!/usr/bin/env python3
"""Export bounded Enoch useful/promising signals to a companion repo.

This export is intentionally separate from the paper corpus. It preserves
bounded local evidence and scale-limited leads without turning them into papers.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "enoch_promising_signal_v1"
DISCLAIMER = (
    "These are not validated papers, not peer-reviewed results, and not "
    "publication-positive Enoch corpus artifacts. This entry preserves bounded "
    "local evidence that may be useful for larger-compute follow-up."
)
EXPORT_STATUSES = {"useful_signal", "promising_if_scaled", "compute_scale_blocked"}
SOURCE_ROOT = "/var/lib/enoch-control-plane"

PROMISING_SIGNAL_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://github.com/alias8818/enoch-promising-signals/schemas/promising-signal.schema.json",
    "title": "Enoch Promising Signal",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "project_id",
        "run_id",
        "title",
        "status",
        "decision_summary",
        "hypothesis_status",
        "evidence_strength",
        "claim_scope",
        "scale_limits",
        "useful_signal_summary",
        "stop_reason",
        "recommended_next_action",
        "sources",
        "followup",
        "evidence",
        "do_not_overclaim",
    ],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "project_id": {"type": "string", "minLength": 1},
        "run_id": {"type": "string", "minLength": 1},
        "title": {"type": "string", "minLength": 1},
        "status": {"enum": sorted(EXPORT_STATUSES)},
        "decision_summary": {"type": "string", "minLength": 1},
        "hypothesis_status": {"type": "string", "minLength": 1},
        "evidence_strength": {"type": "string", "minLength": 1},
        "claim_scope": {"type": "string", "minLength": 1},
        "scale_limits": {"type": "string", "minLength": 1},
        "useful_signal_summary": {"type": "string", "minLength": 1},
        "stop_reason": {"type": "string", "minLength": 1},
        "recommended_next_action": {"type": "string", "minLength": 1},
        "sources": {"type": "array", "items": {"type": "object"}},
        "followup": {"type": "object"},
        "evidence": {"type": "object"},
        "do_not_overclaim": {"type": "object"},
        "updated_at": {"type": "string"},
    },
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return _text(value).lower() in {"1", "true", "t", "yes", "y", "on"}


def slugify(value: str, fallback: str = "signal") -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-._").lower()
    return (slug or fallback)[:140]


def _safe_path_text(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    return text.replace(SOURCE_ROOT, "<control-plane-state>")


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
        return [text]
    return [value]


def _export_status(row: dict[str, Any]) -> str:
    if _truthy(row.get("compute_scale_blocked")):
        return "compute_scale_blocked"
    outcome = _text(row.get("research_outcome")).lower().replace("-", "_").replace(" ", "_")
    if outcome in {"useful_signal", "promising_if_scaled"}:
        return outcome
    return ""


def is_exportable_row(row: dict[str, Any]) -> bool:
    if _truthy(row.get("write_needed")) or _truthy(row.get("has_live_paper_row")):
        return False
    if _text(row.get("paper_id")) or _text(row.get("paper_status")) or _text(row.get("corpus_imported_at")):
        return False
    return _export_status(row) in EXPORT_STATUSES


def _sources_from_row(row: dict[str, Any]) -> list[dict[str, str]]:
    records = _list(row.get("source_records"))
    sources: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        if isinstance(record, str):
            try:
                parsed = json.loads(record)
            except Exception:
                parsed = None
            record = parsed if isinstance(parsed, dict) else {"source_id": record}
        if not isinstance(record, dict):
            continue
        source = {
            "source_id": _text(record.get("source_id")),
            "url": _text(record.get("url")),
            "title": _text(record.get("title")),
        }
        key = (source["source_id"], source["url"], source["title"])
        if any(source.values()) and key not in seen:
            sources.append(source)
            seen.add(key)
    if sources:
        sources.sort(key=lambda item: (item["source_id"], item["url"], item["title"]))
        return sources

    ids = [_text(item) for item in _list(row.get("source_ids"))]
    urls = [_text(item) for item in _list(row.get("source_urls"))]
    titles = [_text(item) for item in _list(row.get("source_titles"))]
    count = max(len(ids), len(urls), len(titles), 1 if _text(row.get("source_url")) else 0)
    for index in range(count):
        source = {
            "source_id": ids[index] if index < len(ids) else "",
            "url": urls[index] if index < len(urls) else (_text(row.get("source_url")) if index == 0 else ""),
            "title": titles[index] if index < len(titles) else (_text(row.get("source_paper")) if index == 0 else ""),
        }
        if any(source.values()):
            sources.append(source)
    return sources


def signal_from_row(row: dict[str, Any]) -> dict[str, Any]:
    source_paths = [_safe_path_text(item) for item in _list(row.get("artifact_paths")) if _text(item)]
    artifact_root = _safe_path_text(row.get("artifact_root"))
    signal = {
        "schema_version": SCHEMA_VERSION,
        "project_id": _text(row.get("project_id")),
        "run_id": _text(row.get("run_id") or row.get("current_run_id")),
        "title": _text(row.get("project_name") or row.get("title")),
        "status": _export_status(row),
        "decision_summary": _text(row.get("decision_summary")),
        "hypothesis_status": _text(row.get("hypothesis_status")),
        "evidence_strength": _text(row.get("evidence_strength")),
        "claim_scope": _text(row.get("claim_scope")),
        "scale_limits": _text(row.get("scale_limits")),
        "useful_signal_summary": _text(row.get("useful_signal_summary")),
        "stop_reason": _text(row.get("stop_reason")),
        "recommended_next_action": _text(row.get("recommended_next_action")),
        "sources": _sources_from_row(row),
        "followup": {
            "recommended": _truthy(row.get("followup_recommended")),
            "type": _text(row.get("followup_type")),
            "title": _text(row.get("followup_title")),
            "hypothesis": _text(row.get("followup_hypothesis")),
            "required_evidence": [_text(item) for item in _list(row.get("followup_required_evidence")) if _text(item)],
            "success_threshold": _text(row.get("followup_success_threshold")),
            "stop_condition": _text(row.get("followup_stop_condition")),
            "depth": int(row.get("followup_depth") or 0),
        },
        "evidence": {
            "artifact_root": artifact_root,
            "artifact_paths": source_paths,
            "local_only": True,
            "public_evidence_copied": False,
        },
        "do_not_overclaim": {
            "not_a_paper": True,
            "not_peer_reviewed": True,
            "not_publication_validated": True,
            "not_in_main_corpus": True,
            "disclaimer": DISCLAIMER,
        },
        "updated_at": _text(row.get("updated_at")) or datetime.now(timezone.utc).isoformat(),
    }
    return signal


def validate_signal(signal: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for field in PROMISING_SIGNAL_SCHEMA["required"]:
        value = signal.get(field)
        if value in (None, "", [], {}):
            issues.append(f"{field}:required")
    if signal.get("schema_version") != SCHEMA_VERSION:
        issues.append("schema_version:invalid")
    if signal.get("status") not in EXPORT_STATUSES:
        issues.append("status:invalid")
    disclaimer = signal.get("do_not_overclaim") if isinstance(signal.get("do_not_overclaim"), dict) else {}
    for key in ("not_a_paper", "not_publication_validated", "not_in_main_corpus"):
        if disclaimer.get(key) is not True:
            issues.append(f"do_not_overclaim.{key}:required_true")
    if "not validated papers" not in str(disclaimer.get("disclaimer") or ""):
        issues.append("do_not_overclaim.disclaimer:missing_not_validated_papers")
    evidence = signal.get("evidence") if isinstance(signal.get("evidence"), dict) else {}
    if evidence.get("public_evidence_copied") is not False:
        issues.append("evidence.public_evidence_copied:must_be_false")
    if evidence.get("artifact_root") and SOURCE_ROOT in str(evidence.get("artifact_root")):
        issues.append("evidence.artifact_root:private_path_not_redacted")
    return sorted(set(issues))


def export_signals(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    signals = [signal_from_row(row) for row in rows if is_exportable_row(row)]
    signals.sort(key=lambda item: (item["project_id"], item["run_id"]))
    return signals


def _markdown(signal: dict[str, Any]) -> str:
    sources = signal.get("sources") or []
    source_lines = [f"- {src.get('title') or src.get('source_id') or 'source'}: {src.get('url') or src.get('source_id') or ''}" for src in sources]
    followup = signal.get("followup") or {}
    evidence = signal.get("evidence") or {}
    return "\n".join([
        f"# {signal['title']}",
        "",
        f"Status: `{signal['status']}`",
        f"Project ID: `{signal['project_id']}`",
        f"Run ID: `{signal['run_id']}`",
        "",
        "> This is a promising-signal record, not a paper. It is bounded local evidence preserved for possible larger-compute follow-up.",
        "",
        "## Source",
        "",
        *(source_lines or ["- No source URL recorded."]),
        "",
        "## What looked useful",
        "",
        signal["useful_signal_summary"],
        "",
        "## Boundaries and scale limits",
        "",
        signal["scale_limits"],
        "",
        "## Claim scope",
        "",
        signal["claim_scope"],
        "",
        "## Why it stopped",
        "",
        signal["stop_reason"],
        "",
        "## Recommended next action",
        "",
        signal["recommended_next_action"],
        "",
        "## Follow-up",
        "",
        f"- Recommended: `{str(bool(followup.get('recommended'))).lower()}`",
        f"- Type: `{followup.get('type') or ''}`",
        f"- Title: {followup.get('title') or ''}",
        f"- Success threshold: {followup.get('success_threshold') or ''}",
        f"- Stop condition: {followup.get('stop_condition') or ''}",
        "",
        "## Evidence references",
        "",
        f"- Artifact root: `{evidence.get('artifact_root') or ''}`",
        *[f"- `{path}`" for path in evidence.get("artifact_paths") or []],
        "",
        "## Do not overclaim",
        "",
        signal["do_not_overclaim"]["disclaimer"],
        "",
    ])



def _paper_or_corpus_excluded(row: dict[str, Any]) -> bool:
    return (
        _truthy(row.get("write_needed"))
        or _truthy(row.get("has_live_paper_row"))
        or bool(_text(row.get("paper_id")))
        or bool(_text(row.get("paper_status")))
        or bool(_text(row.get("corpus_imported_at")))
    )


def _audit_row_summary(row: dict[str, Any], issues: list[str]) -> dict[str, Any]:
    return {
        "project_id": _text(row.get("project_id")),
        "run_id": _text(row.get("run_id") or row.get("current_run_id")),
        "title": _text(row.get("project_name") or row.get("title")),
        "research_outcome": _text(row.get("research_outcome")),
        "compute_scale_blocked": _truthy(row.get("compute_scale_blocked")),
        "issues": sorted(set(issues)),
    }


def audit_backfill(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = {
        "export_cleanly_now": [],
        "missing_required_evidence_or_fields": [],
        "excluded_paper_or_corpus": [],
        "hard_negative_or_stale": [],
    }
    total = 0
    for row in rows:
        total += 1
        if _paper_or_corpus_excluded(row):
            buckets["excluded_paper_or_corpus"].append(_audit_row_summary(row, ["paper_or_corpus_row"]))
            continue
        status = _export_status(row)
        if status not in EXPORT_STATUSES:
            buckets["hard_negative_or_stale"].append(_audit_row_summary(row, ["research_outcome:not_export_status"]))
            continue
        signal = signal_from_row(row)
        issues = validate_signal(signal)
        if issues:
            buckets["missing_required_evidence_or_fields"].append(_audit_row_summary(row, issues))
            continue
        buckets["export_cleanly_now"].append(_audit_row_summary(row, []))
    for key in buckets:
        buckets[key].sort(key=lambda item: (item.get("project_id") or "", item.get("run_id") or ""))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_candidate_rows": total,
            "export_cleanly_now": len(buckets["export_cleanly_now"]),
            "missing_required_evidence_or_fields": len(buckets["missing_required_evidence_or_fields"]),
            "excluded_paper_or_corpus": len(buckets["excluded_paper_or_corpus"]),
            "hard_negative_or_stale": len(buckets["hard_negative_or_stale"]),
        },
        "buckets": buckets,
    }


def audit_backfill_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    buckets = report.get("buckets") or {}
    labels = [
        ("Export cleanly now", "export_cleanly_now"),
        ("Missing required evidence/fields", "missing_required_evidence_or_fields"),
        ("Excluded because paper/corpus", "excluded_paper_or_corpus"),
        ("Hard negative or stale", "hard_negative_or_stale"),
    ]
    lines = [
        "# Promising signals backfill audit",
        "",
        f"Generated: `{report.get('generated_at') or ''}`",
        "",
        "This is a dry-run classification report. It does not export rows or change the companion repo.",
        "",
        "## Summary",
        "",
        "| Bucket | Count |",
        "|---|---:|",
        f"| Total candidate rows | {summary.get('total_candidate_rows', 0)} |",
    ]
    for label, key in labels:
        lines.append(f"| {label} | {summary.get(key, 0)} |")
    lines.extend([
        "",
        "## Backfill plan",
        "",
        "1. Export rows in `export_cleanly_now` first; they already satisfy the deterministic public record contract.",
        "2. Backfill rows in `missing_required_evidence_or_fields` only after source/evidence fields are recovered from control-plane or worker artifacts.",
        "3. Leave `excluded_paper_or_corpus` out of the promising-signals repo; those belong to the paper/corpus lane.",
        "4. Leave `hard_negative_or_stale` out unless a new deterministic decision record changes their status.",
        "",
    ])
    for label, key in labels:
        rows = buckets.get(key) or []
        lines.extend([f"## {label}", "", "| Project | Outcome | Issues |", "|---|---|---|"])
        if not rows:
            lines.append("| _none_ |  |  |")
        for row in rows:
            project = row.get("project_id") or row.get("title") or "unknown"
            outcome = row.get("research_outcome") or ("compute_scale_blocked" if row.get("compute_scale_blocked") else "")
            issues = ", ".join(row.get("issues") or [])
            lines.append(f"| `{project}` | `{outcome}` | {issues} |")
        lines.append("")
    return "\n".join(lines)

def write_schema(repo_root: Path) -> None:
    schema_dir = repo_root / "schemas"
    schema_dir.mkdir(parents=True, exist_ok=True)
    (schema_dir / "promising-signal.schema.json").write_text(json.dumps(PROMISING_SIGNAL_SCHEMA, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_export(rows: Iterable[dict[str, Any]], repo_root: Path) -> dict[str, Any]:
    signals = export_signals(rows)
    failures = []
    for signal in signals:
        issues = validate_signal(signal)
        if issues:
            failures.append({"project_id": signal.get("project_id"), "issues": issues})
    if failures:
        raise SystemExit(json.dumps({"error": "schema_validation_failed", "failures": failures}, indent=2))
    (repo_root / "data").mkdir(parents=True, exist_ok=True)
    (repo_root / "signals").mkdir(parents=True, exist_ok=True)
    write_schema(repo_root)
    (repo_root / "data" / "signals.jsonl").write_text("".join(json.dumps(signal, sort_keys=True) + "\n" for signal in signals), encoding="utf-8")
    index_lines = [
        "# Promising signal index",
        "",
        "These records are bounded local signals, not papers and not publication-positive claims.",
        "",
        "| Title | Status | Evidence strength | Follow-up |",
        "|---|---|---|---|",
    ]
    for signal in signals:
        slug = slugify(signal["project_id"])
        path = repo_root / "signals" / f"{slug}.md"
        path.write_text(_markdown(signal), encoding="utf-8")
        followup = signal.get("followup") or {}
        index_lines.append(f"| [{signal['title']}]({slug}.md) | `{signal['status']}` | {signal['evidence_strength']} | {followup.get('title') or ''} |")
    (repo_root / "signals" / "index.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    return {"count": len(signals), "signals": [signal["project_id"] for signal in signals]}


def _fetch_postgres_rows(project_ids: list[str], query: str) -> list[dict[str, Any]]:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as exc:  # pragma: no cover - env-specific
        raise SystemExit(f"psycopg is required for live Postgres export: {exc}") from exc
    url = os.environ.get("ENOCH_SUPABASE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("ENOCH_SUPABASE_DATABASE_URL or DATABASE_URL is required")
    where = []
    params: list[Any] = []
    if project_ids:
        where.append("pe.project_id = any(%s)")
        params.append(project_ids)
    if query:
        where.append("(pe.project_id ilike %s or pe.project_name ilike %s)")
        params.extend([f"%{query}%", f"%{query}%"])
    where_sql = " and ".join(where) if where else "true"
    sql = f"""
    select
      pe.project_id, pe.project_name, pe.run_id, pe.decision_summary,
      pe.research_outcome, pe.hypothesis_status, pe.evidence_strength,
      pe.claim_scope, pe.scale_limits, pe.useful_signal_summary,
      pe.recommended_next_action, pe.stop_reason,
      pe.followup_recommended, pe.followup_type, pe.followup_title,
      pe.followup_hypothesis, pe.followup_required_evidence,
      pe.followup_success_threshold, pe.followup_stop_condition,
      pe.followup_depth, pe.bounded_paper_ready, pe.compute_scale_blocked,
      pe.write_needed, pe.has_live_paper_row,
      qi.updated_at, p.paper_id, p.paper_status, ci.imported_at as corpus_imported_at,
      coalesce(array_remove(array_cat(array_agg(distinct rs.source_id), array_agg(distinct parent_rs.source_id)), null), '{{}}') as source_ids,
      coalesce(array_remove(array_cat(array_agg(distinct rs.url), array_agg(distinct parent_rs.url)), null), '{{}}') as source_urls,
      coalesce(array_remove(array_cat(array_agg(distinct rs.title), array_agg(distinct parent_rs.title)), null), '{{}}') as source_titles,
      (
        coalesce(
          jsonb_agg(distinct jsonb_build_object('source_id', rs.source_id, 'url', rs.url, 'title', rs.title))
          filter (where rs.source_id is not null),
          '[]'::jsonb
        ) || coalesce(
          jsonb_agg(distinct jsonb_build_object('source_id', parent_rs.source_id, 'url', parent_rs.url, 'title', parent_rs.title))
          filter (where parent_rs.source_id is not null),
          '[]'::jsonb
        )
      ) as source_records,
      cp.project_dir as artifact_root,
      array['run_notes.md','.enoch/project_decision.json','.enoch/metrics.json','results/smoke.json'] as artifact_paths
    from enoch.paper_eligibility pe
    left join enoch.queue_items qi on qi.project_id=pe.project_id
    left join enoch.papers p on p.project_id=pe.project_id or p.run_id=pe.run_id
    left join enoch.corpus_imports ci on ci.paper_id=p.paper_id
    left join enoch.research_lineage rl on rl.target_type='candidate' and rl.target_id=pe.project_id
    left join enoch.research_sources rs on rs.source_id=rl.source_id
    left join enoch.paper_eligibility parent_pe on lower(parent_pe.followup_title)=lower(pe.project_name) and parent_pe.project_id<>pe.project_id
    left join enoch.research_lineage parent_rl on parent_rl.target_type='candidate' and parent_rl.target_id=parent_pe.project_id
    left join enoch.research_sources parent_rs on parent_rs.source_id=parent_rl.source_id
    left join enoch.projects cp on cp.project_id=pe.project_id
    where {where_sql}
    group by pe.project_id, pe.project_name, pe.run_id, pe.decision_summary,
      pe.research_outcome, pe.hypothesis_status, pe.evidence_strength,
      pe.claim_scope, pe.scale_limits, pe.useful_signal_summary,
      pe.recommended_next_action, pe.stop_reason,
      pe.followup_recommended, pe.followup_type, pe.followup_title,
      pe.followup_hypothesis, pe.followup_required_evidence,
      pe.followup_success_threshold, pe.followup_stop_condition,
      pe.followup_depth, pe.bounded_paper_ready, pe.compute_scale_blocked,
      pe.write_needed, pe.has_live_paper_row,
      qi.updated_at, p.paper_id, p.paper_status, ci.imported_at, cp.project_dir
    """
    with psycopg.connect(url, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-repo", required=True, type=Path)
    parser.add_argument("--input-json", type=Path, help="JSON array of rows for deterministic/offline export")
    parser.add_argument("--project-id", action="append", default=[])
    parser.add_argument("--query", default="")
    parser.add_argument("--audit-report", type=Path, help="Write a dry-run backfill audit JSON report instead of exporting rows")
    parser.add_argument("--audit-markdown", type=Path, help="Optional Markdown path for --audit-report")
    args = parser.parse_args(argv)
    if args.input_json:
        rows = json.loads(args.input_json.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise SystemExit("--input-json must contain a JSON list")
    else:
        rows = _fetch_postgres_rows(args.project_id, args.query)
    if args.audit_report:
        report = audit_backfill(rows)
        args.audit_report.parent.mkdir(parents=True, exist_ok=True)
        args.audit_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if args.audit_markdown:
            args.audit_markdown.parent.mkdir(parents=True, exist_ok=True)
            args.audit_markdown.write_text(audit_backfill_markdown(report) + "\n", encoding="utf-8")
        print(json.dumps({"audit_report": str(args.audit_report), **report["summary"]}, indent=2, sort_keys=True))
        return 0
    result = write_export(rows, args.output_repo)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
