#!/usr/bin/env python3
"""Research Facility janitor for needs-review candidates.

The janitor is intentionally conservative. By default it only reads live rows,
computes the separate dispatch-priority score, and writes a JSON report. With
``--apply`` it can admit strong borderline candidates. Rejections require the
extra ``--apply-rejections`` flag so cleanup cannot silently throw away ideas.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import research_facility


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _payload_hash(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class JanitorPolicy:
    promote_score_floor: float = 71.5
    promote_priority_floor: float = 80.0
    reject_score_ceiling: float = 65.0
    reject_stale_days: float = 7.0
    rewrite_score_floor: float = 68.0
    saturated_category_count: int = 18


def _priority_signal(row: dict[str, Any], breakdown: dict[str, Any]) -> bool:
    return bool(
        float(breakdown.get("lineage_bonus") or 0) >= 5.0
        or float(breakdown.get("targeted_source_bonus") or 0) >= 4.0
        or _as_text(row.get("parent_project_id"))
        or _as_text(row.get("parent_run_id"))
    )


def classify_candidate(row: dict[str, Any], *, category_counts: dict[str, int], policy: JanitorPolicy, now: datetime | None = None) -> dict[str, Any]:
    breakdown = research_facility.dispatch_priority_breakdown(row, category_counts=category_counts, now=now)
    total_score = _as_float(row.get("total_score"))
    duplicate_penalty = float(breakdown.get("duplicate_penalty") or 0)
    weak_penalty = float(breakdown.get("weak_contract_penalty") or 0)
    saturated = int(breakdown.get("category_count") or 0) >= policy.saturated_category_count
    has_priority_signal = _priority_signal(row, breakdown)

    action = "keep"
    reason = "candidate remains reviewable but does not cross janitor thresholds"
    if (
        (
            float(breakdown["dispatch_priority_score"]) >= policy.promote_priority_floor
            or (total_score >= policy.promote_score_floor and has_priority_signal)
        )
        and duplicate_penalty < 8.0
        and (has_priority_signal or not saturated)
    ):
        action = "promote"
        reason = "strong borderline needs-review candidate with sufficient priority signal"
    elif total_score <= policy.reject_score_ceiling and float(breakdown.get("age_days") or 0) >= policy.reject_stale_days and weak_penalty >= 6.0:
        action = "reject"
        reason = "stale low-score needs-review candidate with weak contract signals"
    elif total_score >= policy.rewrite_score_floor:
        action = "rewrite_suggested"
        reason = "candidate may be salvageable with a tighter contract, branch target, or evidence source"

    return {
        "candidate_id": row.get("candidate_id"),
        "title": row.get("title"),
        "category": row.get("category"),
        "generation_mode": row.get("generation_mode"),
        "status": row.get("status"),
        "total_score": total_score,
        "action": action,
        "reason": reason,
        "dispatch_priority": breakdown,
    }


def classify_rows(rows: Iterable[dict[str, Any]], *, policy: JanitorPolicy, now: datetime | None = None) -> list[dict[str, Any]]:
    rows_list = list(rows)
    category_counts = Counter(_as_text(row.get("category")).lower() for row in rows_list if _as_text(row.get("category")))
    return [classify_candidate(row, category_counts=dict(category_counts), policy=policy, now=now) for row in rows_list]


def fetch_needs_review_rows(database_url: str, *, limit: int) -> list[dict[str, Any]]:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("set search_path to enoch, public")
            cur.execute(
                """
                select candidate_id, generation_mode, status, title, category, priority,
                       source_kind, source_ids, source_urls, parent_project_id, parent_run_id,
                       hypothesis, mechanism, baseline_to_beat, success_threshold, kill_condition,
                       accessibility_delta, expected_artifacts, required_evidence, likely_failure_modes,
                       estimated_runtime_class, expected_token_budget, novelty_score, feasibility_score,
                       accessibility_score, falsifiability_score, total_score, score_breakdown,
                       dedupe_key, similar_prior_projects, novelty_comparison, risk_notes,
                       provider, provider_model, created_at, updated_at
                from research_candidates
                where status = 'needs_review'
                order by total_score desc, updated_at asc, candidate_id asc
                limit %s
                """,
                (max(1, min(limit, 2000)),),
            )
            return [dict(row) for row in cur.fetchall()]


def apply_actions(database_url: str, actions: list[dict[str, Any]], *, requested_by: str, apply_rejections: bool) -> dict[str, int]:
    import psycopg

    counters = {"promoted": 0, "rejected": 0, "skipped_rejections": 0, "events_inserted": 0, "admissions_inserted": 0}
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("set search_path to enoch, public")
            for action in actions:
                candidate_id = _as_text(action.get("candidate_id"))
                verb = _as_text(action.get("action"))
                if not candidate_id:
                    continue
                if verb == "promote":
                    cur.execute(
                        """
                        update research_candidates
                        set status = 'admitted', score_breakdown = coalesce(score_breakdown, '{}'::jsonb) || %s::jsonb, updated_at = now()
                        where candidate_id = %s and status = 'needs_review'
                        """,
                        (json.dumps({"janitor_dispatch_priority": action.get("dispatch_priority") or {}}), candidate_id),
                    )
                    if int(cur.rowcount or 0):
                        counters["promoted"] += 1
                    admission_key = f"research-janitor:admit:{candidate_id}"
                    cur.execute(
                        """
                        insert into research_admissions(candidate_id, admission_decision, admission_reason, score_breakdown, admitted_idea_id, operator, idempotency_key)
                        values (%s,'admitted',%s,%s::jsonb,null,%s,%s)
                        on conflict (idempotency_key) do nothing
                        """,
                        (candidate_id, str(action.get("reason") or "janitor admitted needs-review candidate"), json.dumps(action.get("dispatch_priority") or {}), requested_by, admission_key),
                    )
                    counters["admissions_inserted"] += int(cur.rowcount or 0)
                elif verb == "reject":
                    if not apply_rejections:
                        counters["skipped_rejections"] += 1
                        continue
                    cur.execute(
                        """
                        update research_candidates
                        set status = 'rejected', rejection_reason = %s, updated_at = now()
                        where candidate_id = %s and status = 'needs_review'
                        """,
                        (str(action.get("reason") or "janitor rejected stale weak candidate"), candidate_id),
                    )
                    if int(cur.rowcount or 0):
                        counters["rejected"] += 1
                    admission_key = f"research-janitor:reject:{candidate_id}"
                    cur.execute(
                        """
                        insert into research_admissions(candidate_id, admission_decision, admission_reason, score_breakdown, admitted_idea_id, operator, idempotency_key)
                        values (%s,'rejected',%s,%s::jsonb,null,%s,%s)
                        on conflict (idempotency_key) do nothing
                        """,
                        (candidate_id, str(action.get("reason") or "janitor rejected stale weak candidate"), json.dumps(action.get("dispatch_priority") or {}), requested_by, admission_key),
                    )
                    counters["admissions_inserted"] += int(cur.rowcount or 0)
                if verb in {"promote", "reject", "rewrite_suggested", "keep"}:
                    payload = {"requested_by": requested_by, "janitor_action": action}
                    event_key = f"research-janitor:{verb}:{candidate_id}"
                    cur.execute(
                        "select event_id, payload_hash from control_events where idempotency_key = %s",
                        (event_key,),
                    )
                    existing = cur.fetchone()
                    payload_hash = _payload_hash(payload)
                    if not existing:
                        cur.execute(
                            """
                            insert into control_events(idempotency_key,event_type,entity_type,entity_id,payload_json,payload_hash,created_at)
                            values (%s,%s,'research_candidate',%s,%s::jsonb,%s,%s)
                            """,
                            (event_key, f"research.janitor.{verb}", candidate_id, json.dumps(payload, default=_json_default), payload_hash, datetime.now(timezone.utc).isoformat()),
                        )
                        counters["events_inserted"] += int(cur.rowcount or 0)
    return counters


def build_report(rows: list[dict[str, Any]], actions: list[dict[str, Any]], *, applied: bool, apply_result: dict[str, int] | None) -> dict[str, Any]:
    counts = Counter(action["action"] for action in actions)
    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": not applied,
        "row_count": len(rows),
        "action_counts": dict(sorted(counts.items())),
        "apply_result": apply_result or {},
        "actions": actions,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Classify and optionally clean Research Facility needs-review rows")
    parser.add_argument("--database-url", required=True, help="Postgres connection URL for the enoch schema")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--apply", action="store_true", help="Apply promotions; rejections still require --apply-rejections")
    parser.add_argument("--apply-rejections", action="store_true", help="Also apply reject actions")
    parser.add_argument("--requested-by", default="research-facility-janitor")
    parser.add_argument("--promote-score-floor", type=float, default=71.5)
    parser.add_argument("--promote-priority-floor", type=float, default=80.0)
    parser.add_argument("--reject-score-ceiling", type=float, default=65.0)
    parser.add_argument("--reject-stale-days", type=float, default=7.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    policy = JanitorPolicy(
        promote_score_floor=args.promote_score_floor,
        promote_priority_floor=args.promote_priority_floor,
        reject_score_ceiling=args.reject_score_ceiling,
        reject_stale_days=args.reject_stale_days,
    )
    rows = fetch_needs_review_rows(args.database_url, limit=args.limit)
    actions = classify_rows(rows, policy=policy)
    apply_result = None
    if args.apply:
        apply_result = apply_actions(args.database_url, actions, requested_by=args.requested_by, apply_rejections=args.apply_rejections)
    report = build_report(rows, actions, applied=args.apply, apply_result=apply_result)
    text = json.dumps(report, indent=2, sort_keys=True, default=_json_default)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
