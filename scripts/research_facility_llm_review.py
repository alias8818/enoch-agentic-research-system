#!/usr/bin/env python3
"""Quota-gated LLM adjudication for Research Facility janitor rows.

This is a second-opinion layer, not the primary scorer. It spends at most one
provider request per run, only after Synthetic quota gates pass, and it only
applies safe deterministic mutations: admitted rows may be moved to admitted;
rewrite/keep/reject decisions now close the candidate review loop by moving rows to explicit terminal or holding statuses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import research_facility_maintenance, research_provider_budget, research_provider_generate

DECISIONS = {"admit", "rewrite_contract", "keep_for_later", "reject"}
NON_ADMIT_STATUS_BY_DECISION = {"reject": "rejected", "rewrite_contract": "rewrite_needed", "keep_for_later": "deferred"}
ADMISSION_DECISION_BY_STATUS = {"rejected": "rejected", "rewrite_needed": "rewrite_needed", "deferred": "deferred"}
DEFAULT_MODEL = "hf:zai-org/GLM-5.1"
PROMPT_VERSION = "research_facility_llm_review_v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.S)
        if match:
            text = match.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\{\s*\"decisions\"\s*:\s*\[.*\]\s*\})", text, flags=re.S)
        if not match:
            raise
        data = json.loads(match.group(1))
    if not isinstance(data, dict) or not isinstance(data.get("decisions"), list):
        raise ValueError("LLM review response must be an object with decisions array")
    return data


def budget_status(
    *,
    base_url: str,
    estimated_requests: int,
    reserve_requests: int,
    min_remaining_credits: float,
    min_rolling_remaining: int,
    min_weekly_percent_remaining: float,
    timeout: int,
) -> dict[str, Any]:
    payload = research_provider_budget.fetch_json(f"{base_url.rstrip('/')}/v2/quotas", api_key="", timeout=timeout)
    result = research_provider_budget.synthetic_budget_status(
        payload,
        min_remaining_credits=min_remaining_credits,
        min_rolling_remaining=min_rolling_remaining,
        estimated_requests=estimated_requests,
        reserve_requests=reserve_requests,
    )
    weekly = payload.get("weeklyTokenLimit") or {}
    try:
        weekly_percent = float(weekly.get("percentRemaining") or 0.0)
    except (TypeError, ValueError):
        weekly_percent = 0.0
    result["weekly_percent_remaining"] = weekly_percent
    result["min_weekly_percent_remaining"] = min_weekly_percent_remaining
    if weekly_percent < min_weekly_percent_remaining:
        result.setdefault("failures", []).append(
            f"weekly percent remaining {weekly_percent:.2f} < minimum {min_weekly_percent_remaining:.2f}"
        )
        result["ok"] = False
    return result


def latest_review_age_minutes(database_url: str, *, event_type: str = "research.janitor.llm_review") -> float | None:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("set search_path to enoch, public")
            row = cur.execute(
                "select created_at from control_events where event_type = %s order by created_at desc limit 1",
                (event_type,),
            ).fetchone()
    if not row:
        return None
    created = row["created_at"]
    if isinstance(created, str):
        created = datetime.fromisoformat(created.replace("Z", "+00:00"))
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - created).total_seconds() / 60.0)


def select_review_batch(database_url: str, *, limit: int, janitor_limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = research_facility_maintenance.fetch_needs_review_rows(database_url, limit=janitor_limit)
    actions = research_facility_maintenance.classify_rows(rows, policy=research_facility_maintenance.JanitorPolicy())
    by_id = {str(row.get("candidate_id")): row for row in rows}
    rewrite = [action for action in actions if action.get("action") == "rewrite_suggested"]
    rewrite.sort(key=lambda action: float((action.get("dispatch_priority") or {}).get("dispatch_priority_score") or 0), reverse=True)
    batch: list[dict[str, Any]] = []
    for action in rewrite[:limit]:
        row = by_id.get(str(action.get("candidate_id")))
        if not row:
            continue
        batch.append({"candidate": row, "janitor_action": action})
    return batch, research_facility_maintenance.build_report(rows, actions, applied=False, apply_result=None)


def build_review_prompt(batch: list[dict[str, Any]]) -> str:
    compact = []
    for item in batch:
        row = item["candidate"]
        action = item["janitor_action"]
        compact.append({
            "candidate_id": row.get("candidate_id"),
            "title": row.get("title"),
            "category": row.get("category"),
            "generation_mode": row.get("generation_mode"),
            "source_kind": row.get("source_kind"),
            "source_urls": row.get("source_urls") or [],
            "parent_project_id": row.get("parent_project_id"),
            "total_score": row.get("total_score"),
            "score_breakdown": row.get("score_breakdown") or {},
            "dispatch_priority": action.get("dispatch_priority") or {},
            "hypothesis": row.get("hypothesis"),
            "mechanism": row.get("mechanism"),
            "baseline_to_beat": row.get("baseline_to_beat"),
            "success_threshold": row.get("success_threshold"),
            "kill_condition": row.get("kill_condition"),
            "accessibility_delta": row.get("accessibility_delta"),
            "expected_artifacts": row.get("expected_artifacts") or [],
            "required_evidence": row.get("required_evidence") or [],
            "likely_failure_modes": row.get("likely_failure_modes") or [],
            "estimated_runtime_class": row.get("estimated_runtime_class"),
            "expected_token_budget": row.get("expected_token_budget"),
        })
    return f"""
Return ONLY compact JSON with this exact top-level shape:
{{"decisions":[{{"candidate_id":"...","decision":"admit|rewrite_contract|keep_for_later|reject","confidence":"low|medium|high","reason":"<=220 chars","rewrite_notes":"<=260 chars"}}]}}

You are adjudicating Enoch Research Facility candidates that deterministic rules marked rewrite_suggested.
Choose exactly one decision per candidate_id.

Policy:
- admit only if the candidate is already specific, falsifiable, bounded, and worth queueing without another rewrite.
- rewrite_contract if the idea is promising but needs a sharper hypothesis, baseline, metric, branch target, or evidence ladder.
- keep_for_later if reasonable but lower priority, saturated, expensive, or not urgent.
- reject if duplicate, vague, too incremental, untestable locally, or likely proxy-only.
- Prefer bounded GPT-2-small-class or direct target-stack evidence over toy proxies.
- Do not admit shallow variants just because they sound interesting.

Candidates JSON:
{json.dumps(compact, ensure_ascii=False, sort_keys=True, default=str)}
""".strip()


def call_review_model(*, base_url: str, model: str, prompt: str, timeout: int, max_tokens: int, temperature: float) -> dict[str, Any]:
    payload = research_provider_generate.call_openai_compatible_chat(
        base_url=base_url,
        model=model,
        prompt=prompt,
        api_key="",
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    content = research_provider_generate._extract_chat_content(payload)  # type: ignore[attr-defined]
    data = _extract_json_object(content)
    data["provider_response_id"] = payload.get("id", "")
    return data


def normalize_decisions(raw: dict[str, Any], batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed_ids = {str(item["candidate"].get("candidate_id")) for item in batch}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw.get("decisions") or []:
        if not isinstance(item, dict):
            continue
        candidate_id = _as_text(item.get("candidate_id"))
        decision = _as_text(item.get("decision")).lower()
        if candidate_id not in allowed_ids or candidate_id in seen or decision not in DECISIONS:
            continue
        seen.add(candidate_id)
        out.append({
            "candidate_id": candidate_id,
            "decision": decision,
            "confidence": _as_text(item.get("confidence") or "low")[:20],
            "reason": _as_text(item.get("reason"))[:500],
            "rewrite_notes": _as_text(item.get("rewrite_notes"))[:800],
        })
    return out


def _confidence_allows_admit(decision: dict[str, Any]) -> bool:
    return _as_text(decision.get("confidence")).lower() in {"medium", "high"}


def _candidate_status_for_decision(decision: dict[str, Any]) -> str | None:
    verdict = _as_text(decision.get("decision")).lower()
    if verdict == "admit":
        return "admitted" if _confidence_allows_admit(decision) else "deferred"
    return NON_ADMIT_STATUS_BY_DECISION.get(verdict)


def _status_update_payload(*, decision: dict[str, Any], provider_model: str, janitor_action: dict[str, Any]) -> dict[str, Any]:
    return {
        "janitor_llm_decision": {
            "decision": decision.get("decision"),
            "confidence": decision.get("confidence"),
            "reason": decision.get("reason"),
            "rewrite_notes": decision.get("rewrite_notes"),
            "provider_model": provider_model,
            "prompt_version": PROMPT_VERSION,
            "janitor_action": janitor_action,
            "decided_at": utc_now(),
        }
    }


def _apply_non_admit_decision(
    cur: Any,
    *,
    candidate_id: str,
    decision: dict[str, Any],
    requested_by: str,
    provider_model: str,
    janitor_action: dict[str, Any],
) -> dict[str, int]:
    status = _candidate_status_for_decision(decision)
    if status not in {"rejected", "rewrite_needed", "deferred"}:
        return {"status_updates": 0, "admissions_inserted": 0}
    admission_decision = ADMISSION_DECISION_BY_STATUS[status]
    reason = decision.get("reason") or f"LLM janitor review marked {admission_decision}"
    payload = _status_update_payload(decision=decision, provider_model=provider_model, janitor_action=janitor_action)
    cur.execute(
        """
        update research_candidates
        set status = %s,
            rejection_reason = case when %s = 'rejected' then %s else rejection_reason end,
            score_breakdown = coalesce(score_breakdown, '{}'::jsonb) || %s::jsonb,
            updated_at = now()
        where candidate_id = %s and status = 'needs_review'
        """,
        (status, status, str(reason), json.dumps(payload, sort_keys=True, default=str), candidate_id),
    )
    status_updates = int(cur.rowcount or 0)
    admission_key = f"research-janitor-llm-admission:{candidate_id}:{admission_decision}"
    cur.execute(
        """
        insert into research_admissions(candidate_id, admission_decision, admission_reason, score_breakdown, admitted_idea_id, operator, idempotency_key)
        values (%s,%s,%s,%s::jsonb,null,%s,%s)
        on conflict (idempotency_key) do nothing
        """,
        (candidate_id, admission_decision, str(reason), json.dumps(payload, sort_keys=True, default=str), requested_by, admission_key),
    )
    return {"status_updates": status_updates, "admissions_inserted": int(cur.rowcount or 0)}


def record_review(database_url: str, *, decisions: list[dict[str, Any]], batch: list[dict[str, Any]], requested_by: str, provider_model: str, dry_run: bool) -> dict[str, Any]:
    import psycopg

    by_id = {str(item["candidate"].get("candidate_id")): item for item in batch}
    counts = Counter(decision["decision"] for decision in decisions)
    result = {
        "dry_run": dry_run,
        "decision_counts": dict(sorted(counts.items())),
        "events_inserted": 0,
        "admissions_inserted": 0,
        "status_updates": 0,
        "admitted": 0,
        "rejected": 0,
        "rewrite_needed": 0,
        "deferred": 0,
    }
    if dry_run:
        return result
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("set search_path to enoch, public")
            for decision in decisions:
                candidate_id = decision["candidate_id"]
                source = by_id.get(candidate_id, {})
                janitor_action = source.get("janitor_action") or {}
                payload = {
                    "requested_by": requested_by,
                    "provider_model": provider_model,
                    "prompt_version": PROMPT_VERSION,
                    "llm_decision": decision,
                    "janitor_action": janitor_action,
                }
                event_key = f"research-janitor-llm:{candidate_id}:{decision['decision']}"
                cur.execute("select event_id from control_events where idempotency_key = %s", (event_key,))
                if not cur.fetchone():
                    cur.execute(
                        """
                        insert into control_events(idempotency_key,event_type,entity_type,entity_id,payload_json,payload_hash,created_at)
                        values (%s,'research.janitor.llm_review','research_candidate',%s,%s::jsonb,%s,%s)
                        """,
                        (event_key, candidate_id, json.dumps(payload, sort_keys=True, default=str), _payload_hash(payload), datetime.now(timezone.utc).isoformat()),
                    )
                    result["events_inserted"] += int(cur.rowcount or 0)
                if decision["decision"] == "admit" and _confidence_allows_admit(decision):
                    action = source.get("janitor_action") or {"candidate_id": candidate_id, "action": "promote", "reason": decision.get("reason") or "LLM review admitted candidate"}
                    action = dict(action)
                    action["action"] = "promote"
                    action["reason"] = f"LLM janitor review admitted: {decision.get('reason') or 'no reason'}"
                    apply = research_facility_maintenance.apply_actions(database_url, [action], requested_by=requested_by, apply_rejections=False)
                    promoted = int(apply.get("promoted") or 0)
                    result["admitted"] += promoted
                    result["status_updates"] += promoted
                    result["admissions_inserted"] += int(apply.get("admissions_inserted") or 0)
                    continue
                update = _apply_non_admit_decision(
                    cur,
                    candidate_id=candidate_id,
                    decision=decision,
                    requested_by=requested_by,
                    provider_model=provider_model,
                    janitor_action=janitor_action,
                )
                status = _candidate_status_for_decision(decision)
                updated = int(update.get("status_updates") or 0)
                result["status_updates"] += updated
                result["admissions_inserted"] += int(update.get("admissions_inserted") or 0)
                if updated and status in {"rejected", "rewrite_needed", "deferred"}:
                    result[status] += updated
    return result


def apply_stored_llm_decisions(database_url: str, *, requested_by: str, limit: int, dry_run: bool) -> dict[str, Any]:
    """Apply latest stored LLM janitor decisions that were event-only before this patch."""

    import psycopg
    from psycopg.rows import dict_row

    result: dict[str, Any] = {
        "dry_run": dry_run,
        "candidate_count": 0,
        "decision_counts": {},
        "status_updates": 0,
        "admissions_inserted": 0,
        "rejected": 0,
        "rewrite_needed": 0,
        "deferred": 0,
        "admitted": 0,
    }
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("set search_path to enoch, public")
            rows = cur.execute(
                """
                select distinct on (e.entity_id)
                       e.entity_id as candidate_id,
                       e.payload_json->'llm_decision' as llm_decision,
                       e.payload_json->'janitor_action' as janitor_action,
                       coalesce(e.payload_json->>'provider_model', '') as provider_model,
                       e.created_at
                from control_events e
                join research_candidates c on c.candidate_id = e.entity_id
                where e.event_type = 'research.janitor.llm_review'
                  and e.entity_type = 'research_candidate'
                  and c.status = 'needs_review'
                  and e.payload_json ? 'llm_decision'
                order by e.entity_id, e.created_at desc
                limit %s
                """,
                (max(1, min(limit, 2000)),),
            ).fetchall()
            result["candidate_count"] = len(rows)
            decisions = [dict(row["llm_decision"] or {}, candidate_id=row["candidate_id"]) for row in rows]
            result["decision_counts"] = dict(sorted(Counter(_as_text(d.get("decision")).lower() for d in decisions if _as_text(d.get("decision"))).items()))
            if dry_run:
                return result
            for row in rows:
                decision = dict(row["llm_decision"] or {})
                decision["candidate_id"] = row["candidate_id"]
                if decision.get("decision") == "admit" and _confidence_allows_admit(decision):
                    action = dict(row["janitor_action"] or {})
                    action["candidate_id"] = row["candidate_id"]
                    action["action"] = "promote"
                    action["reason"] = f"Stored LLM janitor review admitted: {decision.get('reason') or 'no reason'}"
                    apply = research_facility_maintenance.apply_actions(database_url, [action], requested_by=requested_by, apply_rejections=False)
                    promoted = int(apply.get("promoted") or 0)
                    result["admitted"] += promoted
                    result["status_updates"] += promoted
                    result["admissions_inserted"] += int(apply.get("admissions_inserted") or 0)
                    continue
                update = _apply_non_admit_decision(
                    cur,
                    candidate_id=row["candidate_id"],
                    decision=decision,
                    requested_by=requested_by,
                    provider_model=row["provider_model"] or DEFAULT_MODEL,
                    janitor_action=dict(row["janitor_action"] or {}),
                )
                status = _candidate_status_for_decision(decision)
                updated = int(update.get("status_updates") or 0)
                result["status_updates"] += updated
                result["admissions_inserted"] += int(update.get("admissions_inserted") or 0)
                if updated and status in {"rejected", "rewrite_needed", "deferred"}:
                    result[status] += updated
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--provider-base-url", default=os.environ.get("ENOCH_RESEARCH_PROVIDER_BASE_URL", "https://synthetic.int.exe.xyz"))
    parser.add_argument("--openai-base-url", default=os.environ.get("ENOCH_RESEARCH_PROVIDER_OPENAI_BASE_URL", "https://synthetic.int.exe.xyz/openai/v1"))
    parser.add_argument("--model", default=os.environ.get("ENOCH_RESEARCH_PROVIDER_MODEL", DEFAULT_MODEL))
    parser.add_argument("--batch-size", type=int, default=15)
    parser.add_argument("--janitor-limit", type=int, default=250)
    parser.add_argument("--estimated-requests", type=int, default=1)
    parser.add_argument("--reserve-requests", type=int, default=5)
    parser.add_argument("--min-rolling-remaining", type=int, default=150)
    parser.add_argument("--min-remaining-credits", type=float, default=10.0)
    parser.add_argument("--min-weekly-percent-remaining", type=float, default=25.0)
    parser.add_argument("--cooldown-minutes", type=int, default=25)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--max-tokens", type=int, default=6000)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--requested-by", default="research-facility-llm-review")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--apply-stored-decisions", action="store_true", help="Apply prior event-only LLM janitor decisions before any provider call")
    parser.add_argument("--apply-stored-decisions-only", action="store_true", help="Apply prior event-only LLM janitor decisions and exit without a provider call")
    parser.add_argument("--stored-decision-limit", type=int, default=500)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    dry_run = not args.apply or args.dry_run
    report: dict[str, Any] = {"ok": False, "action": "research_janitor_llm_review", "dry_run": dry_run, "checked_at": utc_now()}
    if args.apply_stored_decisions or args.apply_stored_decisions_only:
        stored = apply_stored_llm_decisions(
            args.database_url,
            requested_by=args.requested_by,
            limit=args.stored_decision_limit,
            dry_run=dry_run,
        )
        report["stored_decision_apply"] = stored
        if args.apply_stored_decisions_only:
            report.update({"ok": True, "action": "applied_stored_decisions"})
            text = json.dumps(report, indent=2, sort_keys=True, default=str)
            if args.output:
                args.output.write_text(text + "\n", encoding="utf-8")
            else:
                print(text)
            return 0
    age = latest_review_age_minutes(args.database_url)
    report["last_review_age_minutes"] = age
    if age is not None and age < args.cooldown_minutes:
        report.update({"ok": True, "action": "skipped", "reason": f"cooldown active: {age:.1f}m < {args.cooldown_minutes}m"})
    else:
        budget = budget_status(
            base_url=args.provider_base_url,
            estimated_requests=args.estimated_requests,
            reserve_requests=args.reserve_requests,
            min_remaining_credits=args.min_remaining_credits,
            min_rolling_remaining=args.min_rolling_remaining,
            min_weekly_percent_remaining=args.min_weekly_percent_remaining,
            timeout=min(max(args.timeout, 5), 60),
        )
        report["budget"] = {key: budget.get(key) for key in (
            "ok", "remaining_credits", "min_remaining_credits", "weekly_percent_remaining", "min_weekly_percent_remaining",
            "rolling_remaining", "rolling_max", "rolling_limited", "estimated_requests", "reserve_requests", "failures",
        )}
        if not budget.get("ok"):
            report.update({"ok": True, "action": "skipped", "reason": "; ".join(budget.get("failures") or ["budget unavailable"])})
        else:
            batch, janitor = select_review_batch(args.database_url, limit=max(1, min(args.batch_size, 50)), janitor_limit=args.janitor_limit)
            report["janitor"] = {"row_count": janitor.get("row_count"), "action_counts": janitor.get("action_counts")}
            report["batch_count"] = len(batch)
            if not batch:
                report.update({"ok": True, "action": "skipped", "reason": "no rewrite_suggested backlog"})
            else:
                prompt = build_review_prompt(batch)
                raw = call_review_model(
                    base_url=args.openai_base_url,
                    model=args.model,
                    prompt=prompt,
                    timeout=args.timeout,
                    max_tokens=args.max_tokens,
                    temperature=args.temperature,
                )
                decisions = normalize_decisions(raw, batch)
                apply_result = record_review(
                    args.database_url,
                    decisions=decisions,
                    batch=batch,
                    requested_by=args.requested_by,
                    provider_model=args.model,
                    dry_run=dry_run,
                )
                report.update({
                    "ok": True,
                    "action": "reviewed",
                    "provider_model": args.model,
                    "provider_response_id": raw.get("provider_response_id", ""),
                    "prompt_version": PROMPT_VERSION,
                    "decision_count": len(decisions),
                    "decision_counts": apply_result.get("decision_counts") or dict(Counter(d["decision"] for d in decisions)),
                    "apply_result": apply_result,
                    "decisions": decisions,
                })
    text = json.dumps(report, indent=2, sort_keys=True, default=str)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
