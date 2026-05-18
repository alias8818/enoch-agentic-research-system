#!/usr/bin/env python3
"""Scout recent useful-signal decisions for bounded paper readiness.

This script is intentionally conservative: it never publishes and it does not
write paper rows. With --apply it only marks already-completed useful-signal
decision payloads as `bounded_paper_ready: true`, which moves them into the
existing paper drafting gate for a scoped draft.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from enoch_control_plane.enoch_core.store import IdempotencyConflict


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).lower() in {"1", "true", "yes", "y"}


@dataclass(frozen=True)
class ScoutRow:
    decision_id: int
    project_id: str
    project_name: str
    run_id: str
    decided_at: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ScoutResult:
    row: ScoutRow
    score: int
    eligible: bool
    reasons: list[str]
    blockers: list[str]


def _decision_payload(payload_json: dict[str, Any]) -> dict[str, Any]:
    nested = payload_json.get("project_decision")
    return nested if isinstance(nested, dict) else payload_json


def _metric_count(*values: str) -> int:
    return sum(len(re.findall(r"(?<![a-zA-Z])\d+(?:\.\d+)?\s*(?:%|x|tok/s|ms|tokens|seeds|runs)?", value)) for value in values)


def score_payload(payload: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    decision = _text(payload.get("project_decision"))
    outcome = _text(payload.get("research_outcome"))
    hyp = _text(payload.get("hypothesis_status"))
    evidence = _text(payload.get("evidence_strength"))
    claim_scope = _text(payload.get("claim_scope"))
    scale_limits = _text(payload.get("scale_limits"))
    summary = _text(payload.get("useful_signal_summary"))
    stop = _text(payload.get("stop_reason"))
    next_action = _text(payload.get("recommended_next_action"))
    combined = "\n".join([claim_scope, scale_limits, summary, stop, next_action]).lower()
    blockers: list[str] = []
    reasons: list[str] = []
    score = 0

    if decision != "finalize_negative":
        blockers.append("not a finalize_negative decision")
    if outcome != "useful_signal":
        blockers.append("not a useful_signal result")
    if _truthy(payload.get("bounded_paper_ready")):
        blockers.append("already bounded_paper_ready")
    if _truthy(payload.get("compute_scale_blocked")):
        blockers.append("compute-scale blocked")
    if hyp == "supported":
        score += 30; reasons.append("supported hypothesis")
    elif hyp == "mixed":
        score += 18; reasons.append("mixed but partially supported hypothesis")
    else:
        blockers.append(f"hypothesis_status={hyp or 'missing'}")
    if evidence == "strong":
        score += 24; reasons.append("strong evidence")
    elif evidence == "moderate":
        score += 14; reasons.append("moderate evidence")
    else:
        blockers.append(f"evidence_strength={evidence or 'missing'}")
    if len(claim_scope) >= 80:
        score += 14; reasons.append("explicit scoped claim")
    else:
        blockers.append("claim_scope too thin")
    if len(scale_limits) >= 80:
        score += 14; reasons.append("explicit scale limits")
    else:
        blockers.append("scale_limits too thin")
    metrics = _metric_count(summary, claim_scope)
    if metrics >= 4:
        score += 12; reasons.append("numeric metrics present")
    elif metrics >= 2:
        score += 6; reasons.append("some numeric metrics present")
    else:
        blockers.append("insufficient numeric metrics")
    if any(marker in combined for marker in ("baseline", "control", "ablation", "versus", "compared")):
        score += 8; reasons.append("baseline/control language present")
    else:
        blockers.append("baseline/control evidence unclear")
    if any(marker in combined for marker in ("not paper-ready", "no-paper", "publication-grade", "paper", "scoped")):
        score += 6; reasons.append("paper limits are explicit")
    else:
        blockers.append("paper-limit rationale unclear")
    if any(marker in combined for marker in ("real", "gpt-2", "distilgpt2", "wikitext", "cifar", "wall-clock", "kv-cache")):
        score += 4; reasons.append("direct/local target evidence marker present")

    return score, reasons, blockers


def load_candidates(database_url: str, *, days: int, limit: int) -> list[ScoutRow]:
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("set search_path to enoch, public")
            rows = cur.execute(
                """
                select d.decision_id, d.project_id, p.project_name, coalesce(d.run_id, '') as run_id,
                       d.decided_at::text as decided_at, d.payload_json
                from project_decisions d
                join projects p using(project_id)
                join queue_items q using(project_id)
                where d.decided_at >= now() - (%s::text || ' days')::interval
                  and q.status = 'completed'
                  and not q.manual_review_required
                  and not exists (
                    select 1 from papers paper
                    where paper.project_id = d.project_id
                      and paper.paper_status in ('draft_review','publication_draft','finalized','approved_for_corpus')
                  )
                order by d.decided_at desc, d.decision_id desc
                limit %s
                """,
                (days, limit),
            ).fetchall()
    return [ScoutRow(int(r["decision_id"]), _text(r["project_id"]), _text(r["project_name"]), _text(r["run_id"]), _text(r["decided_at"]), dict(r["payload_json"] or {})) for r in rows]


def scout(rows: list[ScoutRow], *, threshold: int) -> list[ScoutResult]:
    results: list[ScoutResult] = []
    for row in rows:
        payload = _decision_payload(row.payload)
        score, reasons, blockers = score_payload(payload)
        eligible = score >= threshold and not blockers
        if _text(payload.get("research_outcome")) == "useful_signal":
            results.append(ScoutResult(row, score, eligible, reasons, blockers))
    results.sort(key=lambda item: (item.eligible, item.score, item.row.decided_at), reverse=True)
    return results


def _canonical_event_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True)


def _event_hash(event_json: str) -> str:
    return hashlib.sha256(event_json.encode("utf-8")).hexdigest()


def _row_get(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return row[index]


def apply_ready(database_url: str, results: list[ScoutResult], *, max_apply: int, requested_by: str) -> list[dict[str, Any]]:
    import psycopg
    applied: list[dict[str, Any]] = []
    selected = [r for r in results if r.eligible][:max_apply]
    if not selected:
        return applied
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("set search_path to enoch, public")
            for result in selected:
                payload = dict(result.row.payload)
                nested = payload.get("project_decision") if isinstance(payload.get("project_decision"), dict) else payload
                nested["bounded_paper_ready"] = True
                nested["paper_scout_review"] = {
                    "reviewed_at": datetime.now(timezone.utc).isoformat(),
                    "requested_by": requested_by,
                    "score": result.score,
                    "reasons": result.reasons,
                    "mode": "bounded_paper_ready_only",
                }
                if isinstance(payload.get("project_decision"), dict):
                    payload["project_decision"] = nested
                else:
                    payload = nested
                cur.execute(
                    """
                    update project_decisions
                    set payload_json = %s::jsonb, updated_at = now()
                    where decision_id = %s
                    """,
                    (json.dumps(payload, sort_keys=True), result.row.decision_id),
                )
                event_payload = {
                    "decision_id": result.row.decision_id,
                    "project_id": result.row.project_id,
                    "run_id": result.row.run_id,
                    "score": result.score,
                    "reasons": result.reasons,
                    "effect": "bounded_paper_ready_true",
                    "requested_by": requested_by,
                }
                event_json = _canonical_event_json(event_payload)
                event_hash = _event_hash(event_json)
                event_key = f"paper-scout:{result.row.decision_id}:bounded-ready"
                cur.execute(
                    """
                    select event_id, event_type, entity_type, entity_id, payload_hash
                    from control_events
                    where idempotency_key = %s
                    """,
                    (event_key,),
                )
                existing = cur.fetchone()
                if existing and (
                    _row_get(existing, "event_type", 1) != "paper_scout.mark_ready"
                    or _row_get(existing, "entity_type", 2) != "project"
                    or _row_get(existing, "entity_id", 3) != result.row.project_id
                    or _row_get(existing, "payload_hash", 4) != event_hash
                ):
                    raise IdempotencyConflict(
                        f"idempotency key {event_key!r} was reused with different event identity"
                    )
                cur.execute(
                    """
                    insert into control_events(idempotency_key, event_type, entity_type, entity_id, payload_json, payload_hash)
                    values (%s, 'paper_scout.mark_ready', 'project', %s, %s::jsonb, %s)
                    on conflict (idempotency_key) do nothing
                    """,
                    (event_key, result.row.project_id, event_json, event_hash),
                )
                applied.append(event_payload)
        conn.commit()
    return applied


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""))
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--threshold", type=int, default=88)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-apply", type=int, default=3)
    parser.add_argument("--requested-by", default="paper-scout")
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.database_url:
        raise SystemExit("--database-url or DATABASE_URL is required")
    rows = load_candidates(args.database_url, days=args.days, limit=args.limit)
    results = scout(rows, threshold=args.threshold)
    applied = apply_ready(args.database_url, results, max_apply=args.max_apply, requested_by=args.requested_by) if args.apply else []
    report = {
        "schema_version": "enoch_paper_scout_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime_effect": "marked_bounded_paper_ready" if args.apply else "none",
        "threshold": args.threshold,
        "days": args.days,
        "inspected": len(rows),
        "useful_signal_reviewed": len(results),
        "eligible_count": sum(1 for r in results if r.eligible),
        "applied_count": len(applied),
        "applied": applied,
        "top_candidates": [
            {
                "decision_id": r.row.decision_id,
                "project_id": r.row.project_id,
                "project_name": r.row.project_name,
                "run_id": r.row.run_id,
                "decided_at": r.row.decided_at,
                "score": r.score,
                "eligible": r.eligible,
                "reasons": r.reasons,
                "blockers": r.blockers,
            }
            for r in results[:25]
        ],
    }
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
