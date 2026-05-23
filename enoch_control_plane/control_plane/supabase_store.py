from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from ..enoch_core.logic import (
    followup_candidate_from_decision_payload,
    paper_draft_decision_gate,
    project_decision_payload,
)
from ..enoch_core.store import IdempotencyConflict
from ..models import utc_now
from .models import (
    ControlFlags,
    DashboardObservationRecord,
    IdeaIntakeRequest,
    ImportSnapshotRequest,
    NotionIntakeRequest,
    PaperRecord,
    PaperReviewApproveFinalizationRequest,
    PaperReviewBackfillRequest,
    PaperReviewChecklistUpdateRequest,
    PaperReviewClaimRequest,
    PaperReviewPrepareFinalizationRequest,
    PaperReviewRecord,
    PaperReviewStatusUpdateRequest,
    PaperStatus,
    ReviewQueueItem,
    ReviewStatus,
    RunState,
)
from .promising_signal_priority import (
    promising_followup_priority_key,
    ranked_followup_readiness,
)
from .store import (
    ACTIVE_STATUSES,
    ALLOWED_STATUS_TRANSITIONS,
    SYSTEM_REVIEW_STATUSES,
    QueueStatus,
    TERMINAL_SUCCESS_CALLBACK_STATES,
    WORKER_CALLBACK_AUDIT_KEYS,
    _atomic_write_text,
    _audit_rows,
    _bool,
    _checklist_progress,
    _collect_idea_intake_candidates,
    _completed_success_queue_row,
    _contract_worker_callback_states,
    _derived_worker_callback_idempotency_key,
    _late_terminal_success_worker_callback_payload,
    _stale_worker_callback_ignore_reason,
    _stale_worker_callback_payload,
    _worker_callback_entity_id,
    _worker_callback_event_type_name,
    _worker_callback_payload,
    _worker_callback_transition,
    _default_review_checklist,
    _default_supabase_finalization_root,
    _expanduser_or_none,
    _existing_file_snapshot,
    _first_present,
    _hash,
    _int,
    _is_older_timestamp,
    _json,
    _json_dict,
    _json_list,
    _notion_intake_row_result,
    _notion_page_id,
    _notion_page_id_from_url,
    _notion_status,
    _notion_title,
    _notion_url,
    _normal,
    _paper_identity_conflicts,
    _normalize_review_checklist,
    _priority_rank,
    _progress_for_items,
    _readiness_passed,
    _review_rank,
    _restore_or_remove_path,
    _import_snapshot_event_payload,
    _paper_status_from_import_raw,
    _reject_conflicting_snapshot_rows,
    _slug_id,
    _snapshot_rows,
    _text,
    _validate_import_snapshot_rows,
)
from .workload_routing import route_machine_target

# Centralized SQL constant for the top remaining S1192 duplication
# (status count query used in multiple _query calls).
STATUS_COUNT_QUERY = "select status, count(*) as count from queue_items group by status"
PROJECT_DECISION_JSON_FILENAME = "project_decision.json"


ConnectionFactory = Callable[[], Any]


def _decision_gate_state(gate: dict[str, Any]) -> str:
    if gate.get("eligible") is True:
        return "positive"
    reason = _text(gate.get("reason")).lower()
    decision = _text(gate.get("decision")).lower()
    values = " ".join(
        _text(item[-1]).lower()
        for item in gate.get("values") or []
        if isinstance(item, (list, tuple)) and item
    )
    haystack = " ".join([reason, decision, values])
    if "missing" in reason:
        return "missing"
    if "could not" in reason or "malformed" in reason:
        return "malformed"
    if any(
        token in haystack
        for token in (
            "negative",
            "reject",
            "not positive",
            "nonpositive",
            "non_positive",
        )
    ):
        return "negative"
    if any(
        token in haystack
        for token in ("needs_review", "inconclusive", "caveat", "conditional", "mixed")
    ):
        return "unknown"
    return "unknown"


def _stable_followup_id(parent_project_id: str, title: str, hypothesis: str) -> str:
    seed = f"{parent_project_id}:{title}:{hypothesis}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:10]
    slug = (
        _slug_id(title or f"followup-{parent_project_id}")[:58].strip("-") or "followup"
    )
    return f"{slug}-{digest}"[:80]


def _followup_parent_source_record(
    candidate: dict[str, Any], followup_payload: dict[str, Any]
) -> dict[str, Any]:
    parent_project_id = _text(
        followup_payload.get("parent_project_id") or candidate.get("project_id")
    )
    parent_run_id = _text(
        followup_payload.get("parent_run_id") or candidate.get("current_run_id")
    )
    parent_title = _text(candidate.get("project_name")) or parent_project_id
    locator = (
        f"projects/{parent_project_id}/runs/{parent_run_id}"
        if parent_run_id
        else f"projects/{parent_project_id}/decisions/latest"
    )
    source_url = f"enoch://control-plane/{locator}"
    source_seed = f"followup-parent-run:{parent_project_id}:{parent_run_id or 'latest'}"
    source_id = f"followup-parent-run-{hashlib.sha256(source_seed.encode('utf-8')).hexdigest()[:16]}"
    return {
        "source_id": source_id,
        "source_kind": "prior_followup_evidence",
        "title": f"Parent run decision: {parent_title}",
        "url": source_url,
        "external_id": parent_run_id or parent_project_id,
        "summary": f"Follow-up source captured from parent project {parent_project_id}",
        "payload_json": {
            "parent_project_id": parent_project_id,
            "parent_run_id": parent_run_id,
            "parent_project_name": parent_title,
            "followup_project_id": _text(followup_payload.get("idea_id")),
            "followup_title": _text(followup_payload.get("title")),
            "followup_type": _text(followup_payload.get("followup_type")),
            "decision_payload_json": candidate.get("decision_payload_json")
            if isinstance(candidate.get("decision_payload_json"), dict)
            else {},
        },
    }


def _source_id_for_url(url: str) -> str:
    return f"url-{hashlib.sha256(_text(url).encode('utf-8')).hexdigest()[:24]}"


def _candidate_source_records(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_ids: set[str] = set()
    for source in candidate.get("source_records") or []:
        if not isinstance(source, dict):
            continue
        url = _text(source.get("url"))
        source_id = _text(source.get("source_id")) or (
            _source_id_for_url(url) if url else ""
        )
        if not source_id or source_id in seen_ids:
            continue
        record = {
            "source_id": source_id,
            "source_kind": _text(
                source.get("source_kind") or candidate.get("source_kind") or "other"
            ),
            "title": _text(source.get("title") or candidate.get("title")),
            "url": url,
            "external_id": _text(source.get("external_id")),
            "retrieved_at": _text(source.get("retrieved_at")),
            "summary": _text(source.get("summary")),
            "payload_json": source.get("payload_json")
            if isinstance(source.get("payload_json"), dict)
            else {},
            "content_hash": _text(source.get("content_hash")),
        }
        records.append(record)
        seen_ids.add(source_id)
        if url:
            seen_urls.add(url)
    for raw_url in candidate.get("source_urls") or []:
        url = _text(raw_url)
        if not url or url in seen_urls:
            continue
        source_id = _source_id_for_url(url)
        if source_id in seen_ids:
            continue
        record = {
            "source_id": source_id,
            "source_kind": _text(candidate.get("source_kind") or "other"),
            "title": _text(candidate.get("title")),
            "url": url,
            "external_id": "",
            "retrieved_at": "",
            "summary": "Candidate source URL materialized at Research Facility ledger write time.",
            "payload_json": {"url": url},
            "content_hash": hashlib.sha256(url.encode("utf-8")).hexdigest(),
        }
        records.append(record)
        seen_ids.add(source_id)
        seen_urls.add(url)
    return records


def _unique_candidate_source_ids(
    candidate: dict[str, Any], source_records: list[dict[str, Any]]
) -> list[str]:
    source_ids: list[str] = []
    for source_id in [
        *list(candidate.get("source_ids") or []),
        *[_text(source.get("source_id")) for source in source_records],
    ]:
        source_id_text = _text(source_id)
        if source_id_text and source_id_text not in source_ids:
            source_ids.append(source_id_text)
    return source_ids


def _candidate_source_url_list(candidate: dict[str, Any]) -> list[str]:
    return [_text(url) for url in (candidate.get("source_urls") or []) if _text(url)]


def _research_candidate_rejection_reason(plan_json: dict[str, Any]) -> str:
    if plan_json.get("admission_decision") != "rejected":
        return ""
    return str(plan_json.get("admission_reason") or "")


def _research_candidate_text_value(
    candidate: dict[str, Any], key: str, default: str = ""
) -> str:
    return str(candidate.get(key) or default)


def _research_candidate_float_value(candidate: dict[str, Any], key: str) -> float:
    return float(candidate.get(key) or 0)


def _research_candidate_json_value(
    candidate: dict[str, Any], key: str, default: Any
) -> Any:
    return candidate.get(key) or default


def _plan_to_json(plan: Any) -> dict[str, Any]:
    if hasattr(plan, "to_json"):
        return plan.to_json()
    return dict(plan)


def _internal_project_source_record(
    project_id: str,
    title: str,
    *,
    source_kind: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_project_id = _text(project_id)
    clean_title = _text(title) or clean_project_id
    source_id = f"internal_generated:{clean_project_id}"
    payload_json = {
        "project_id": clean_project_id,
        "project_name": clean_title,
        "source_kind": _text(source_kind),
        **(payload or {}),
    }
    return {
        "source_id": source_id,
        "source_kind": "internal_generated",
        "title": f"Internal Enoch project: {clean_title}",
        "url": "",
        "external_id": clean_project_id,
        "summary": "Deterministic source record for an operator/native project without external source lineage.",
        "payload_json": payload_json,
    }


def _record_internal_project_source_lineage(
    cur: Any,
    *,
    project_id: str,
    title: str,
    source_kind: str = "",
    payload: dict[str, Any] | None = None,
) -> int:
    source = _internal_project_source_record(
        project_id, title, source_kind=source_kind, payload=payload
    )
    cur.execute(
        """
        insert into research_sources(source_id, source_kind, title, url, external_id, retrieved_at, summary, payload_json, content_hash)
        values (%s,%s,%s,%s,%s,null,%s,%s::jsonb,%s)
        on conflict (source_id) do update set
          source_kind=excluded.source_kind,
          title=excluded.title,
          url=excluded.url,
          external_id=excluded.external_id,
          summary=excluded.summary,
          payload_json=excluded.payload_json,
          content_hash=excluded.content_hash,
          updated_at=now()
        """,
        (
            source["source_id"],
            source["source_kind"],
            source["title"],
            source["url"],
            source["external_id"],
            source["summary"],
            _json(source["payload_json"]),
            hashlib.sha256(_json(source["payload_json"]).encode("utf-8")).hexdigest(),
        ),
    )
    cur.execute(
        """
        insert into research_lineage(source_type, source_id, target_type, target_id, relation_type, evidence_json)
        select source_type, source_id, target_type, target_id, relation_type, evidence_json::jsonb
        from (values
          ('source', %s, 'idea', %s, 'generated_from', %s),
          ('idea', %s, 'project', %s, 'queued_as', %s)
        ) as v(source_type, source_id, target_type, target_id, relation_type, evidence_json)
        where not exists (
          select 1 from research_lineage rl
          where rl.source_type=v.source_type and rl.source_id=v.source_id
            and rl.target_type=v.target_type and rl.target_id=v.target_id
            and rl.relation_type=v.relation_type
        )
        """,
        (
            source["source_id"],
            _text(project_id),
            _json({"source_id": source["source_id"], "captured_by": "idea_intake"}),
            _text(project_id),
            _text(project_id),
            _json({"queued_by": "idea_intake"}),
        ),
    )
    return int(getattr(cur, "rowcount", 0) or 0)


def _persist_notion_intake_candidate(
    cur: Any,
    candidate: dict[str, Any],
    *,
    now: str,
    override_existing_dispatch_metadata: bool,
) -> str:
    raw = candidate["source_row"]
    existed = (
        cur.execute(
            "select 1 from queue_items where project_id = %s",
            (candidate["project_id"],),
        ).fetchone()
        is not None
    )
    cur.execute(
        """
        insert into projects(project_id,project_name,project_dir,notion_page_url,notion_page_id,origin_idea_status,created_at,updated_at)
        values (%s,%s,%s,%s,%s,%s,%s,%s)
        on conflict (project_id) do update set
          project_name=excluded.project_name,
          project_dir=projects.project_dir,
          notion_page_url=coalesce(nullif(excluded.notion_page_url,''), projects.notion_page_url),
          notion_page_id=coalesce(nullif(excluded.notion_page_id,''), projects.notion_page_id),
          origin_idea_status=coalesce(nullif(excluded.origin_idea_status,''), projects.origin_idea_status),
          updated_at=excluded.updated_at
        """,
        (
            candidate["project_id"],
            candidate["project_name"],
            candidate["project_dir"],
            candidate["notion_page_url"],
            candidate["notion_page_id"],
            candidate["origin_idea_status"],
            now,
            now,
        ),
    )
    if existed:
        if override_existing_dispatch_metadata:
            cur.execute(
                """
                update queue_items
                set selection_rank=%s, dispatch_priority=%s, machine_target=%s, model=%s, sandbox=%s, updated_at=%s
                where project_id=%s and status not in ('dispatching','running','awaiting_wake','wake_received','reconciling')
                """,
                (
                    candidate["selection_rank"],
                    candidate["dispatch_priority"],
                    candidate["machine_target"],
                    candidate["model"],
                    candidate["sandbox"],
                    now,
                    candidate["project_id"],
                ),
            )
        else:
            cur.execute(
                """
                update queue_items
                set selection_rank=%s, dispatch_priority=%s, updated_at=%s
                where project_id=%s and status not in ('dispatching','running','awaiting_wake','wake_received','reconciling')
                """,
                (
                    candidate["selection_rank"],
                    candidate["dispatch_priority"],
                    now,
                    candidate["project_id"],
                ),
            )
        outcome = "updated"
    else:
        cur.execute(
            """
            insert into queue_items(project_id,status,selection_rank,dispatch_priority,auto_continue,continue_count,max_continues,retry_count,max_retries,current_run_id,current_session_id,last_run_state,last_event_type,next_action_hint,manual_review_required,blocked_reason,last_error,last_result_summary,machine_target,model,sandbox,last_dispatch_at,last_callback_at,stale_after,updated_at)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                candidate["project_id"],
                QueueStatus.QUEUED.value,
                candidate["selection_rank"],
                candidate["dispatch_priority"],
                True,
                0,
                0,
                0,
                2,
                "",
                "",
                "",
                "",
                candidate["next_action_hint"],
                False,
                "",
                "",
                "",
                candidate["machine_target"],
                candidate["model"],
                candidate["sandbox"],
                None,
                None,
                None,
                now,
            ),
        )
        outcome = "created"
    _record_internal_project_source_lineage(
        cur,
        project_id=candidate["project_id"],
        title=candidate["project_name"],
        source_kind=candidate["source_kind"],
        payload={"source_payload_json": raw if isinstance(raw, dict) else {}},
    )
    return outcome


def _idea_intake_ideas_row_values(
    candidate: dict[str, Any], raw: dict[str, Any], *, now: str
) -> tuple[Any, ...]:
    return (
        candidate["project_id"],
        candidate["project_name"],
        candidate["origin_idea_status"],
        _text(_first_present(raw, "category", "property_category")),
        _text(_first_present(raw, "priority", "property_priority")),
        candidate["source_kind"],
        _text(_first_present(raw, "source_external_id", "external_id")),
        _text(_first_present(raw, "source_external_url", "external_url", "url")),
        _text(_first_present(raw, "description", "property_description")),
        _text(_first_present(raw, "implementation", "property_implementation")),
        _text(_first_present(raw, "baseline_to_beat", "property_baseline_to_beat")),
        _text(_first_present(raw, "kill_condition", "property_kill_condition")),
        _text(
            _first_present(raw, "accessibility_delta", "property_accessibility_delta")
        ),
        _text(_first_present(raw, "experiment_results", "property_experiment_results")),
        _text(
            _first_present(
                raw, "expected_token_budget", "property_expected_token_budget"
            )
        ),
        _text(_first_present(raw, "confidence", "property_confidence")),
        _text(_first_present(raw, "feasibility", "property_feasibility")),
        _text(_first_present(raw, "leverage", "property_leverage")),
        _text(_first_present(raw, "novelty_score", "property_novelty_score")),
        _text(_first_present(raw, "signal_speed", "property_signal_speed")),
        _text(_first_present(raw, "teacher_dependence", "property_teacher_dependence")),
        candidate["machine_target"],
        candidate["model"],
        candidate["sandbox"],
        candidate["selection_rank"],
        candidate["dispatch_priority"],
        _json(raw),
        now,
        now,
    )


def _persist_idea_intake_candidate(
    cur: Any,
    candidate: dict[str, Any],
    *,
    now: str,
    override_existing_dispatch_metadata: bool,
) -> str:
    raw = candidate["source_row"]
    existed = (
        cur.execute(
            "select 1 from queue_items where project_id = %s",
            (candidate["project_id"],),
        ).fetchone()
        is not None
    )
    cur.execute(
        """
        insert into ideas(
          idea_id, title, idea_status, category, priority, source_kind, source_external_id, source_external_url,
          description, implementation, baseline_to_beat, kill_condition, accessibility_delta, experiment_results,
          expected_token_budget, confidence, feasibility, leverage, novelty_score, signal_speed, teacher_dependence,
          machine_target, model, sandbox, selection_rank, dispatch_priority, source_payload_json, created_at, updated_at
        ) values (
          %s,%s,%s,%s,%s,%s,%s,%s,
          %s,%s,%s,%s,%s,%s,
          %s,%s,%s,%s,%s,%s,%s,
          %s,%s,%s,%s,%s,%s::jsonb,%s,%s
        )
        on conflict (idea_id) do update set
          title=excluded.title, idea_status=excluded.idea_status, category=excluded.category, priority=excluded.priority,
          source_kind=excluded.source_kind, source_external_id=excluded.source_external_id,
          source_external_url=excluded.source_external_url, description=excluded.description,
          implementation=excluded.implementation, baseline_to_beat=excluded.baseline_to_beat,
          kill_condition=excluded.kill_condition, accessibility_delta=excluded.accessibility_delta,
          experiment_results=excluded.experiment_results, expected_token_budget=excluded.expected_token_budget,
          confidence=excluded.confidence, feasibility=excluded.feasibility, leverage=excluded.leverage,
          novelty_score=excluded.novelty_score, signal_speed=excluded.signal_speed,
          teacher_dependence=excluded.teacher_dependence, machine_target=excluded.machine_target,
          model=excluded.model, sandbox=excluded.sandbox, selection_rank=excluded.selection_rank,
          dispatch_priority=excluded.dispatch_priority, source_payload_json=excluded.source_payload_json,
          updated_at=excluded.updated_at
        """,
        _idea_intake_ideas_row_values(candidate, raw, now=now),
    )
    cur.execute(
        """
        insert into projects(project_id,project_name,project_dir,notion_page_url,notion_page_id,origin_idea_status,created_at,updated_at)
        values (%s,%s,%s,'','',%s,%s,%s)
        on conflict (project_id) do update set
          project_name=excluded.project_name, project_dir=excluded.project_dir,
          origin_idea_status=coalesce(nullif(excluded.origin_idea_status,''), projects.origin_idea_status),
          updated_at=excluded.updated_at
        """,
        (
            candidate["project_id"],
            candidate["project_name"],
            candidate["project_dir"],
            candidate["origin_idea_status"],
            now,
            now,
        ),
    )
    if existed:
        if override_existing_dispatch_metadata:
            cur.execute(
                """
                update queue_items
                set selection_rank=%s, dispatch_priority=%s, machine_target=%s, model=%s, sandbox=%s, updated_at=%s
                where project_id=%s and status not in ('dispatching','running','awaiting_wake','wake_received','reconciling')
                """,
                (
                    candidate["selection_rank"],
                    candidate["dispatch_priority"],
                    candidate["machine_target"],
                    candidate["model"],
                    candidate["sandbox"],
                    now,
                    candidate["project_id"],
                ),
            )
        else:
            cur.execute(
                """
                update queue_items
                set selection_rank=%s, dispatch_priority=%s, updated_at=%s
                where project_id=%s and status not in ('dispatching','running','awaiting_wake','wake_received','reconciling')
                """,
                (
                    candidate["selection_rank"],
                    candidate["dispatch_priority"],
                    now,
                    candidate["project_id"],
                ),
            )
        outcome = "updated"
    else:
        cur.execute(
            """
            insert into queue_items(project_id,status,selection_rank,dispatch_priority,auto_continue,continue_count,max_continues,retry_count,max_retries,current_run_id,current_session_id,last_run_state,last_event_type,next_action_hint,manual_review_required,blocked_reason,last_error,last_result_summary,machine_target,model,sandbox,last_dispatch_at,last_callback_at,stale_after,updated_at)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                candidate["project_id"],
                QueueStatus.QUEUED.value,
                candidate["selection_rank"],
                candidate["dispatch_priority"],
                True,
                0,
                0,
                0,
                2,
                "",
                "",
                "",
                "",
                candidate["next_action_hint"],
                False,
                "",
                "",
                "",
                candidate["machine_target"],
                candidate["model"],
                candidate["sandbox"],
                None,
                None,
                None,
                now,
            ),
        )
        outcome = "created"
    _record_internal_project_source_lineage(
        cur,
        project_id=candidate["project_id"],
        title=candidate["project_name"],
        source_kind=candidate["source_kind"],
        payload={"source_payload_json": raw if isinstance(raw, dict) else {}},
    )
    return outcome


def _followup_depth_from_payload(payload: dict[str, Any] | None) -> int:
    if not isinstance(payload, dict):
        return 0
    source = (
        payload.get("source_payload_json")
        if isinstance(payload.get("source_payload_json"), dict)
        else payload
    )
    try:
        return int(
            source.get("followup_depth") or source.get("parent_followup_depth") or 0
        )
    except (TypeError, ValueError):
        return 0


def _enforced_followup_depth(
    decision_payload: dict[str, Any], *lineage_payloads: dict[str, Any] | None
) -> int:
    """Never let worker output reset controller-owned follow-up lineage depth."""

    return max(
        [
            _followup_depth_from_payload(decision_payload),
            *[_followup_depth_from_payload(payload) for payload in lineage_payloads],
        ]
    )


_RESEARCH_LADDER_TIERS: dict[int, tuple[str, str, str]] = {
    0: ("Tier 0", "smoke/proxy falsification", "small"),
    1: ("Tier 1", "controlled small direct test", "medium"),
    2: (
        "Tier 2",
        "medium confirmation with fixed seeds, ablations, and a real baseline",
        "large",
    ),
    3: ("Tier 3", "bounded full validation up to roughly 24 hours", "large"),
    4: ("Tier 4", "paper-readiness replication and robustness", "large"),
}


def _jsonish_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _jsonish_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _project_decision_payload_from_candidate(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    payload = _jsonish_dict(candidate.get("decision_payload_json"))
    nested = payload.get("project_decision")
    if isinstance(nested, dict):
        return nested
    return payload


def _followup_required_evidence_items(candidate: dict[str, Any]) -> list[Any]:
    return [
        _text(item)
        for item in _jsonish_list(candidate.get("followup_required_evidence"))
        if _text(item)
    ]


def _has_concrete_followup(candidate: dict[str, Any]) -> bool:
    return (
        bool(_text(candidate.get("followup_title")))
        and bool(_text(candidate.get("followup_hypothesis")))
        and len(_followup_required_evidence_items(candidate)) >= 2
        and bool(_text(candidate.get("followup_success_threshold")))
        and bool(_text(candidate.get("followup_stop_condition")))
    )


def _followup_escalation_payload(
    candidate: dict[str, Any], next_depth: int
) -> dict[str, Any]:
    decision = _project_decision_payload_from_candidate(candidate)
    hypothesis_status = _text(decision.get("hypothesis_status")).lower()
    evidence_strength = _text(decision.get("evidence_strength")).lower()
    project_decision = _text(
        decision.get("project_decision") or decision.get("decision")
    ).lower()
    concrete = _has_concrete_followup(candidate)
    promising = (
        project_decision == "finalize_negative"
        and hypothesis_status in {"mixed", "supported"}
        and evidence_strength in {"moderate", "strong"}
        and concrete
        and next_depth <= 3
    )
    if promising:
        tier = max(1, min(3, next_depth))
    else:
        tier = max(0, min(4, next_depth))
    tier_name, tier_label, budget = _RESEARCH_LADDER_TIERS[tier]
    guidance = [
        f"Minimum validation target: {tier_name} - {tier_label}.",
        "Do not close this follow-up on another tiny proxy unless it directly falsifies the stated threshold.",
        "Keep the paper gate strict: mechanism support is not publication readiness.",
    ]
    if tier >= 2:
        guidance.append(
            "Use direct target metrics, fixed seeds where relevant, an ablation/control, and a real baseline."
        )
    if tier >= 3:
        guidance.append(
            "A bounded full validation may spend up to roughly 24 hours if the medium signal still holds."
        )
    return {
        "research_ladder_tier": tier,
        "research_ladder_label": f"{tier_name}: {tier_label}",
        "research_ladder_budget_hint": budget,
        "promising_escalation": promising,
        "escalation_reason": (
            "mixed/supported moderate no-paper result with concrete follow-up evidence"
            if promising
            else "standard bounded follow-up; preserve strict paper gate"
        ),
        "worker_prompt_guidance": guidance,
    }


_GATE_DECISION_VALUE_FIELDS = (
    "project_decision",
    "decision",
    "status",
    "hypothesis_status",
    "verdict",
    "outcome",
    "recommendation",
)


def _gate_value_for_field(values: Sequence[Any], field: str) -> str:
    for item in values:
        if (
            isinstance(item, (list, tuple))
            and len(item) >= 3
            and _text(item[1]) == field
        ):
            return _text(item[2])
    return ""


def _decision_from_gate_values(values: Sequence[Any]) -> str:
    for preferred_field in _GATE_DECISION_VALUE_FIELDS:
        decision = _gate_value_for_field(values, preferred_field)
        if decision:
            return decision
    return ""


def _decision_summary(gate: dict[str, Any]) -> str:
    reason = _text(gate.get("reason"))
    decision = _text(gate.get("decision")) or _decision_from_gate_values(
        gate.get("values") or []
    )
    if decision and reason:
        return f"{decision} ({reason})"
    return decision or reason


def _unresolved_artifact(field: str, raw_path: str) -> dict[str, Any]:
    return {
        "field": field,
        "path": raw_path,
        "absolute_path": "",
        "exists": False,
        "readable": False,
        "safe": False,
        "size_bytes": 0,
    }


def _resolve_artifact_path(path: Path, project_dir: Path | None) -> Path | None:
    try:
        if path.is_absolute():
            candidate = path
        elif project_dir:
            candidate = project_dir / path
        else:
            candidate = path
        return candidate.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _artifact_path_is_safe(resolved: Path, project_dir: Path | None) -> bool:
    if project_dir is None:
        return True
    try:
        resolved.relative_to(project_dir.resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _artifact_file_stats(
    resolved: Path, raw_path: str, safe: bool
) -> tuple[bool, bool, int]:
    try:
        exists = bool(raw_path) and resolved.exists()
        readable = safe and exists and resolved.is_file()
        size_bytes = resolved.stat().st_size if readable else 0
        return exists, readable, size_bytes
    except (OSError, RuntimeError, ValueError):
        return bool(raw_path), False, 0


_QUEUE_PAPER_RUN_SCOPE = (
    "where pa.project_id = q.project_id\n"
    "  and (coalesce(q.current_run_id, '') = '' or pa.run_id = q.current_run_id)"
)

_PROJECT_DECISION_SCOPE = (
    "where d.project_id = q.project_id\n"
    "  and (d.run_id = nullif(q.current_run_id, '') or d.run_id is null)"
)

_PROJECT_DECISION_ORDER = (
    "order by case when d.run_id = nullif(q.current_run_id, '') then 0 else 1 end,"
    " d.decided_at desc nulls last, d.decision_id desc nulls last"
)


def _queue_paper_scalar_subquery(select_expr: str, alias: str) -> str:
    return f"""
              (
                select {select_expr}
                from papers pa
                {_QUEUE_PAPER_RUN_SCOPE}
                order by pa.updated_at desc
                limit 1
              ) as {alias}"""


def _queue_paper_review_subquery(select_expr: str, alias: str) -> str:
    return f"""
              (
                select {select_expr}
                from papers pa
                left join publication_automation_items rv using(paper_id)
                {_QUEUE_PAPER_RUN_SCOPE}
                order by pa.updated_at desc
                limit 1
              ) as {alias}"""


def _queue_corpus_subquery(select_expr: str, alias: str) -> str:
    return f"""
              (
                select {select_expr}
                from papers pa
                left join corpus_imports ci using(paper_id)
                {_QUEUE_PAPER_RUN_SCOPE}
                order by pa.updated_at desc
                limit 1
              ) as {alias}"""


def _queue_project_decision_subquery(select_expr: str, alias: str) -> str:
    return f"""
              (
                select {select_expr}
                from project_decisions d
                {_PROJECT_DECISION_SCOPE}
                {_PROJECT_DECISION_ORDER}
                limit 1
              ) as {alias}"""


def _queue_project_decision_json_field_subquery(json_field: str, alias: str) -> str:
    return _queue_project_decision_subquery(
        (
            f"coalesce(d.payload_json->'project_decision'->>'{json_field}',"
            f" d.payload_json->>'{json_field}')"
        ),
        alias,
    )


def _queue_rows_related_projection_sql() -> str:
    paper_scalars = (
        ("pa.paper_id", "related_paper_id"),
        ("pa.paper_status", "related_paper_status"),
        ("pa.draft_markdown_path", "related_draft_markdown_path"),
        ("pa.evidence_bundle_path", "related_evidence_bundle_path"),
        ("pa.claim_ledger_path", "related_claim_ledger_path"),
        ("pa.manifest_path", "related_manifest_path"),
    )
    review_scalars = (
        ("rv.automation_status", "related_review_status"),
        ("rv.finalization_package_path", "related_finalization_package_path"),
    )
    corpus_scalars = (
        ("ci.corpus_import_id", "related_corpus_import_id"),
        ("ci.artifact_slug", "related_artifact_slug"),
        ("ci.source_record_fingerprint", "related_source_record_fingerprint"),
        ("(ci.paper_id is not null)", "related_corpus_imported"),
    )
    decision_columns = (
        ("d.decision_gate_state", "decision_gate_state"),
        ("d.decision_summary", "decision_summary"),
        ("d.payload_json", "decision_payload_json"),
        ("d.followup_recommended", "followup_recommended"),
        ("d.followup_type", "followup_type"),
        ("d.followup_title", "followup_title"),
        ("d.followup_hypothesis", "followup_hypothesis"),
        ("d.followup_required_evidence", "followup_required_evidence"),
        ("d.followup_success_threshold", "followup_success_threshold"),
        ("d.followup_stop_condition", "followup_stop_condition"),
        ("d.followup_depth", "followup_depth"),
    )
    decision_json_fields = (
        ("project_decision", "project_decision"),
        ("research_outcome", "research_outcome"),
        ("bounded_paper_ready", "bounded_paper_ready"),
        ("hypothesis_status", "hypothesis_status"),
        ("evidence_strength", "evidence_strength"),
        ("claim_scope", "claim_scope"),
        ("scale_limits", "scale_limits"),
    )
    parts = [
        *(_queue_paper_scalar_subquery(expr, alias) for expr, alias in paper_scalars),
        *(_queue_paper_review_subquery(expr, alias) for expr, alias in review_scalars),
        *(_queue_corpus_subquery(expr, alias) for expr, alias in corpus_scalars),
        *(
            _queue_project_decision_subquery(expr, alias)
            for expr, alias in decision_columns
        ),
        *(
            _queue_project_decision_json_field_subquery(field, alias)
            for field, alias in decision_json_fields
        ),
        """
              exists (
                select 1
                from control_events ev
                where ev.event_type = 'followup.launch'
                  and ev.entity_type = 'project'
                  and ev.entity_id = q.project_id
              ) as followup_launched""",
    ]
    return ",\n".join(parts)


_SUPABASE_EVENT_PAGE_ORDER_BY = {
    "type": "event_type asc, event_id desc",
    "entity": "entity_type asc, entity_id asc, event_id desc",
}


def _supabase_event_page_filter_clauses(
    *,
    event_id: str = "",
    entity_type: str = "",
    entity_id: str = "",
    event_type: str = "",
    search: str = "",
) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    event_id_int = _int(event_id, 0)
    if event_id_int > 0:
        clauses.append("event_id = %s")
        params.append(event_id_int)
    if entity_type:
        clauses.append("entity_type = %s")
        params.append(entity_type)
    if entity_id:
        clauses.append("entity_id = %s")
        params.append(entity_id)
    if event_type:
        clauses.append("event_type = %s")
        params.append(event_type)
    if search:
        clauses.append("(event_type ilike %s or entity_id ilike %s)")
        needle = f"%{search}%"
        params.extend([needle, needle])
    return clauses, params


def _supabase_event_page_sort_plan(
    sort: str, cursor_id: int
) -> tuple[str, list[str], list[Any], bool]:
    if sort == "oldest":
        extra_clauses: list[str] = []
        extra_params: list[Any] = []
        if cursor_id > 0:
            extra_clauses.append("event_id > %s")
            extra_params.append(cursor_id)
        return "event_id asc", extra_clauses, extra_params, True
    if sort == "recent":
        extra_clauses = []
        extra_params = []
        if cursor_id > 0:
            extra_clauses.append("event_id < %s")
            extra_params.append(cursor_id)
        return "event_id desc", extra_clauses, extra_params, True
    order_by = _SUPABASE_EVENT_PAGE_ORDER_BY.get(sort, "event_id desc")
    return order_by, [], [], False


def _supabase_event_page_select_list(*, include_payload: bool) -> str:
    if include_payload:
        return """
            event_id,
            idempotency_key,
            event_type,
            entity_type,
            entity_id,
            payload_json,
            created_at
        """
    return """
        event_id,
        idempotency_key,
        event_type,
        entity_type,
        entity_id,
        pg_column_size(payload_json) as payload_bytes,
        created_at
    """


def _supabase_event_page_item(
    row: dict[str, Any],
    *,
    include_payload: bool,
    payload_fn: Callable[[Any], Any],
) -> dict[str, Any]:
    item = dict(row)
    if include_payload:
        item["payload"] = payload_fn(item.pop("payload_json"))
    else:
        item["payload_summary"] = {
            "keys": [],
            "bytes": int(item.pop("payload_bytes") or 0),
        }
    item["created_at"] = str(item.get("created_at") or "")
    return item


def _supabase_event_page_next_cursor(
    *,
    uses_event_id_cursor: bool,
    has_more: bool,
    out: list[dict[str, Any]],
    cursor_id: int,
    safe_size: int,
) -> str | None:
    if not has_more or not out:
        return None
    if uses_event_id_cursor:
        return str(out[-1]["event_id"])
    return str(max(0, cursor_id) + safe_size)


class ReadOnlyStoreError(RuntimeError):
    """Raised when a write path is attempted through the Supabase read adapter."""


class SupabaseReadOnlyControlPlaneStore:
    """Read-only Postgres adapter for the Enoch control-plane schema.

    This adapter is intentionally narrow. It supports dashboard/status parity
    reads against the private `enoch` schema and rejects mutation attempts so a
    config flag cannot silently cut production writes over to Supabase.
    """

    def __init__(
        self, database_url: str, *, connect: ConnectionFactory | None = None
    ) -> None:
        self.database_url = database_url.strip()
        if not self.database_url:
            raise ValueError("supabase_database_url is required for supabase backends")
        self._connect_factory = connect or self._psycopg_connect
        self._external_connect_factory = connect is not None
        self._conn: Any | None = None
        self._conn_lock = threading.Lock()

    def _psycopg_connect(self) -> Any:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except (
            ImportError
        ) as exc:  # pragma: no cover - dependency is declared in pyproject.
            raise RuntimeError(
                "psycopg is required for the Supabase control-plane adapter"
            ) from exc
        return psycopg.connect(self.database_url, row_factory=dict_row)

    @contextmanager
    def _connect(self) -> Iterator[Any]:
        if self._external_connect_factory:
            conn = self._connect_factory()
            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute("set search_path to enoch, public")
                    yield conn
            finally:
                close = getattr(conn, "close", None)
                if callable(close):
                    close()
            return

        self._conn_lock.acquire()
        conn = None
        try:
            try:
                conn = self._conn
                if conn is None or bool(getattr(conn, "closed", False)):
                    conn = self._connect_factory()
                    with conn.cursor() as cur:
                        cur.execute("set statement_timeout to '45s'")
                        cur.execute("set idle_in_transaction_session_timeout to '30s'")
                    self._conn = conn
                # Supabase pooler/transaction boundaries can reset session settings.
                # Keep the persistent server-side connection, but assert the private
                # schema on every checkout so subsequent dashboard reads do not drift
                # back to `public`. This pre-yield section must also release the
                # mutex on failure; otherwise a DB restart can permanently wedge all
                # dashboard worker threads behind _conn_lock.
                with conn.cursor() as cur:
                    cur.execute("set search_path to enoch, public")
            except Exception as exc:
                if conn is not None:
                    rollback = getattr(conn, "rollback", None)
                    if callable(rollback):
                        rollback()
                    if bool(
                        getattr(conn, "closed", False)
                    ) or self._is_transient_connection_error(exc):
                        close = getattr(conn, "close", None)
                        if callable(close):
                            close()
                        self._conn = None
                raise
            try:
                yield conn
                conn.commit()
            except Exception as exc:
                rollback = getattr(conn, "rollback", None)
                if callable(rollback):
                    rollback()
                if bool(
                    getattr(conn, "closed", False)
                ) or self._is_transient_connection_error(exc):
                    close = getattr(conn, "close", None)
                    if callable(close):
                        close()
                    self._conn = None
                raise
        finally:
            self._conn_lock.release()

    @staticmethod
    def _is_transient_connection_error(exc: Exception) -> bool:
        text = f"{type(exc).__name__}: {exc}".lower()
        return any(
            token in text
            for token in (
                "connection is lost",
                "connection to database closed",
                "edbhandlerexited",
                "server closed the connection",
            )
        )

    def _query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                with self._connect() as conn:
                    with conn.cursor() as cur:
                        cur.execute(sql, tuple(params))
                        rows = cur.fetchall()
                return [dict(row) for row in rows]
            except Exception as exc:
                last_exc = exc
                if attempt < 2 and self._is_transient_connection_error(exc):
                    time.sleep(0.25 * (attempt + 1))
                    continue
                raise
        assert last_exc is not None
        raise last_exc

    @staticmethod
    def _cursor_rows(
        cur: Any, sql: str, params: Sequence[Any] = ()
    ) -> list[dict[str, Any]]:
        cur.execute(sql, tuple(params))
        return [dict(row) for row in cur.fetchall()]

    def _one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        rows = self._query(sql, params)
        return rows[0] if rows else None

    @staticmethod
    def _payload(value: Any) -> Any:
        if isinstance(value, str):
            return json.loads(value or "{}")
        return value if value is not None else {}

    @staticmethod
    def _json_text(value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(
            value if value is not None else {}, sort_keys=True, separators=(",", ":")
        )

    @staticmethod
    def _row_value(row: Any, key: str, index: int) -> Any:
        if isinstance(row, dict):
            return row.get(key)
        return row[index]

    def _insert_research_admission(
        self,
        cur: Any,
        *,
        candidate_id: str,
        admission_decision: str,
        admission_reason: str,
        score_breakdown: Any,
        admitted_idea_id: str | None,
        operator: str,
        idempotency_key: str,
    ) -> int:
        score_json = self._json_text(score_breakdown)
        cur.execute(
            """
            select admission_id, candidate_id, admission_decision, admission_reason, score_breakdown, admitted_idea_id, operator
            from research_admissions
            where idempotency_key = %s
            """,
            (idempotency_key,),
        )
        existing = cur.fetchone()
        expected_idea_id = admitted_idea_id or None
        if existing and (
            self._row_value(existing, "candidate_id", 1) != candidate_id
            or self._row_value(existing, "admission_decision", 2) != admission_decision
            or self._row_value(existing, "admission_reason", 3) != admission_reason
            or self._json_text(self._row_value(existing, "score_breakdown", 4))
            != score_json
            or (self._row_value(existing, "admitted_idea_id", 5) or None)
            != expected_idea_id
            or self._row_value(existing, "operator", 6) != operator
        ):
            raise IdempotencyConflict(
                f"idempotency key {idempotency_key!r} was reused with different admission identity"
            )
        if existing:
            return 0
        cur.execute(
            """
            insert into research_admissions(candidate_id, admission_decision, admission_reason, score_breakdown, admitted_idea_id, operator, idempotency_key)
            values (%s,%s,%s,%s::jsonb,%s,%s,%s)
            on conflict (idempotency_key) do nothing
            """,
            (
                candidate_id,
                admission_decision,
                admission_reason,
                score_json,
                admitted_idea_id,
                operator,
                idempotency_key,
            ),
        )
        return int(cur.rowcount or 0)

    def _read_only(self, *_args: Any, **_kwargs: Any) -> None:
        raise ReadOnlyStoreError(
            "Supabase control-plane adapter is read-only in this migration phase"
        )

    append_event = _read_only
    import_snapshot = _read_only
    pause = _read_only
    resume = _read_only
    upsert_dashboard_observation = _read_only

    def flags(self) -> ControlFlags:
        row = self._one("select * from control_flags where singleton = true")
        if not row:
            return ControlFlags()
        return ControlFlags(
            queue_paused=bool(row["queue_paused"]),
            maintenance_mode=bool(row["maintenance_mode"]),
            pause_reason=_text(row["pause_reason"]),
            paused_at=str(row["paused_at"])
            if row.get("paused_at") is not None
            else None,
            paused_by=_text(row["paused_by"]),
            updated_at=str(row["updated_at"]),
        )

    def queue_counts_sql(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self._query(STATUS_COUNT_QUERY):
            status = _text(row["status"]) or "unknown"
            count = int(row["count"] or 0)
            counts[status] = count
            counts["all"] = counts.get("all", 0) + count
            if status in ACTIVE_STATUSES:
                counts["active"] = counts.get("active", 0) + count
            # The status bucket key already records queued/paused counts.
            # Do not add the same row count twice under the same public key.
            if status == QueueStatus.CANCELED.value:
                counts["completed"] = counts.get("completed", 0) + count
        blocked = self._one(
            """
            select count(*) as count
            from queue_items
            where manual_review_required = true or status in (%s, %s, %s)
            """,
            (
                QueueStatus.BLOCKED.value,
                QueueStatus.NEEDS_REVIEW.value,
                QueueStatus.DISPATCH_ERROR.value,
            ),
        )
        counts["blocked"] = int((blocked or {}).get("count") or 0)
        for key in ("all", "active", "queued", "blocked", "paused", "completed"):
            counts.setdefault(key, 0)
        return counts

    def paper_counts_sql(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self._query(
            "select paper_status, count(*) as count from papers group by paper_status"
        ):
            status = _text(row["paper_status"]) or "unknown"
            count = int(row["count"] or 0)
            counts[status] = count
            counts["all"] = counts.get("all", 0) + count
        counts.setdefault("all", 0)
        return counts

    def queue_rows(self) -> list[dict[str, Any]]:
        return self._queue_rows("order by q.dispatch_priority asc, q.updated_at desc")

    def operator_queue_rows_sql(self) -> list[dict[str, Any]]:
        return self._queue_rows(
            """
            where q.status <> %s or q.next_action_hint = %s or q.manual_review_required = true
            order by q.updated_at desc
            """,
            (QueueStatus.CANCELED.value, "draft_paper_or_select_next_project"),
        )

    def active_items_sql(self, *, limit: int = 10) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 50))
        placeholders = ",".join(["%s"] * len(ACTIVE_STATUSES))
        return self._queue_rows(
            f"where q.status in ({placeholders}) order by q.updated_at desc limit %s",
            (*sorted(ACTIVE_STATUSES), safe_limit),
        )

    def active_items(self) -> list[dict[str, Any]]:
        return self.active_items_sql(limit=50)

    def queued_items_sql(self, *, limit: int = 200) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        return self._queue_rows(
            """
            where q.status = %s and q.manual_review_required = false
            order by q.dispatch_priority asc, q.selection_rank asc, q.updated_at asc
            limit %s
            """,
            (QueueStatus.QUEUED.value, safe_limit),
        )

    def recently_completed_items_sql(self, *, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 200))
        return self._queue_rows(
            """
            where q.status = %s
               or q.last_run_state in (%s, %s, %s, %s)
            order by q.updated_at desc
            limit %s
            """,
            (
                QueueStatus.COMPLETED.value,
                "wake_ready",
                "completed",
                "complete",
                "finished",
                safe_limit,
            ),
        )

    def active_machine_targets(self) -> set[str]:
        return {_normal(row.get("machine_target")) for row in self.active_items()}

    def next_candidate_sql(self) -> dict[str, Any] | None:
        rows = self._queue_rows(
            "where q.status = %s order by q.dispatch_priority asc, q.updated_at desc limit 1",
            (QueueStatus.QUEUED.value,),
        )
        return rows[0] if rows else None

    def next_dispatch_candidate(
        self, *, blocked_machine_targets: set[str] | None = None
    ) -> dict[str, Any] | None:
        if self.flags().queue_paused:
            return None
        blocked = (
            self.active_machine_targets()
            if blocked_machine_targets is None
            else {_normal(item) for item in blocked_machine_targets}
        )
        target_filter = ""
        params: tuple[Any, ...] = (QueueStatus.QUEUED.value,)
        if blocked:
            placeholders = ",".join(["%s"] * len(blocked))
            target_filter = f"and lower(replace(replace(trim(coalesce(q.machine_target, '')), '-', '_'), ' ', '_')) not in ({placeholders})"
            params = (QueueStatus.QUEUED.value, *sorted(blocked))
        rows = self._queue_rows(
            f"""
            where q.status = %s and q.manual_review_required = false
            {target_filter}
            order by q.dispatch_priority asc, q.selection_rank asc, q.updated_at asc
            limit 1
            """,
            params,
        )
        return rows[0] if rows else None

    def _queue_rows_query(self, suffix: str) -> str:
        return f"""
            select q.*,
              p.project_name,
              p.project_dir,
              p.notion_page_url,
              p.notion_page_id,
              p.origin_idea_status,
              {_queue_rows_related_projection_sql()},
              i.source_kind as idea_source_kind,
              coalesce(i.source_payload_json, '{{}}'::jsonb) as idea_source_payload_json,
              case
                when coalesce(i.source_payload_json->>'followup_depth', '') ~ '^[0-9]+$'
                then (i.source_payload_json->>'followup_depth')::integer
                when coalesce(i.source_payload_json->>'parent_followup_depth', '') ~ '^[0-9]+$'
                then (i.source_payload_json->>'parent_followup_depth')::integer
                else 0
              end as source_followup_depth,
              p.created_at as project_created_at,
              p.updated_at as project_updated_at
            from queue_items q
            join projects p using(project_id)
            left join ideas i on i.idea_id = q.project_id
            {suffix}
            """

    def _queue_rows_from_cursor(
        self, cur: Any, suffix: str, params: Sequence[Any] = ()
    ) -> list[dict[str, Any]]:
        return self._cursor_rows(cur, self._queue_rows_query(suffix), params)

    def _queue_rows(
        self, suffix: str, params: Sequence[Any] = ()
    ) -> list[dict[str, Any]]:
        return self._query(self._queue_rows_query(suffix), params)

    def paper_rows(self) -> list[dict[str, Any]]:
        return self._paper_rows("order by pa.updated_at desc")

    def operator_paper_rows_sql(self) -> list[dict[str, Any]]:
        return self.paper_rows()

    def _paper_rows_query(self, suffix: str) -> str:
        return f"""
            select pa.*,
              p.project_name,
              p.project_dir,
              p.notion_page_url,
              p.notion_page_id,
              rv.automation_status as review_status,
              rv.finalization_package_path,
              rv.finalized_at,
              ci.corpus_import_id,
              ci.artifact_slug,
              ci.commit_sha as corpus_commit_sha,
              ci.manifest_path as corpus_manifest_path,
              ci.manifest_hash as corpus_manifest_hash,
              ci.source_record_fingerprint,
              ci.hf_dataset_synced,
              ci.imported_at as corpus_imported_at,
              (ci.paper_id is not null) as corpus_imported
            from papers pa
            left join projects p using(project_id)
            left join publication_automation_items rv using(paper_id)
            left join corpus_imports ci using(paper_id)
            {suffix}
            """

    def _paper_rows_from_cursor(
        self, cur: Any, suffix: str, params: Sequence[Any] = ()
    ) -> list[dict[str, Any]]:
        return self._cursor_rows(cur, self._paper_rows_query(suffix), params)

    def _paper_rows(
        self, suffix: str, params: Sequence[Any] = ()
    ) -> list[dict[str, Any]]:
        return self._query(self._paper_rows_query(suffix), params)

    @staticmethod
    def _page(
        rows: list[dict[str, Any]], page_size: int, cursor: str
    ) -> tuple[list[dict[str, Any]], str | None, bool]:
        safe_size = max(1, min(page_size, 200))
        offset = max(0, _int(cursor, 0))
        page_rows = rows[offset : offset + safe_size]
        has_more = len(rows) > offset + safe_size
        next_cursor = str(offset + safe_size) if has_more else None
        return page_rows, next_cursor, has_more

    @staticmethod
    def _matches(row: dict[str, Any], search: str, keys: Sequence[str]) -> bool:
        needle = search.strip().lower()
        if not needle:
            return True
        return any(needle in _text(row.get(key)).lower() for key in keys)

    @staticmethod
    def _sql_page(
        rows: list[dict[str, Any]], *, page_size: int, cursor: str
    ) -> tuple[list[dict[str, Any]], str | None, bool]:
        safe_size = max(1, min(page_size, 200))
        offset = max(0, _int(cursor, 0))
        page_rows = rows[:safe_size]
        has_more = len(rows) > safe_size
        next_cursor = str(offset + safe_size) if has_more else None
        return page_rows, next_cursor, has_more

    def queue_page(
        self,
        *,
        queue: str = "all",
        status: str = "",
        search: str = "",
        page_size: int = 50,
        cursor: str = "",
        sort: str = "priority",
    ) -> tuple[list[dict[str, Any]], str | None, bool]:
        safe_size = max(1, min(page_size, 200))
        offset = max(0, _int(cursor, 0))
        clauses: list[str] = []
        params: list[Any] = []
        if queue == "active":
            placeholders = ",".join(["%s"] * len(ACTIVE_STATUSES))
            clauses.append(f"q.status in ({placeholders})")
            params.extend(sorted(ACTIVE_STATUSES))
        elif queue == "queued":
            clauses.append("q.status = %s")
            params.append(QueueStatus.QUEUED.value)
        elif queue == "blocked":
            clauses.append(
                "(q.manual_review_required = true or q.status in (%s, %s, %s))"
            )
            params.extend(
                [
                    QueueStatus.BLOCKED.value,
                    QueueStatus.NEEDS_REVIEW.value,
                    QueueStatus.DISPATCH_ERROR.value,
                ]
            )
        elif queue == "paused":
            clauses.append("q.status = %s")
            params.append(QueueStatus.PAUSED.value)
        elif queue == "completed":
            clauses.append("q.status in (%s, %s)")
            params.extend([QueueStatus.COMPLETED.value, QueueStatus.CANCELED.value])
        elif queue not in {"", "all"}:
            clauses.append("q.status = %s")
            params.append(queue)
        if status:
            clauses.append("q.status = %s")
            params.append(status)
        if search:
            needle = f"%{search.strip()}%"
            clauses.append(
                """
                (
                  q.project_id ilike %s
                  or p.project_name ilike %s
                  or q.status ilike %s
                  or q.next_action_hint ilike %s
                  or q.current_run_id ilike %s
                  or q.last_run_state ilike %s
                )
                """
            )
            params.extend([needle, needle, needle, needle, needle, needle])
        where = f"where {' and '.join(clauses)}" if clauses else ""
        if sort == "recent":
            order_by = "q.updated_at desc, q.project_id desc"
        elif sort == "oldest":
            order_by = "q.updated_at asc, q.project_id asc"
        elif sort == "name":
            order_by = "lower(p.project_name) asc, q.updated_at desc"
        elif sort == "status":
            order_by = "q.status asc, q.updated_at desc"
        else:
            order_by = (
                "q.dispatch_priority asc, q.selection_rank asc, q.updated_at desc"
            )
        params.extend([safe_size + 1, offset])
        rows = self._queue_rows(
            f"{where} order by {order_by} limit %s offset %s", tuple(params)
        )
        return self._sql_page(rows, page_size=safe_size, cursor=cursor)

    def project_page(
        self,
        *,
        status: str = "",
        search: str = "",
        page_size: int = 50,
        cursor: str = "",
        sort: str = "recent",
    ) -> tuple[list[dict[str, Any]], str | None, bool]:
        safe_size = max(1, min(page_size, 200))
        offset = max(0, _int(cursor, 0))
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("(p.origin_idea_status = %s or q.status = %s)")
            params.extend([status, status])
        if search:
            needle = f"%{search.strip()}%"
            clauses.append(
                """
                (
                  p.project_id ilike %s
                  or p.project_name ilike %s
                  or p.origin_idea_status ilike %s
                  or coalesce(q.status, '') ilike %s
                  or coalesce(q.current_run_id, '') ilike %s
                )
                """
            )
            params.extend([needle, needle, needle, needle, needle])
        where = f"where {' and '.join(clauses)}" if clauses else ""
        if sort == "oldest":
            order_by = "p.updated_at asc, p.project_id asc"
        elif sort == "created":
            order_by = "p.created_at desc, p.updated_at desc"
        elif sort == "name":
            order_by = "lower(p.project_name) asc, p.updated_at desc"
        elif sort == "status":
            order_by = "coalesce(q.status, p.origin_idea_status) asc, p.updated_at desc"
        else:
            order_by = "p.updated_at desc, p.project_id desc"
        params.extend([safe_size + 1, offset])
        rows = self._query(
            f"""
            select p.project_id,
              p.project_name,
              p.notion_page_url,
              p.notion_page_id,
              p.origin_idea_status,
              p.created_at as project_created_at,
              p.updated_at as project_updated_at,
              q.status as queue_status,
              q.current_run_id as current_run_id,
              q.dispatch_priority as dispatch_priority,
              q.next_action_hint as next_action_hint,
              (select r.run_id from runs r where r.project_id = p.project_id order by r.updated_at desc, r.run_id desc limit 1) as latest_run_id,
              (select r.state from runs r where r.project_id = p.project_id order by r.updated_at desc, r.run_id desc limit 1) as latest_run_state,
              (select pa.paper_id from papers pa where pa.project_id = p.project_id order by pa.updated_at desc limit 1) as related_paper_id,
              (select pa.paper_status from papers pa where pa.project_id = p.project_id order by pa.updated_at desc limit 1) as related_paper_status
            from projects p
            left join queue_items q using(project_id)
            {where}
            order by {order_by}
            limit %s offset %s
            """,
            tuple(params),
        )
        return self._sql_page(rows, page_size=safe_size, cursor=cursor)

    def paper_page(
        self,
        *,
        status: str = "",
        project_id: str = "",
        run_id: str = "",
        search: str = "",
        page_size: int = 50,
        cursor: str = "",
        sort: str = "recent",
    ) -> tuple[list[dict[str, Any]], str | None, bool]:
        safe_size = max(1, min(page_size, 200))
        offset = max(0, _int(cursor, 0))
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("pa.paper_status = %s")
            params.append(status)
        if project_id:
            clauses.append("pa.project_id = %s")
            params.append(project_id)
        if run_id:
            clauses.append("pa.run_id = %s")
            params.append(run_id)
        if search:
            needle = f"%{search.strip()}%"
            clauses.append(
                """
                (
                  pa.paper_id ilike %s
                  or pa.project_id ilike %s
                  or coalesce(pa.run_id, '') ilike %s
                  or pa.paper_status ilike %s
                  or p.project_name ilike %s
                )
                """
            )
            params.extend([needle, needle, needle, needle, needle])
        where = f"where {' and '.join(clauses)}" if clauses else ""
        if sort == "status":
            order_by = "pa.paper_status asc, pa.updated_at desc, pa.paper_id desc"
        elif sort == "title":
            order_by = "lower(coalesce(p.project_name, '')) asc, pa.updated_at desc, pa.paper_id desc"
        elif sort == "oldest":
            order_by = "pa.updated_at asc, pa.paper_id asc"
        else:
            order_by = "pa.updated_at desc, pa.paper_id desc"
        params.extend([safe_size + 1, offset])
        rows = self._paper_rows(
            f"{where} order by {order_by} limit %s offset %s", tuple(params)
        )
        return self._sql_page(rows, page_size=safe_size, cursor=cursor)

    def run_page(
        self,
        *,
        state: str = "",
        project_id: str = "",
        search: str = "",
        page_size: int = 50,
        cursor: str = "",
        sort: str = "recent",
    ) -> tuple[list[dict[str, Any]], str | None, bool]:
        safe_size = max(1, min(page_size, 200))
        offset = max(0, _int(cursor, 0))
        clauses: list[str] = []
        params: list[Any] = []
        if state:
            clauses.append("(r.state = %s or r.gate_state = %s)")
            params.extend([state, state])
        if project_id:
            clauses.append("r.project_id = %s")
            params.append(project_id)
        if search:
            needle = f"%{search.strip()}%"
            clauses.append(
                """
                (
                  r.run_id ilike %s
                  or r.project_id ilike %s
                  or r.session_id ilike %s
                  or r.current_activity ilike %s
                )
                """
            )
            params.extend([needle, needle, needle, needle])
        where = f"where {' and '.join(clauses)}" if clauses else ""
        if sort == "oldest":
            order_by = "r.updated_at asc, r.run_id asc"
        elif sort == "state":
            order_by = "r.state asc, r.updated_at desc, r.run_id desc"
        else:
            order_by = "r.updated_at desc, r.run_id desc"
        params.extend([safe_size + 1, offset])
        rows = self._query(
            f"select r.* from runs r {where} order by {order_by} limit %s offset %s",
            tuple(params),
        )
        return self._sql_page(rows, page_size=safe_size, cursor=cursor)

    def event_page(
        self,
        *,
        event_id: str = "",
        entity_type: str = "",
        entity_id: str = "",
        event_type: str = "",
        search: str = "",
        page_size: int = 50,
        cursor: str = "",
        include_payload: bool = False,
        sort: str = "recent",
    ) -> tuple[list[dict[str, Any]], str | None, bool]:
        safe_size = max(1, min(page_size, 200))
        clauses, params = _supabase_event_page_filter_clauses(
            event_id=event_id,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            search=search,
        )
        cursor_id = _int(cursor, 0)
        order_by, sort_clauses, sort_params, uses_event_id_cursor = (
            _supabase_event_page_sort_plan(sort, cursor_id)
        )
        clauses.extend(sort_clauses)
        params.extend(sort_params)
        where = f"where {' and '.join(clauses)}" if clauses else ""
        select_list = _supabase_event_page_select_list(include_payload=include_payload)

        if uses_event_id_cursor:
            params.append(safe_size + 1)
            rows = self._query(
                f"select {select_list} from control_events {where} order by {order_by} limit %s",
                tuple(params),
            )
        else:
            offset = max(0, cursor_id)
            params.extend([safe_size + 1, offset])
            rows = self._query(
                f"select {select_list} from control_events {where} order by {order_by} limit %s offset %s",
                tuple(params),
            )

        out = [
            _supabase_event_page_item(
                row, include_payload=include_payload, payload_fn=self._payload
            )
            for row in rows[:safe_size]
        ]
        has_more = len(rows) > safe_size
        next_cursor = _supabase_event_page_next_cursor(
            uses_event_id_cursor=uses_event_id_cursor,
            has_more=has_more,
            out=out,
            cursor_id=cursor_id,
            safe_size=safe_size,
        )
        return out, next_cursor, has_more

    def _overview_queue_status_counts(self, cur: Any) -> dict[str, int]:
        counts: dict[str, int] = {}
        blocked_count = 0
        for row in self._cursor_rows(
            cur,
            """
            select
              status,
              count(*) as count,
              (
                select count(*)
                from queue_items
                where manual_review_required = true or status in (%s, %s, %s)
              ) as blocked_count
            from queue_items
            group by status
            """,
            (
                QueueStatus.BLOCKED.value,
                QueueStatus.NEEDS_REVIEW.value,
                QueueStatus.DISPATCH_ERROR.value,
            ),
        ):
            status = _text(row["status"]) or "unknown"
            count = int(row["count"] or 0)
            counts[status] = count
            counts["all"] = counts.get("all", 0) + count
            blocked_count = int(row.get("blocked_count") or 0)
        counts["active"] = sum(counts.get(status, 0) for status in ACTIVE_STATUSES)
        counts["queued"] = counts.get(QueueStatus.QUEUED.value, 0)
        counts["blocked"] = blocked_count
        for key in ("all", "active", "queued", "blocked", "paused", "completed"):
            counts.setdefault(key, 0)
        return counts

    def _overview_paper_status_counts(self, cur: Any) -> dict[str, int]:
        paper_counts: dict[str, int] = {}
        for row in self._cursor_rows(
            cur,
            "select paper_status, count(*) as count from papers group by paper_status",
        ):
            status = _text(row["paper_status"]) or "unknown"
            count = int(row["count"] or 0)
            paper_counts[status] = count
            paper_counts["all"] = paper_counts.get("all", 0) + count
        paper_counts.setdefault("all", 0)
        return paper_counts

    def _overview_active_queue_slice(
        self, cur: Any, *, active_limit: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        safe_active_limit = max(1, min(active_limit, 50))
        placeholders = ",".join(["%s"] * len(ACTIVE_STATUSES))
        active_items = self._queue_rows_from_cursor(
            cur,
            f"where q.status in ({placeholders}) order by q.updated_at desc limit %s",
            (*sorted(ACTIVE_STATUSES), safe_active_limit),
        )
        next_candidates = self._queue_rows_from_cursor(
            cur,
            "where q.status = %s order by q.dispatch_priority asc, q.updated_at desc limit 1",
            (QueueStatus.QUEUED.value,),
        )
        next_candidate = next_candidates[0] if next_candidates else None
        return active_items, next_candidate

    def _overview_operator_queue_rows(self, cur: Any) -> list[dict[str, Any]]:
        return self._cursor_rows(
            cur,
            """
            select
              q.project_id,
              p.project_name,
              q.status,
              q.dispatch_priority,
              q.selection_rank,
              q.current_run_id,
              q.current_session_id,
              q.last_run_state,
              q.next_action_hint,
              q.manual_review_required,
              q.blocked_reason,
              q.last_result_summary,
              q.last_callback_at,
              q.last_dispatch_at,
              q.updated_at,
              p.project_dir,
              p.notion_page_url,
              ''::text as related_paper_id,
              ''::text as related_paper_status,
              ''::text as related_review_status,
              ''::text as related_finalization_package_path,
              ''::text as related_draft_markdown_path,
              ''::text as related_evidence_bundle_path,
              ''::text as related_claim_ledger_path,
              ''::text as related_manifest_path,
              false as related_corpus_imported,
              ''::text as related_corpus_import_id,
              ''::text as related_artifact_slug,
              ''::text as related_source_record_fingerprint,
              coalesce(pe.decision_gate_state, '') as decision_gate_state,
              coalesce(pe.decision_summary, '') as decision_summary,
              coalesce(pe.research_outcome, '') as research_outcome,
              coalesce(pe.hypothesis_status, '') as hypothesis_status,
              coalesce(pe.evidence_strength, '') as evidence_strength,
              coalesce(pe.claim_scope, '') as claim_scope,
              coalesce(pe.scale_limits, '') as scale_limits,
              coalesce(pe.useful_signal_summary, '') as useful_signal_summary,
              coalesce(pe.bounded_paper_ready, false) as bounded_paper_ready,
              coalesce(pe.compute_scale_blocked, false) as compute_scale_blocked,
              coalesce(pe.recommended_next_action, '') as recommended_next_action,
              coalesce(pe.stop_reason, '') as stop_reason,
              coalesce(pe.followup_recommended, false) as followup_recommended,
              coalesce(pe.followup_type, '') as followup_type,
              coalesce(pe.followup_title, '') as followup_title,
              coalesce(pe.followup_hypothesis, '') as followup_hypothesis,
              coalesce(pe.followup_required_evidence, '[]'::jsonb) as followup_required_evidence,
              coalesce(pe.followup_success_threshold, '') as followup_success_threshold,
              coalesce(pe.followup_stop_condition, '') as followup_stop_condition,
              coalesce(pe.followup_depth, 0) as followup_depth,
              case
                when coalesce(i.source_payload_json->>'followup_depth', '') ~ '^[0-9]+$'
                then (i.source_payload_json->>'followup_depth')::integer
                when coalesce(i.source_payload_json->>'parent_followup_depth', '') ~ '^[0-9]+$'
                then (i.source_payload_json->>'parent_followup_depth')::integer
                else 0
              end as source_followup_depth,
              exists (
                select 1
                from control_events ev
                where ev.event_type = 'followup.launch'
                  and ev.entity_type = 'project'
                  and ev.entity_id = q.project_id
              ) as followup_launched
            from queue_items q
            join projects p using(project_id)
            left join paper_eligibility pe on pe.project_id = q.project_id
            left join ideas i on i.idea_id = q.project_id
            where exists (
                select 1
                from paper_eligibility candidate
                where candidate.project_id = q.project_id
                  and (candidate.raw_write_candidate or candidate.followup_recommended)
            )
               or q.manual_review_required = true
               or q.status in (%s, %s, %s)
            order by q.updated_at desc
            """,
            (
                QueueStatus.BLOCKED.value,
                QueueStatus.NEEDS_REVIEW.value,
                QueueStatus.DISPATCH_ERROR.value,
            ),
        )

    def _overview_operator_paper_rows(self, cur: Any) -> list[dict[str, Any]]:
        return self._paper_rows_from_cursor(
            cur,
            """
            where
              (pa.paper_status = %s and rv.automation_status = %s and rv.finalization_package_path <> '' and ci.paper_id is null)
              or ci.paper_id is not null
              or pa.paper_status in (%s, %s, %s)
            order by pa.updated_at desc
            """,
            (
                PaperStatus.PUBLICATION_DRAFT.value,
                ReviewStatus.FINALIZED.value,
                PaperStatus.PUBLICATION_DRAFT.value,
                PaperStatus.DRAFT_REVIEW.value,
                PaperStatus.ARCHIVED.value,
            ),
        )

    def _overview_events_page(
        self, cur: Any, *, event_limit: int
    ) -> tuple[list[dict[str, Any]], str | None, bool]:
        safe_event_limit = max(0, min(event_limit, 50))
        if not safe_event_limit:
            return [], None, False
        event_rows = self._cursor_rows(
            cur,
            """
            select
                event_id,
                idempotency_key,
                event_type,
                entity_type,
                entity_id,
                pg_column_size(payload_json) as payload_bytes,
                created_at
            from control_events
            order by event_id desc
            limit %s
            """,
            (safe_event_limit + 1,),
        )
        events: list[dict[str, Any]] = []
        for row in event_rows[:safe_event_limit]:
            item = dict(row)
            item["payload_summary"] = {
                "keys": [],
                "bytes": int(item.pop("payload_bytes") or 0),
            }
            item["created_at"] = str(item.get("created_at") or "")
            events.append(item)
        event_has_more = len(event_rows) > safe_event_limit
        event_next_cursor = (
            str(events[-1]["event_id"]) if event_has_more and events else None
        )
        return events, event_next_cursor, event_has_more

    def _fetch_overview_read_model_parts(
        self, cur: Any, *, active_limit: int, event_limit: int
    ) -> dict[str, Any]:
        active_items, next_candidate = self._overview_active_queue_slice(
            cur, active_limit=active_limit
        )
        return {
            "counts": self._overview_queue_status_counts(cur),
            "paper_counts": self._overview_paper_status_counts(cur),
            "active_items": active_items,
            "next_candidate": next_candidate,
            "raw_queue_rows": self._overview_operator_queue_rows(cur),
            "raw_paper_rows": self._overview_operator_paper_rows(cur),
            "events_page": self._overview_events_page(cur, event_limit=event_limit),
        }

    def overview_read_model_parts(
        self, *, active_limit: int = 5, event_limit: int = 10
    ) -> dict[str, Any]:
        """Return the overview read-model inputs using one database connection.

        The overview endpoint combines several bounded read models. Running each
        helper through `_query()` opened a fresh Supabase/Postgres connection and
        made the dashboard latency mostly connection setup time. Keep the public
        read-model semantics in `read_models.overview()` while batching the SQL
        reads for this adapter only.
        """

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                with self._connect() as conn:
                    with conn.cursor() as cur:
                        return self._fetch_overview_read_model_parts(
                            cur,
                            active_limit=active_limit,
                            event_limit=event_limit,
                        )
            except Exception as exc:
                last_exc = exc
                if attempt < 2 and self._is_transient_connection_error(exc):
                    time.sleep(0.25 * (attempt + 1))
                    continue
                raise
        assert last_exc is not None
        raise last_exc

    def run_rows(self) -> list[dict[str, Any]]:
        return self._query("select * from runs order by updated_at desc, run_id desc")

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self._query(STATUS_COUNT_QUERY):
            counts[_text(row["status"]) or "unknown"] = int(row["count"] or 0)
        return counts

    def recent_events(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._query(
            """
            select
                event_id,
                idempotency_key,
                event_type,
                entity_type,
                entity_id,
                pg_column_size(payload_json) as payload_bytes,
                created_at
            from control_events
            order by event_id desc
            limit %s
            """,
            (max(0, limit),),
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["payload"] = {
                "payload_omitted": True,
                "payload_bytes": int(item.pop("payload_bytes") or 0),
            }
            item["created_at"] = str(item.get("created_at") or "")
            item.pop("payload_hash", None)
            out.append(item)
        return out

    def event_rows(
        self,
        limit: int = 100,
        *,
        entity_type: str = "",
        entity_id: str = "",
        event_type: str = "",
        search: str = "",
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if entity_type:
            clauses.append("entity_type = %s")
            params.append(entity_type)
        if entity_id:
            clauses.append("entity_id = %s")
            params.append(entity_id)
        if event_type:
            clauses.append("event_type = %s")
            params.append(event_type)
        if search:
            clauses.append(
                "(event_type ilike %s or entity_id ilike %s or payload_json::text ilike %s)"
            )
            needle = f"%{search}%"
            params.extend([needle, needle, needle])
        where = f"where {' and '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 1000)))
        rows = self._query(
            f"select * from control_events {where} order by event_id desc limit %s",
            tuple(params),
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["payload"] = self._payload(item.pop("payload_json"))
            item["created_at"] = str(item.get("created_at") or "")
            item.pop("payload_hash", None)
            out.append(item)
        return out

    def dashboard_ideas_intake_parts(
        self, *, page_size: int = 50, include_latest_payload: bool = False
    ) -> dict[str, Any]:
        safe_limit = max(1, min(page_size, 500))
        with self._connect() as conn:
            with conn.cursor() as cur:
                if include_latest_payload:
                    latest_rows = self._cursor_rows(
                        cur,
                        """
                        select *
                        from operator_observations
                        where source = %s and scope = %s
                        order by observed_at desc, observation_id desc
                        limit 1
                        """,
                        ("idea_intake", "global"),
                    )
                    latest = (
                        self._observation_from_row(latest_rows[0])
                        if latest_rows
                        else None
                    )
                else:
                    latest_rows = self._cursor_rows(
                        cur,
                        """
                        with latest as (
                          select observation_id, source, scope, observed_at, ttl_seconds, status,
                                 payload_hash, created_at, payload_json,
                                 pg_column_size(payload_json) as payload_bytes
                          from operator_observations
                          where source = %s and scope = %s
                          order by observed_at desc, observation_id desc
                          limit 1
                        )
                        select
                          observation_id,
                          source,
                          scope,
                          observed_at,
                          ttl_seconds,
                          status,
                          payload_hash,
                          created_at,
                          payload_bytes,
                          coalesce(jsonb_array_length(payload_json->'skipped_rows'), 0) as skipped_row_count,
                          coalesce((
                            select jsonb_object_agg(reason, count)
                            from (
                              select coalesce(item->>'reason', 'unknown') as reason, count(*) as count
                              from jsonb_array_elements(coalesce(payload_json->'skipped_rows', '[]'::jsonb)) item
                              group by 1
                            ) reasons
                          ), '{}'::jsonb) as skipped_reasons
                        from latest
                        """,
                        ("idea_intake", "global"),
                    )
                    latest = None
                    if latest_rows:
                        row = latest_rows[0]
                        latest = DashboardObservationRecord(
                            observation_id=int(row["observation_id"]),
                            source=row["source"],
                            scope=row["scope"],
                            observed_at=str(row["observed_at"]),
                            ttl_seconds=int(row["ttl_seconds"]),
                            status=row["status"],
                            payload={
                                "payload_omitted": True,
                                "payload_bytes": int(row.get("payload_bytes") or 0),
                                "skipped_row_count": int(
                                    row.get("skipped_row_count") or 0
                                ),
                                "skipped_reasons": self._payload(
                                    row.get("skipped_reasons") or {}
                                ),
                            },
                            payload_hash=row["payload_hash"],
                            created_at=str(row["created_at"]),
                        )
                projection = self._cursor_rows(
                    cur,
                    """
                    select idea_id, title, idea_status, category, priority, source_kind,
                           source_external_id, source_external_url, machine_target, model, sandbox,
                           selection_rank, dispatch_priority, project_id, queue_status,
                           current_run_id, last_run_state, next_action_hint, manual_review_required,
                           queue_updated_at, paper_id, paper_status, created_at, updated_at
                    from idea_workbench
                    order by updated_at desc, idea_id asc
                    limit %s
                    """,
                    (safe_limit,),
                )
                recent_rows = self._cursor_rows(
                    cur,
                    """
                    select event_id, idempotency_key, event_type, entity_type, entity_id,
                           pg_column_size(payload_json) as payload_bytes, created_at
                    from control_events
                    where event_type = %s
                    order by event_id desc
                    limit %s
                    """,
                    ("ideas.intake", 20),
                )
                if not recent_rows:
                    recent_rows = self._cursor_rows(
                        cur,
                        """
                        select event_id, idempotency_key, event_type, entity_type, entity_id,
                               pg_column_size(payload_json) as payload_bytes, created_at
                        from control_events
                        where event_type = %s
                        order by event_id desc
                        limit %s
                        """,
                        ("notion.intake", 20),
                    )
                recent = []
                for row in recent_rows:
                    item = dict(row)
                    item["payload_summary"] = {
                        "keys": [],
                        "bytes": int(item.pop("payload_bytes") or 0),
                    }
                    item["created_at"] = str(item.get("created_at") or "")
                    item.pop("payload_hash", None)
                    recent.append(item)
                status_counts = {
                    _text(row["status"]) or "unknown": int(row["count"] or 0)
                    for row in self._cursor_rows(
                        cur,
                        STATUS_COUNT_QUERY,
                    )
                }
        return {
            "latest_sync": latest,
            "queued_projection": projection,
            "recent_events": recent,
            "projection_counts": status_counts,
        }

    def project_row(self, project_id: str) -> dict[str, Any] | None:
        return self._one("select * from projects where project_id = %s", (project_id,))

    def queue_row(self, project_id: str) -> dict[str, Any] | None:
        rows = self._queue_rows("where q.project_id = %s", (project_id,))
        return rows[0] if rows else None

    def run_row(self, run_id: str) -> dict[str, Any] | None:
        return self._one("select * from runs where run_id = %s", (run_id,))

    def paper_row(self, paper_id: str) -> dict[str, Any] | None:
        rows = self._paper_rows("where pa.paper_id = %s", (paper_id,))
        return rows[0] if rows else None

    def latest_dashboard_observation(
        self,
        *,
        source: str,
        scope: str = "global",
    ) -> DashboardObservationRecord | None:
        row = self._one(
            """
            select *
            from operator_observations
            where source = %s and scope = %s
            order by observed_at desc, observation_id desc
            limit 1
            """,
            (source, scope),
        )
        return self._observation_from_row(row) if row else None

    def latest_dashboard_observation_summary(
        self,
        *,
        source: str,
        scope: str = "global",
    ) -> DashboardObservationRecord | None:
        row = self._one(
            """
            with latest as (
              select observation_id, source, scope, observed_at, ttl_seconds, status,
                     payload_hash, created_at, payload_json,
                     pg_column_size(payload_json) as payload_bytes
              from operator_observations
              where source = %s and scope = %s
              order by observed_at desc, observation_id desc
              limit 1
            )
            select
              observation_id,
              source,
              scope,
              observed_at,
              ttl_seconds,
              status,
              payload_hash,
              created_at,
              payload_bytes,
              coalesce(jsonb_array_length(payload_json->'skipped_rows'), 0) as skipped_row_count,
              coalesce((
                select jsonb_object_agg(reason, count)
                from (
                  select coalesce(item->>'reason', 'unknown') as reason, count(*) as count
                  from jsonb_array_elements(coalesce(payload_json->'skipped_rows', '[]'::jsonb)) item
                  group by 1
                ) reasons
              ), '{}'::jsonb) as skipped_reasons
            from latest
            """,
            (source, scope),
        )
        if not row:
            return None
        return DashboardObservationRecord(
            observation_id=int(row["observation_id"]),
            source=row["source"],
            scope=row["scope"],
            observed_at=str(row["observed_at"]),
            ttl_seconds=int(row["ttl_seconds"]),
            status=row["status"],
            payload={
                "payload_omitted": True,
                "payload_bytes": int(row.get("payload_bytes") or 0),
                "skipped_row_count": int(row.get("skipped_row_count") or 0),
                "skipped_reasons": self._payload(row.get("skipped_reasons") or {}),
            },
            payload_hash=row["payload_hash"],
            created_at=str(row["created_at"]),
        )

    def latest_dashboard_observations(
        self, *, scope: str = "global"
    ) -> dict[str, DashboardObservationRecord]:
        rows = self._query(
            """
            select distinct on (source) *
            from operator_observations
            where scope = %s
            order by source, observed_at desc, observation_id desc
            """,
            (scope,),
        )
        return {row["source"]: self._observation_from_row(row) for row in rows}

    def _observation_from_row(self, row: dict[str, Any]) -> DashboardObservationRecord:
        return DashboardObservationRecord(
            observation_id=int(row["observation_id"]),
            source=row["source"],
            scope=row["scope"],
            observed_at=str(row["observed_at"]),
            ttl_seconds=int(row["ttl_seconds"]),
            status=row["status"],
            payload=self._payload(row["payload_json"]),
            payload_hash=row["payload_hash"],
            created_at=str(row["created_at"]),
        )

    def export_snapshot(self, *, event_limit: int = 50) -> dict[str, Any]:
        return {
            "source": "supabase_readonly_control_plane",
            "generated_at": utc_now(),
            "flags": self.flags().model_dump(mode="json"),
            "queue_rows": self.queue_rows(),
            "paper_rows": self.paper_rows(),
            "events": self.recent_events(event_limit),
        }


class SupabaseControlPlaneStore(SupabaseReadOnlyControlPlaneStore):
    """Write-capable Postgres adapter for the private `enoch` control-plane schema.

    This intentionally starts with the shared control-plane write primitives
    needed for migration cutover safety and dashboard parity. Unimplemented
    high-risk workflow writes remain absent rather than silently falling back to
    SQLite semantics.
    """

    def _append_event_in_cursor(
        self,
        cur: Any,
        *,
        idempotency_key: str,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
    ) -> tuple[int, bool]:
        payload_json = _json(payload)
        payload_hash = _hash(payload)
        row = cur.execute(
            "select event_id, event_type, entity_type, entity_id, payload_hash from control_events where idempotency_key = %s",
            (idempotency_key,),
        ).fetchone()
        if row:
            if (
                row["event_type"] != event_type
                or row["entity_type"] != entity_type
                or row["entity_id"] != entity_id
                or row["payload_hash"] != payload_hash
            ):
                raise IdempotencyConflict(
                    f"idempotency key {idempotency_key!r} was reused with different payload"
                )
            return int(row["event_id"]), False
        inserted = cur.execute(
            """
            insert into control_events(idempotency_key,event_type,entity_type,entity_id,payload_json,payload_hash,created_at)
            values (%s,%s,%s,%s,%s::jsonb,%s,%s)
            returning event_id
            """,
            (
                idempotency_key,
                event_type,
                entity_type,
                entity_id,
                payload_json,
                payload_hash,
                utc_now(),
            ),
        ).fetchone()
        return int(inserted["event_id"]), True

    def append_event(
        self,
        *,
        idempotency_key: str,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
    ) -> tuple[int, bool]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                return self._append_event_in_cursor(
                    cur,
                    idempotency_key=idempotency_key,
                    event_type=event_type,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    payload=payload,
                )

    def event_by_idempotency_key(self, idempotency_key: str) -> dict[str, Any] | None:
        row = self._one(
            """
            select event_id, idempotency_key, event_type, entity_type, entity_id, created_at
            from control_events
            where idempotency_key = %s
            """,
            (idempotency_key,),
        )
        return dict(row) if row else None

    def claim_dispatch_candidate(
        self,
        *,
        project_id: str,
        run_id: str,
        requested_by: str,
        conflicting_machine_targets: set[str] | None = None,
    ) -> dict[str, Any] | None:
        payload = {"requested_by": requested_by, "run_id": run_id}
        if (
            self._replayed_event_id(
                f"dispatch-claim:{run_id}",
                payload,
                event_type="controller.dispatch_claimed",
                entity_type="project",
                entity_id=project_id,
            )
            is not None
        ):
            return None
        now = utc_now()
        active_placeholders = ",".join(["%s"] * len(ACTIVE_STATUSES))
        conflict_targets = sorted(
            {_normal(item) for item in conflicting_machine_targets or []}
        )
        conflict_clause = "" if conflicting_machine_targets is None else "and false"
        conflict_params: tuple[str, ...] = ()
        if conflict_targets:
            conflict_placeholders = ",".join(["%s"] * len(conflict_targets))
            conflict_clause = f"and lower(replace(replace(trim(coalesce(active.machine_target, '')), '-', '_'), ' ', '_')) in ({conflict_placeholders})"
            conflict_params = tuple(conflict_targets)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    update queue_items
                    set status=%s, current_run_id=%s, current_session_id=%s, last_run_state=%s,
                        last_event_type=%s, next_action_hint=%s, last_error=%s, last_result_summary=%s,
                        last_dispatch_at=%s, updated_at=%s
                    where project_id=%s
                      and status=%s
                      and manual_review_required=false
                      and not exists (
                        select 1 from queue_items active
                        where active.status in ({active_placeholders})
                        {conflict_clause}
                      )
                    """,
                    (
                        QueueStatus.DISPATCHING.value,
                        run_id,
                        "",
                        QueueStatus.DISPATCHING.value,
                        "dispatch_claimed",
                        "prepare_worker_dispatch",
                        "",
                        "",
                        now,
                        now,
                        project_id,
                        QueueStatus.QUEUED.value,
                        *sorted(ACTIVE_STATUSES),
                        *conflict_params,
                    ),
                )
                claimed = cur.rowcount == 1
                if claimed:
                    self._append_event_in_cursor(
                        cur,
                        idempotency_key=f"dispatch-claim:{run_id}",
                        event_type="controller.dispatch_claimed",
                        entity_type="project",
                        entity_id=project_id,
                        payload=payload,
                    )
        if not claimed:
            return None
        return self.queue_row(project_id)

    def release_dispatch_claim(
        self, *, project_id: str, run_id: str, reason: str
    ) -> dict[str, Any]:
        now = utc_now()
        with self._connect() as conn:
            with conn.cursor() as cur:
                result = cur.execute(
                    """
                    update queue_items
                    set status=%s, current_run_id='', current_session_id='', last_run_state='',
                        last_event_type=%s, next_action_hint=%s, last_error=%s, updated_at=%s
                    where project_id=%s and current_run_id=%s and status=%s
                    """,
                    (
                        QueueStatus.QUEUED.value,
                        "dispatch_claim_released",
                        "controller_review",
                        reason,
                        now,
                        project_id,
                        run_id,
                        QueueStatus.DISPATCHING.value,
                    ),
                )
                rowcount = int(
                    getattr(result, "rowcount", getattr(cur, "rowcount", 1)) or 0
                )
                if rowcount == 1:
                    self._append_event_in_cursor(
                        cur,
                        idempotency_key=f"dispatch-claim-release:{run_id}",
                        event_type="controller.dispatch_claim_released",
                        entity_type="project",
                        entity_id=project_id,
                        payload={"run_id": run_id, "reason": reason},
                    )
        return self.queue_row(project_id) or {}

    def pause(
        self, *, reason: str, paused_by: str, maintenance_mode: bool
    ) -> tuple[ControlFlags, int]:
        now = utc_now()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update control_flags
                    set queue_paused=true, maintenance_mode=%s, pause_reason=%s, paused_at=%s, paused_by=%s, updated_at=%s
                    where singleton=true
                    """,
                    (maintenance_mode, reason, now, paused_by, now),
                )
                flags = ControlFlags(
                    queue_paused=True,
                    maintenance_mode=maintenance_mode,
                    pause_reason=reason,
                    paused_at=now,
                    paused_by=paused_by,
                    updated_at=now,
                )
                event_id, _ = self._append_event_in_cursor(
                    cur,
                    idempotency_key=f"pause:{now}",
                    event_type="control.pause",
                    entity_type="control",
                    entity_id="queue",
                    payload=flags.model_dump(mode="json"),
                )
        return flags, event_id

    def resume(
        self, *, resumed_by: str, maintenance_mode: bool
    ) -> tuple[ControlFlags, int]:
        now = utc_now()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update control_flags
                    set queue_paused=false, maintenance_mode=%s, pause_reason='', paused_at=null, paused_by=%s, updated_at=%s
                    where singleton=true
                    """,
                    (maintenance_mode, resumed_by, now),
                )
                flags = ControlFlags(
                    queue_paused=False,
                    maintenance_mode=maintenance_mode,
                    pause_reason="",
                    paused_at=None,
                    paused_by=resumed_by,
                    updated_at=now,
                )
                event_id, _ = self._append_event_in_cursor(
                    cur,
                    idempotency_key=f"resume:{now}",
                    event_type="control.resume",
                    entity_type="control",
                    entity_id="queue",
                    payload=flags.model_dump(mode="json"),
                )
        return flags, event_id

    def upsert_dashboard_observation(
        self,
        *,
        source: str,
        scope: str = "global",
        observed_at: str | None = None,
        ttl_seconds: int = 300,
        status: str = "ok",
        payload: dict[str, Any] | None = None,
    ) -> DashboardObservationRecord:
        now = utc_now()
        payload_dict = payload or {}
        payload_json = _json(payload_dict)
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        observed = observed_at or now
        with self._connect() as conn:
            with conn.cursor() as cur:
                row = cur.execute(
                    """
                    insert into operator_observations(source,scope,observed_at,ttl_seconds,status,payload_json,payload_hash,created_at)
                    values (%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
                    returning observation_id
                    """,
                    (
                        source,
                        scope,
                        observed,
                        ttl_seconds,
                        status,
                        payload_json,
                        payload_hash,
                        now,
                    ),
                ).fetchone()
        return DashboardObservationRecord(
            observation_id=int(row["observation_id"]),
            source=source,
            scope=scope,
            observed_at=observed,
            ttl_seconds=ttl_seconds,
            status=status,
            payload=payload_dict,
            payload_hash=payload_hash,
            created_at=now,
        )

    def dispatch_next_dry_run(
        self, *, requested_by: str
    ) -> tuple[str, dict[str, Any] | None, int | None, str]:
        flags = self.flags()
        if flags.queue_paused:
            return "paused", None, None, flags.pause_reason or "queue paused"
        active = self.active_items()
        candidate = self.next_dispatch_candidate()
        if not candidate:
            return (
                "noop",
                None,
                None,
                "no queued candidate on an open worker lane"
                if active
                else "no queued candidate",
            )
        return (
            "dry_run_dispatch",
            candidate,
            None,
            "dry-run dispatch selected candidate",
        )

    def _paper_review_join_rows(self) -> list[dict[str, Any]]:
        return self._query(
            """
            select
              pa.*,
              p.project_name,
              p.project_dir,
              p.notion_page_url,
              p.notion_page_id,
              q.status as queue_status,
              q.manual_review_required,
              q.blocked_reason,
              q.next_action_hint,
              rv.automation_status as review_status,
              rv.automation_actor as reviewer,
              rv.blocker,
              rv.claimed_at,
              rv.checklist_json,
              rv.rank_score,
              rv.rank_reasons_json,
              rv.missing_signals_json,
              rv.rank_tiebreaker,
              rv.source_audit_path,
              rv.finalization_package_path,
              rv.finalized_at,
              rv.decision_summary,
              rv.created_at as review_created_at,
              rv.updated_at as review_updated_at
            from publication_automation_items rv
            join papers pa using(paper_id)
            left join projects p using(project_id)
            left join queue_items q using(project_id)
            order by rv.rank_score desc, pa.updated_at desc, pa.paper_id asc
            """
        )

    def _review_queue_item_from_row(
        self, row: dict[str, Any], *, include_rank_reasons: bool = True
    ) -> dict[str, Any]:
        checklist = _json_dict(row.get("checklist_json")) or _default_review_checklist()
        rank_reasons = (
            _json_list(row.get("rank_reasons_json")) if include_rank_reasons else []
        )
        missing_signals = _json_list(row.get("missing_signals_json"))
        score = _int(row.get("rank_score"), 0)
        updated_at = _text(row.get("review_updated_at")) or _text(row.get("updated_at"))
        item = ReviewQueueItem(
            paper_id=_text(row.get("paper_id")),
            project_id=_text(row.get("project_id")),
            project_name=_text(row.get("project_name")),
            paper_status=_text(row.get("paper_status")),
            paper_type=_text(row.get("paper_type")),
            review_status=_text(row.get("review_status")) or ReviewStatus.QUEUED.value,
            checklist_progress=_checklist_progress(checklist),
            blocker=_text(row.get("blocker")),
            reviewer=_text(row.get("reviewer")),
            claimed_at=_text(row.get("claimed_at")),
            updated_at=updated_at,
            rank_score=score,
            rank_bucket="blocked"
            if score < 0
            else "ready"
            if score >= 100
            else "review",
            rank_reasons=rank_reasons,
            missing_signals=missing_signals,
            rank_tiebreaker=_text(row.get("rank_tiebreaker")),
            draft_markdown_path=_text(row.get("draft_markdown_path")),
            draft_latex_path=_text(row.get("draft_latex_path")),
            evidence_bundle_path=_text(row.get("evidence_bundle_path")),
            claim_ledger_path=_text(row.get("claim_ledger_path")),
            manifest_path=_text(row.get("manifest_path")),
            finalization_package_path=_text(row.get("finalization_package_path")),
            finalized_at=_text(row.get("finalized_at")),
            decision_summary=_text(row.get("decision_summary")),
            links={
                "review": f"/control/api/paper-reviews/{_text(row.get('paper_id'))}",
                "paper": f"/control/api/papers/{_text(row.get('paper_id'))}",
                "project": f"/control/api/projects/{_text(row.get('project_id'))}",
                "run": f"/control/api/runs/{_text(row.get('run_id'))}"
                if _text(row.get("run_id"))
                else "",
            },
        )
        return item.model_dump(mode="json")

    def paper_review_rows(
        self, *, include_rank_reasons: bool = True
    ) -> list[dict[str, Any]]:
        return [
            self._review_queue_item_from_row(
                row, include_rank_reasons=include_rank_reasons
            )
            for row in self._paper_review_join_rows()
        ]

    def paper_review_row(
        self, paper_id: str, *, include_rank_reasons: bool = True
    ) -> dict[str, Any] | None:
        for row in self._paper_review_join_rows():
            if row.get("paper_id") == paper_id:
                return self._review_queue_item_from_row(
                    row, include_rank_reasons=include_rank_reasons
                )
        return None

    def _raw_paper_review_row(self, paper_id: str) -> dict[str, Any] | None:
        return self._one(
            "select * from publication_automation_items where paper_id = %s",
            (paper_id,),
        )

    def _require_paper_review(self, paper_id: str) -> dict[str, Any]:
        row = self._raw_paper_review_row(paper_id)
        if row is None:
            raise ValueError("paper review not found")
        return row

    def paper_review_checklist(self, paper_id: str) -> dict[str, Any]:
        row = self._raw_paper_review_row(paper_id)
        return _normalize_review_checklist(
            _json_dict(row.get("checklist_json")) if row else {}
        )

    def _mutation_payload(self, request: Any, *, action: str) -> dict[str, Any]:
        payload = request.model_dump(mode="json")
        payload["action"] = action
        return payload

    def _papers_for_review_backfill(
        self, request: PaperReviewBackfillRequest
    ) -> list[dict[str, Any]]:
        requested_paper_ids = sorted(
            {_text(paper_id) for paper_id in request.paper_ids if _text(paper_id)}
        )
        if not requested_paper_ids:
            return self.paper_rows()
        placeholders = ",".join(["%s"] * len(requested_paper_ids))
        return self._paper_rows(
            f"where pa.paper_id in ({placeholders})", tuple(requested_paper_ids)
        )

    def _paper_review_backfill_candidates(
        self,
        papers: list[dict[str, Any]],
        *,
        audit_by_paper: dict[str, dict[str, Any]],
        source_audit_path: str,
    ) -> tuple[list[PaperReviewRecord], list[dict[str, Any]]]:
        errors: list[dict[str, Any]] = []
        candidates: list[PaperReviewRecord] = []
        mandatory = [
            "draft_markdown_path",
            "draft_latex_path",
            "evidence_bundle_path",
            "claim_ledger_path",
            "manifest_path",
        ]
        for paper in papers:
            paper_id = _text(paper.get("paper_id"))
            missing_paths = [name for name in mandatory if not _text(paper.get(name))]
            if missing_paths:
                errors.append(
                    {
                        "paper_id": paper_id,
                        "reason": "missing mandatory artifact path",
                        "missing_paths": missing_paths,
                    }
                )
            audit = audit_by_paper.get(paper_id, {})
            initial_missing = ([] if audit else ["readiness_audit"]) + missing_paths
            queue_item = self.queue_row(_text(paper.get("project_id")))
            rank_score, rank_reasons, missing_signals, tiebreaker, _bucket = (
                _review_rank(paper, queue_item, audit, initial_missing)
            )
            status = ReviewStatus.QUEUED if not missing_paths else ReviewStatus.BLOCKED
            candidates.append(
                PaperReviewRecord(
                    paper_id=paper_id,
                    review_status=status,
                    checklist_json=_default_review_checklist(),
                    rank_score=rank_score,
                    rank_reasons=rank_reasons,
                    missing_signals=missing_signals,
                    rank_tiebreaker=tiebreaker,
                    source_audit_path=source_audit_path,
                )
            )
        return candidates, errors

    def _upsert_backfill_paper_review_row(
        self, cur: Any, record: PaperReviewRecord, now: Any
    ) -> str:
        existing = cur.execute(
            "select * from publication_automation_items where paper_id = %s",
            (record.paper_id,),
        ).fetchone()
        rank_reasons_json = _json(record.rank_reasons)
        missing_signals_json = _json(record.missing_signals)
        if not existing:
            cur.execute(
                """
                insert into publication_automation_items(paper_id,automation_status,automation_actor,blocker,claimed_at,checklist_json,rank_score,rank_reasons_json,missing_signals_json,rank_tiebreaker,source_audit_path,finalization_package_path,finalized_at,decision_summary,created_at,updated_at)
                values (%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    record.paper_id,
                    record.review_status.value,
                    record.reviewer,
                    record.blocker,
                    None,
                    _json(_normalize_review_checklist(record.checklist_json)),
                    record.rank_score,
                    rank_reasons_json,
                    missing_signals_json,
                    record.rank_tiebreaker,
                    record.source_audit_path,
                    record.finalization_package_path,
                    None,
                    record.decision_summary,
                    now,
                    now,
                ),
            )
            return "created"
        existing_status = _text(existing["automation_status"])
        next_status = (
            record.review_status.value
            if existing_status in SYSTEM_REVIEW_STATUSES
            else existing_status
        )
        changes = {
            "automation_status": next_status,
            "rank_score": record.rank_score,
            "rank_reasons_json": rank_reasons_json,
            "missing_signals_json": missing_signals_json,
            "rank_tiebreaker": record.rank_tiebreaker,
            "source_audit_path": record.source_audit_path,
        }
        if all(str(existing[key]) == str(value) for key, value in changes.items()):
            return "skipped"
        cur.execute(
            """
            update publication_automation_items
            set automation_status=%s, rank_score=%s, rank_reasons_json=%s::jsonb, missing_signals_json=%s::jsonb,
                rank_tiebreaker=%s, source_audit_path=%s, updated_at=%s
            where paper_id=%s
            """,
            (
                next_status,
                record.rank_score,
                rank_reasons_json,
                missing_signals_json,
                record.rank_tiebreaker,
                record.source_audit_path,
                now,
                record.paper_id,
            ),
        )
        return "updated"

    def backfill_paper_reviews(
        self, request: PaperReviewBackfillRequest
    ) -> tuple[bool, int, int, int, list[dict[str, Any]]]:
        audit_by_paper = _audit_rows(request.source_audit_path)
        papers = self._papers_for_review_backfill(request)
        candidates, errors = self._paper_review_backfill_candidates(
            papers,
            audit_by_paper=audit_by_paper,
            source_audit_path=request.source_audit_path,
        )
        if request.dry_run:
            return False, len(candidates), 0, 0, errors
        event_payload = request.model_dump(mode="json")
        event_payload.update(
            {"candidate_count": len(candidates), "error_count": len(errors)}
        )
        created = updated = skipped = 0
        now = utc_now()
        with self._connect() as conn:
            with conn.cursor() as cur:
                _, inserted = self._append_event_in_cursor(
                    cur,
                    idempotency_key=request.idempotency_key,
                    event_type="paper_review.backfill",
                    entity_type="paper_reviews",
                    entity_id="backfill",
                    payload=event_payload,
                )
                if not inserted:
                    return False, 0, 0, 0, errors
                for record in candidates:
                    outcome = self._upsert_backfill_paper_review_row(cur, record, now)
                    if outcome == "created":
                        created += 1
                    elif outcome == "updated":
                        updated += 1
                    else:
                        skipped += 1
        return inserted, created, updated, skipped, errors

    def claim_paper_review(
        self, paper_id: str, request: PaperReviewClaimRequest
    ) -> tuple[int, bool, dict[str, Any]]:
        if not _text(request.reviewer):
            raise ValueError("reviewer is required")
        row = self._require_paper_review(paper_id)
        current = _text(row.get("automation_status"))
        if current in {
            ReviewStatus.FINALIZED.value,
            ReviewStatus.REJECTED.value,
            ReviewStatus.APPROVED_FOR_FINALIZATION.value,
        }:
            raise ValueError(f"cannot claim paper review from {current}")
        if (
            current == ReviewStatus.BLOCKED.value
            and _text(row.get("blocker"))
            and not request.clear_blocker
        ):
            raise ValueError("blocked review requires clear_blocker=true to claim")
        if current not in {
            ReviewStatus.QUEUED.value,
            ReviewStatus.CLAIMED.value,
            ReviewStatus.TRIAGE_READY.value,
            ReviewStatus.UNREVIEWED.value,
            ReviewStatus.CHANGES_REQUESTED.value,
            ReviewStatus.BLOCKED.value,
            ReviewStatus.IN_REVIEW.value,
        }:
            raise ValueError(f"cannot claim paper review from {current}")
        payload = self._mutation_payload(request, action="claim")
        payload.update({"to_status": ReviewStatus.CLAIMED.value})
        now = utc_now()
        checklist = _normalize_review_checklist(_json_dict(row.get("checklist_json")))
        with self._connect() as conn:
            with conn.cursor() as cur:
                event_id, inserted = self._append_event_in_cursor(
                    cur,
                    idempotency_key=request.idempotency_key,
                    event_type="paper_review.claimed",
                    entity_type="paper_review",
                    entity_id=paper_id,
                    payload=payload,
                )
                if inserted:
                    cur.execute(
                        "update publication_automation_items set automation_status=%s, automation_actor=%s, blocker=%s, claimed_at=%s, checklist_json=%s::jsonb, updated_at=%s where paper_id=%s",
                        (
                            ReviewStatus.CLAIMED.value,
                            _text(request.reviewer),
                            "" if request.clear_blocker else _text(row.get("blocker")),
                            now,
                            _json(checklist),
                            now,
                            paper_id,
                        ),
                    )
        return event_id, inserted, self.paper_review_row(paper_id) or {}

    def update_paper_review_status(
        self, paper_id: str, request: PaperReviewStatusUpdateRequest
    ) -> tuple[int, bool, dict[str, Any]]:
        row = self._require_paper_review(paper_id)
        current = _text(row.get("automation_status"))
        target = request.review_status.value
        if target == ReviewStatus.APPROVED_FOR_FINALIZATION.value:
            raise ValueError("use approve-finalization endpoint for approval")
        if target in {ReviewStatus.FINALIZED.value}:
            raise ValueError(
                "finalized status is reserved for finalization package workflow"
            )
        if (
            target not in ALLOWED_STATUS_TRANSITIONS.get(current, set())
            and target != current
        ):
            raise ValueError(f"invalid review status transition {current} -> {target}")
        blocker = _text(request.blocker)
        note = _text(request.note)
        if target in {
            ReviewStatus.BLOCKED.value,
            ReviewStatus.CHANGES_REQUESTED.value,
            ReviewStatus.REJECTED.value,
        } and not (blocker or note):
            raise ValueError(f"{target} requires blocker or note")
        payload = self._mutation_payload(request, action="status_update")
        payload.update({"to_status": target})
        now = utc_now()
        next_blocker = blocker if target == ReviewStatus.BLOCKED.value else ""
        decision_summary = (
            note
            if target
            in {ReviewStatus.REJECTED.value, ReviewStatus.CHANGES_REQUESTED.value}
            else _text(row.get("decision_summary"))
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                event_id, inserted = self._append_event_in_cursor(
                    cur,
                    idempotency_key=request.idempotency_key,
                    event_type="paper_review.status_changed",
                    entity_type="paper_review",
                    entity_id=paper_id,
                    payload=payload,
                )
                if inserted:
                    cur.execute(
                        "update publication_automation_items set automation_status=%s, blocker=%s, decision_summary=%s, updated_at=%s where paper_id=%s",
                        (target, next_blocker, decision_summary, now, paper_id),
                    )
        return event_id, inserted, self.paper_review_row(paper_id) or {}

    @staticmethod
    def _validate_checklist_item_update(
        item: dict[str, Any] | None, status: str, note: str, item_id: str
    ) -> None:
        """Pure validation extracted from update_paper_review_checklist to reduce C901.
        All business rules for checklist status transitions live here.
        """
        if item is None:
            raise ValueError(f"unknown checklist item {item_id}")
        if status == "fail" and not note:
            raise ValueError("fail checklist status requires a note")
        if status == "accepted_risk" and not note:
            raise ValueError("accepted_risk checklist status requires a note")
        if item_id == "final_human_approval" and status in {
            "accepted_risk",
            "not_applicable",
        }:
            raise ValueError(
                "automated finalization approval must be pass or fail/pending"
            )
        if status == "not_applicable" and item.get("required") and not note:
            raise ValueError("not_applicable on a required item requires a note")

    def update_paper_review_checklist(
        self, paper_id: str, item_id: str, request: PaperReviewChecklistUpdateRequest
    ) -> tuple[int, bool, dict[str, Any]]:
        row = self._require_paper_review(paper_id)
        checklist = _normalize_review_checklist(_json_dict(row.get("checklist_json")))
        item = next(
            (entry for entry in checklist["items"] if entry["id"] == item_id), None
        )
        status = _text(request.status)
        note = _text(request.note)
        SupabaseControlPlaneStore._validate_checklist_item_update(
            item, status, note, item_id
        )
        payload = self._mutation_payload(request, action="checklist_update")
        payload["item_id"] = item_id
        now = utc_now()
        item.update(
            {
                "status": status,
                "note": note,
                "updated_at": now,
                "updated_by": _text(request.requested_by),
            }
        )
        risks = [
            risk
            for risk in checklist.get("accepted_risks", [])
            if isinstance(risk, dict) and risk.get("item_id") != item_id
        ]
        if status == "accepted_risk":
            risks.append(
                {
                    "item_id": item_id,
                    "risk": note,
                    "accepted_by": _text(request.requested_by),
                    "accepted_at": now,
                }
            )
        checklist["accepted_risks"] = risks
        checklist["progress"] = _progress_for_items(checklist["items"])
        with self._connect() as conn:
            with conn.cursor() as cur:
                event_id, inserted = self._append_event_in_cursor(
                    cur,
                    idempotency_key=request.idempotency_key,
                    event_type="paper_review.checklist_updated",
                    entity_type="paper_review",
                    entity_id=paper_id,
                    payload=payload,
                )
                if inserted:
                    cur.execute(
                        "update publication_automation_items set checklist_json=%s::jsonb, updated_at=%s where paper_id=%s",
                        (_json(checklist), now, paper_id),
                    )
        return event_id, inserted, self.paper_review_row(paper_id) or {}

    def approve_paper_review_finalization(
        self, paper_id: str, request: PaperReviewApproveFinalizationRequest
    ) -> tuple[int, bool, dict[str, Any]]:
        raise ValueError(
            "manual paper approval has been removed; use automated prepare-finalization-package or rewrite-draft"
        )

    def _resolved_artifact(self, paper: dict[str, Any], field: str) -> dict[str, Any]:
        raw_path = _text(paper.get(field))
        project_dir_text = _text(paper.get("project_dir"))
        project_dir = (
            _expanduser_or_none(project_dir_text) if project_dir_text else None
        )
        path = _expanduser_or_none(raw_path) if raw_path else Path()
        if project_dir_text and project_dir is None:
            return _unresolved_artifact(field, raw_path)
        if raw_path and path is None:
            return _unresolved_artifact(field, raw_path)
        path = path or Path()
        resolved = _resolve_artifact_path(path, project_dir)
        if resolved is None:
            return _unresolved_artifact(field, raw_path)
        safe = _artifact_path_is_safe(resolved, project_dir)
        exists, readable, size_bytes = _artifact_file_stats(resolved, raw_path, safe)
        return {
            "field": field,
            "path": raw_path,
            "absolute_path": str(resolved),
            "exists": exists,
            "readable": readable,
            "safe": safe,
            "size_bytes": size_bytes,
        }

    def _finalization_manifest_path(self, paper_id: str, idempotency_key: str) -> Path:
        configured = os.environ.get("ENOCH_SUPABASE_FINALIZATION_ROOT", "").strip()
        root = (
            Path(configured).expanduser()
            if configured
            else _default_supabase_finalization_root()
        )
        return (
            root
            / _slug_id(paper_id)
            / _slug_id(idempotency_key)
            / "finalization_manifest.json"
        )

    def _load_manifest(self, package_path: str) -> dict[str, Any]:
        if not package_path:
            return {}
        path = Path(package_path)
        try:
            return _json_dict(path.read_text(encoding="utf-8")) if path.exists() else {}
        except OSError:
            return {}

    def _replay_prepare_finalization_package(
        self,
        paper_id: str,
        request: PaperReviewPrepareFinalizationRequest,
        payload: dict[str, Any],
    ) -> tuple[int | None, bool, dict[str, Any], str, dict[str, Any]] | None:
        if request.dry_run:
            return None
        replayed_event_id = self._replayed_event_id(
            request.idempotency_key,
            payload,
            event_type="paper_review.finalization_package_prepared",
            entity_type="paper_review",
            entity_id=paper_id,
        )
        if replayed_event_id is None:
            return None
        item = self.paper_review_row(paper_id) or {}
        path = _text(item.get("finalization_package_path"))
        return replayed_event_id, False, item, path, self._load_manifest(path)

    def _existing_finalized_package_result(
        self,
        paper_id: str,
        *,
        dry_run: bool,
        current: str,
    ) -> tuple[int | None, bool, dict[str, Any], str, dict[str, Any]] | None:
        if dry_run or current != ReviewStatus.FINALIZED.value:
            return None
        item = self.paper_review_row(paper_id) or {}
        path = _text(item.get("finalization_package_path"))
        return None, False, item, path, self._load_manifest(path)

    def _validate_prepare_finalization_status(
        self,
        *,
        dry_run: bool,
        require_approval: bool,
        current: str,
    ) -> None:
        if dry_run:
            return
        if require_approval and current != ReviewStatus.APPROVED_FOR_FINALIZATION.value:
            raise ValueError(
                "legacy approval-gated finalization requires internal approved_for_finalization state"
            )
        blocked = {
            ReviewStatus.BLOCKED.value,
            ReviewStatus.CHANGES_REQUESTED.value,
            ReviewStatus.IN_REVIEW.value,
            ReviewStatus.REJECTED.value,
            ReviewStatus.UNREVIEWED.value,
        }
        if not require_approval and current in blocked:
            raise ValueError(
                f"automated finalization cannot publish paper reviews with review_status={current}"
            )

    def _collect_finalization_artifacts(
        self,
        paper: dict[str, Any],
        *,
        dry_run: bool,
    ) -> list[dict[str, Any]]:
        artifacts = [
            self._resolved_artifact(paper, field)
            for field in (
                "draft_markdown_path",
                "draft_latex_path",
                "evidence_bundle_path",
                "claim_ledger_path",
                "manifest_path",
            )
        ]
        unreadable = [
            artifact["field"] for artifact in artifacts if not artifact["readable"]
        ]
        if unreadable and not dry_run:
            raise ValueError(
                f"finalization package requires readable artifacts: {', '.join(unreadable)}"
            )
        return artifacts

    def _build_finalization_package_manifest(
        self,
        *,
        paper_id: str,
        request: PaperReviewPrepareFinalizationRequest,
        paper: dict[str, Any],
        row: dict[str, Any],
        current: str,
        require_approval: bool,
        artifacts: list[dict[str, Any]],
        checklist: dict[str, Any],
        now: str,
    ) -> dict[str, Any]:
        return {
            "schema": "paper_finalization_package_v1",
            "generated_at": now,
            "dry_run": request.dry_run,
            "requested_by": request.requested_by,
            "target_label": request.target_label,
            "paper_id": paper_id,
            "project_id": _text(paper.get("project_id")),
            "project_name": _text(paper.get("project_name")),
            "paper_status": _text(paper.get("paper_status")),
            "automation_status": current,
            "reviewer": _text(row.get("automation_actor")),
            "decision_summary": _text(row.get("decision_summary")),
            "require_approval": require_approval,
            "automated_publication": not require_approval,
            "artifacts": artifacts,
            "checklist": checklist,
            "review_item": self.paper_review_row(paper_id) or {},
            "no_submission_side_effects": True,
        }

    def _persist_prepare_finalization_package(
        self,
        paper_id: str,
        request: PaperReviewPrepareFinalizationRequest,
        *,
        payload: dict[str, Any],
        package_path: Path,
        manifest: dict[str, Any],
        now: str,
    ) -> tuple[int | None, bool, dict[str, Any], str, dict[str, Any]]:
        previous_manifest_exists, previous_manifest_content = _existing_file_snapshot(
            package_path,
            label="finalization package manifest",
        )
        _atomic_write_text(package_path, _json(manifest))
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    event_id, inserted = self._append_event_in_cursor(
                        cur,
                        idempotency_key=request.idempotency_key,
                        event_type="paper_review.finalization_package_prepared",
                        entity_type="paper_review",
                        entity_id=paper_id,
                        payload=payload,
                    )
                    if inserted:
                        cur.execute(
                            "update publication_automation_items set automation_status=%s, finalization_package_path=%s, finalized_at=%s, updated_at=%s where paper_id=%s",
                            (
                                ReviewStatus.FINALIZED.value,
                                str(package_path),
                                now,
                                now,
                                paper_id,
                            ),
                        )
        except Exception:
            _restore_or_remove_path(
                package_path,
                existed=previous_manifest_exists,
                content=previous_manifest_content,
            )
            raise
        item = self.paper_review_row(paper_id) or {}
        return event_id, inserted, item, str(package_path), manifest

    def prepare_paper_review_finalization_package(
        self,
        paper_id: str,
        request: PaperReviewPrepareFinalizationRequest,
        *,
        require_approval: bool = True,
    ) -> tuple[int | None, bool, dict[str, Any], str, dict[str, Any]]:
        row = self._require_paper_review(paper_id)
        payload = self._mutation_payload(request, action="prepare_finalization_package")
        payload.update(
            {
                "to_status": ReviewStatus.FINALIZED.value,
                "require_approval": require_approval,
            }
        )
        replayed = self._replay_prepare_finalization_package(paper_id, request, payload)
        if replayed is not None:
            return replayed
        current = _text(row.get("automation_status"))
        existing = self._existing_finalized_package_result(
            paper_id, dry_run=request.dry_run, current=current
        )
        if existing is not None:
            return existing
        self._validate_prepare_finalization_status(
            dry_run=request.dry_run,
            require_approval=require_approval,
            current=current,
        )
        paper = self.paper_row(paper_id)
        if paper is None:
            raise ValueError("paper row not found")
        checklist = self.paper_review_checklist(paper_id)
        artifacts = self._collect_finalization_artifacts(paper, dry_run=request.dry_run)
        package_path = self._finalization_manifest_path(
            paper_id, request.idempotency_key
        )
        now = utc_now()
        manifest = self._build_finalization_package_manifest(
            paper_id=paper_id,
            request=request,
            paper=paper,
            row=row,
            current=current,
            require_approval=require_approval,
            artifacts=artifacts,
            checklist=checklist,
            now=now,
        )
        if request.dry_run:
            return (
                None,
                False,
                self.paper_review_row(paper_id) or {},
                str(package_path),
                manifest,
            )
        return self._persist_prepare_finalization_package(
            paper_id,
            request,
            payload=payload,
            package_path=package_path,
            manifest=manifest,
            now=now,
        )

    def ingest_notion_ideas(
        self, request: NotionIntakeRequest
    ) -> tuple[bool, int, int, int, list[dict[str, Any]], list[dict[str, Any]]]:
        include_statuses = {
            item.strip().lower() for item in request.include_statuses if item.strip()
        }
        candidates: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []
        for raw in request.notion_rows:
            candidate, skip = _notion_intake_row_result(
                raw,
                include_statuses=include_statuses,
                default_machine_target=request.default_machine_target,
                workload_machine_targets=request.workload_machine_targets,
                default_model=request.default_model,
                default_sandbox=request.default_sandbox,
                source=request.source or "notion",
            )
            if skip is not None:
                skipped_rows.append(skip)
                continue
            candidates.append(candidate)
        if request.dry_run:
            return False, 0, 0, len(skipped_rows), candidates, skipped_rows
        event_payload = request.model_dump(mode="json")
        event_payload["candidate_count"] = len(candidates)
        event_payload["skipped_count"] = len(skipped_rows)
        created = updated = 0
        now = utc_now()
        with self._connect() as conn:
            with conn.cursor() as cur:
                _event_id, inserted = self._append_event_in_cursor(
                    cur,
                    idempotency_key=request.idempotency_key,
                    event_type="notion.intake",
                    entity_type="snapshot",
                    entity_id=request.source,
                    payload=event_payload,
                )
                if not inserted:
                    return (
                        inserted,
                        created,
                        updated,
                        len(skipped_rows),
                        candidates,
                        skipped_rows,
                    )
                for candidate in candidates:
                    outcome = _persist_notion_intake_candidate(
                        cur,
                        candidate,
                        now=now,
                        override_existing_dispatch_metadata=request.override_existing_dispatch_metadata,
                    )
                    if outcome == "created":
                        created += 1
                    else:
                        updated += 1
        return inserted, created, updated, len(skipped_rows), candidates, skipped_rows

    def ingest_ideas(
        self, request: IdeaIntakeRequest
    ) -> tuple[bool, int, int, int, list[dict[str, Any]], list[dict[str, Any]]]:
        include_statuses = {
            item.strip().lower() for item in request.include_statuses if item.strip()
        }
        candidates, skipped_rows = _collect_idea_intake_candidates(
            request, include_statuses
        )
        if request.dry_run:
            return False, 0, 0, len(skipped_rows), candidates, skipped_rows
        event_payload = request.model_dump(mode="json")
        event_payload["candidate_count"] = len(candidates)
        event_payload["skipped_count"] = len(skipped_rows)
        created = updated = 0
        now = utc_now()
        with self._connect() as conn:
            with conn.cursor() as cur:
                _event_id, inserted = self._append_event_in_cursor(
                    cur,
                    idempotency_key=request.idempotency_key,
                    event_type="ideas.intake",
                    entity_type="snapshot",
                    entity_id=request.source,
                    payload=event_payload,
                )
                if not inserted:
                    return (
                        inserted,
                        created,
                        updated,
                        len(skipped_rows),
                        candidates,
                        skipped_rows,
                    )
                for candidate in candidates:
                    outcome = _persist_idea_intake_candidate(
                        cur,
                        candidate,
                        now=now,
                        override_existing_dispatch_metadata=request.override_existing_dispatch_metadata,
                    )
                    if outcome == "created":
                        created += 1
                    else:
                        updated += 1
        return inserted, created, updated, len(skipped_rows), candidates, skipped_rows

    def notion_execution_update_projection(self) -> list[dict[str, Any]]:
        state_map = {
            QueueStatus.QUEUED.value: "queued",
            QueueStatus.DISPATCHING.value: "running",
            QueueStatus.RUNNING.value: "running",
            QueueStatus.AWAITING_WAKE.value: "waiting",
            QueueStatus.WAKE_RECEIVED.value: "waiting",
            QueueStatus.RECONCILING.value: "waiting",
            QueueStatus.COMPLETED.value: "completed",
            QueueStatus.PAUSED.value: "blocked",
            QueueStatus.CANCELED.value: "completed",
            QueueStatus.DISPATCH_ERROR.value: "failed",
            QueueStatus.BLOCKED.value: "blocked",
            QueueStatus.NEEDS_REVIEW.value: "blocked",
        }
        paper_by_project = {
            paper.get("project_id"): paper for paper in self.paper_rows()
        }
        rows = []
        for row in self.queue_rows():
            paper = paper_by_project.get(row.get("project_id")) or {}
            merged = {
                **row,
                "paper_id": paper.get("paper_id") or "",
                "paper_status": paper.get("paper_status") or "",
                "paper_type": paper.get("paper_type") or "",
                "draft_markdown_path": paper.get("draft_markdown_path") or "",
                "paper_updated_at": paper.get("updated_at") or "",
            }
            page_url = merged.get("notion_page_url") or ""
            if not page_url:
                continue
            execution_state = state_map.get(merged.get("status") or "", "blocked")
            blocked_reason = (
                merged.get("blocked_reason")
                or (
                    merged.get("last_result_summary")
                    if execution_state in {"blocked", "failed"}
                    else ""
                )
                or ""
            )
            rows.append(
                {
                    "project_id": merged.get("project_id") or "",
                    "page_id": merged.get("notion_page_id")
                    or _notion_page_id_from_url(page_url),
                    "notion_page_url": page_url,
                    "properties": {
                        "Execution State": execution_state,
                        "Current Run ID": merged.get("current_run_id") or "",
                        "Next Action": merged.get("next_action_hint") or "",
                        "Blocked Reason": blocked_reason,
                        "Last Execution Update": merged.get("updated_at") or utc_now(),
                        "Execution Summary": merged.get("last_result_summary") or "",
                        "Enoch Project ID": merged.get("project_id") or "",
                        "Enoch Queue Status": merged.get("status") or "",
                        "Enoch Last Run State": merged.get("last_run_state") or "",
                        "Enoch Last Event Type": merged.get("last_event_type") or "",
                        "Enoch Next Action Hint": merged.get("next_action_hint") or "",
                        "Enoch Project Dir": merged.get("project_dir") or "",
                        "Enoch Current Session ID": merged.get("current_session_id")
                        or "",
                        "Enoch Last Result Summary": merged.get("last_result_summary")
                        or "",
                        "Enoch Last Error": merged.get("last_error") or "",
                        "Enoch Manual Review Required": "__YES__"
                        if merged.get("manual_review_required")
                        else "__NO__",
                        "Enoch Dispatch Priority": merged.get("dispatch_priority") or 0,
                        "Enoch Selection Rank": merged.get("selection_rank") or 0,
                        "Enoch Paper ID": merged.get("paper_id") or "",
                        "Enoch Paper Status": merged.get("paper_status") or "",
                        "Enoch Paper Type": merged.get("paper_type") or "",
                        "Enoch Paper Markdown Path": merged.get("draft_markdown_path")
                        or "",
                        "Enoch Paper Updated At": merged.get("paper_updated_at") or "",
                        "Enoch Paper Updated At ISO": merged.get("paper_updated_at")
                        or "",
                    },
                }
            )
        return rows

    def queue_notion_projection(self) -> list[dict[str, Any]]:
        return [
            {
                "project_id": row.get("project_id") or "",
                "project_name": row.get("project_name") or "",
                "origin_idea_status": row.get("origin_idea_status") or "",
                "queue_status": row.get("status") or "",
                "next_action_hint": row.get("next_action_hint") or "",
                "last_run_state": row.get("last_run_state") or "",
                "last_event_type": row.get("last_event_type") or "",
                "current_run_id": row.get("current_run_id") or "",
                "current_session_id": row.get("current_session_id") or "",
                "machine_target": row.get("machine_target") or "",
                "manual_review_required": _bool(row.get("manual_review_required")),
                "blocked_reason": row.get("blocked_reason") or "",
                "last_result_summary": row.get("last_result_summary") or "",
                "notion_page_url": row.get("notion_page_url") or "",
                "updated_at": row.get("updated_at") or "",
            }
            for row in self.queue_rows()
        ]

    def idea_workbench_projection(self, *, limit: int = 200) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        with self._connect() as conn:
            with conn.cursor() as cur:
                rows = cur.execute(
                    """
                    select idea_id, title, idea_status, category, priority, source_kind,
                           source_external_id, source_external_url, machine_target, model, sandbox,
                           selection_rank, dispatch_priority, project_id, queue_status,
                           current_run_id, last_run_state, next_action_hint, manual_review_required,
                           queue_updated_at, paper_id, paper_status, created_at, updated_at
                    from idea_workbench
                    order by updated_at desc, idea_id asc
                    limit %s
                    """,
                    (safe_limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def research_facility_workbench_projection(
        self, *, limit: int = 200
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        with self._connect() as conn:
            with conn.cursor() as cur:
                rows = cur.execute(
                    """
                    select w.candidate_id, w.generation_mode, w.status, w.title, w.category, w.priority,
                           w.total_score, w.novelty_score, w.feasibility_score, w.accessibility_score,
                           w.falsifiability_score, w.dedupe_key, w.parent_project_id, w.parent_run_id,
                           w.similar_prior_projects, w.source_urls, w.provider, w.provider_model,
                           w.admission_decision, w.admission_reason, w.admitted_idea_id, w.admitted_by,
                           w.admitted_queue_status, w.admitted_current_run_id, w.admitted_project_name,
                           c.machine_target, c.model, c.sandbox,
                           w.created_at, w.updated_at
                    from research_facility_workbench w
                    left join research_candidates c on c.candidate_id = w.candidate_id
                    order by w.updated_at desc, w.total_score desc, w.candidate_id asc
                    limit %s
                    """,
                    (safe_limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def research_facility_workbench_counts(self) -> dict[str, int]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                rows = cur.execute(
                    """
                    select status, count(*) as count
                    from research_facility_workbench
                    group by status
                    """
                ).fetchall()
        return {
            _text(row.get("status") or "unknown"): int(row.get("count") or 0)
            for row in rows
        }

    def promote_research_candidate(
        self, candidate_id: str, *, requested_by: str, dry_run: bool = True
    ) -> dict[str, Any]:
        """Promote one admitted Research Facility candidate into the queued idea lane.

        Promotion is intentionally narrower than generation:
        - it only accepts candidates whose latest admission decision is
          ``admitted`` and whose candidate status is ``admitted``;
        - it creates/updates idea, project, and queue rows;
        - it does not dispatch work.
        """

        candidate_id = _text(candidate_id).strip()
        requested_by = (_text(requested_by) or "dashboard")[:80]
        if not candidate_id:
            return {
                "ok": False,
                "action": "promote_candidate_blocked",
                "reason": "candidate_id is required",
            }

        with self._connect() as conn:
            with conn.cursor() as cur:
                workbench = cur.execute(
                    """
                    select candidate_id, status, title, admission_decision, admission_reason, admitted_idea_id,
                           admitted_queue_status, admitted_current_run_id, admitted_project_name
                    from research_facility_workbench
                    where candidate_id = %s
                    """,
                    (candidate_id,),
                ).fetchone()
                if not workbench:
                    return {
                        "ok": False,
                        "action": "promote_candidate_blocked",
                        "candidate_id": candidate_id,
                        "reason": "candidate not found",
                    }
                wb = dict(workbench)
                current_status = _text(wb.get("status"))
                admission_decision = _text(wb.get("admission_decision"))
                admitted_idea_id = _text(wb.get("admitted_idea_id"))
                if admitted_idea_id:
                    return {
                        "ok": True,
                        "action": "dry_run_promote_candidate"
                        if dry_run
                        else "promote_candidate",
                        "dry_run": dry_run,
                        "candidate_id": candidate_id,
                        "idea_id": admitted_idea_id,
                        "title": _text(wb.get("title")),
                        "already_promoted": True,
                        "queued_count": 0,
                        "reason": "candidate is already linked to an admitted idea",
                    }
                if current_status != "admitted" or admission_decision != "admitted":
                    return {
                        "ok": False,
                        "action": "promote_candidate_blocked",
                        "dry_run": dry_run,
                        "candidate_id": candidate_id,
                        "title": _text(wb.get("title")),
                        "status": current_status,
                        "admission_decision": admission_decision,
                        "reason": "candidate is not admitted",
                    }

                row = cur.execute(
                    """
                    select candidate_id, title, category, priority, source_urls, description, hypothesis,
                           implementation, baseline_to_beat, kill_condition, accessibility_delta,
                           expected_token_budget, novelty_score, machine_target, model, sandbox,
                           score_breakdown, raw_candidate_json
                    from research_candidates
                    where candidate_id = %s
                    """,
                    (candidate_id,),
                ).fetchone()
                if not row:
                    return {
                        "ok": False,
                        "action": "promote_candidate_blocked",
                        "candidate_id": candidate_id,
                        "reason": "candidate row not found",
                    }
                candidate = dict(row)
                idea_id = candidate_id
                title = _text(candidate.get("title")) or idea_id
                source_urls = (
                    candidate.get("source_urls")
                    if isinstance(candidate.get("source_urls"), list)
                    else []
                )
                source_external_url = _text(source_urls[0]) if source_urls else ""
                raw_candidate = (
                    candidate.get("raw_candidate_json")
                    if isinstance(candidate.get("raw_candidate_json"), dict)
                    else {}
                )
                source_payload_json = {
                    **raw_candidate,
                    "research_candidate_id": candidate_id,
                    "promoted_by": requested_by,
                    "promotion_path": "research_facility_promote_candidate",
                }
                response = {
                    "ok": True,
                    "action": "dry_run_promote_candidate"
                    if dry_run
                    else "promote_candidate",
                    "dry_run": dry_run,
                    "candidate_id": candidate_id,
                    "idea_id": idea_id,
                    "title": title,
                    "queued_count": 0 if dry_run else 1,
                    "dispatch_started": False,
                    "reason": "candidate is admitted and promotable",
                }
                if dry_run:
                    return response

                cur.execute(
                    """
                    insert into ideas(
                      idea_id, title, idea_status, category, priority, source_kind, source_external_url,
                      description, implementation, baseline_to_beat, kill_condition, accessibility_delta,
                      expected_token_budget, novelty_score, machine_target, model, sandbox, selection_rank,
                      dispatch_priority, source_payload_json
                    ) values (
                      %s,%s,'testing',%s,%s,'research_facility',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,50,50,%s::jsonb
                    )
                    on conflict (idea_id) do update set
                      title=excluded.title,
                      category=excluded.category,
                      priority=excluded.priority,
                      source_external_url=excluded.source_external_url,
                      description=excluded.description,
                      implementation=excluded.implementation,
                      baseline_to_beat=excluded.baseline_to_beat,
                      kill_condition=excluded.kill_condition,
                      accessibility_delta=excluded.accessibility_delta,
                      expected_token_budget=excluded.expected_token_budget,
                      novelty_score=excluded.novelty_score,
                      machine_target=excluded.machine_target,
                      model=excluded.model,
                      sandbox=excluded.sandbox,
                      source_payload_json=excluded.source_payload_json,
                      updated_at=now()
                    """,
                    (
                        idea_id,
                        title,
                        _text(candidate.get("category")),
                        _text(candidate.get("priority")),
                        source_external_url,
                        _text(candidate.get("description"))
                        or _text(candidate.get("hypothesis")),
                        _text(candidate.get("implementation")),
                        _text(candidate.get("baseline_to_beat")),
                        _text(candidate.get("kill_condition")),
                        _text(candidate.get("accessibility_delta")),
                        _text(candidate.get("expected_token_budget")),
                        _text(candidate.get("novelty_score")),
                        _text(candidate.get("machine_target")),
                        _text(candidate.get("model")),
                        _text(candidate.get("sandbox")),
                        self._json_text(source_payload_json),
                    ),
                )
                cur.execute(
                    """
                    insert into projects(project_id, project_name, project_dir, origin_idea_status)
                    values (%s,%s,%s,'testing')
                    on conflict (project_id) do update set
                      project_name=excluded.project_name,
                      project_dir=excluded.project_dir,
                      origin_idea_status=coalesce(nullif(projects.origin_idea_status,''), excluded.origin_idea_status),
                      updated_at=now()
                    """,
                    (idea_id, title, idea_id),
                )
                cur.execute(
                    """
                    insert into queue_items(
                      project_id,status,selection_rank,dispatch_priority,auto_continue,continue_count,max_continues,
                      retry_count,max_retries,current_run_id,current_session_id,last_run_state,last_event_type,
                      next_action_hint,manual_review_required,blocked_reason,last_error,last_result_summary,
                      machine_target,model,sandbox,last_dispatch_at,last_callback_at,stale_after,updated_at
                    ) values (
                      %s,'queued',50,50,true,0,0,0,2,'','','','','controller_review',false,'','','',
                      %s,%s,%s,null,null,null,now()
                    )
                    on conflict (project_id) do update set
                      machine_target=excluded.machine_target,
                      model=excluded.model,
                      sandbox=excluded.sandbox,
                      updated_at=now()
                    where queue_items.status not in ('dispatching', 'running', 'awaiting_wake', 'wake_received', 'reconciling')
                    """,
                    (
                        idea_id,
                        _text(candidate.get("machine_target")),
                        _text(candidate.get("model")),
                        _text(candidate.get("sandbox")),
                    ),
                )
                queue_rowcount = int(cur.rowcount or 0)
                promotion_key = f"research-promotion:{candidate_id}:{idea_id}"
                admission_inserted = self._insert_research_admission(
                    cur,
                    candidate_id=candidate_id,
                    admission_decision="admitted",
                    admission_reason=f"promoted to queued idea/project rows by {requested_by}",
                    score_breakdown=candidate.get("score_breakdown") or {},
                    admitted_idea_id=idea_id,
                    operator=requested_by,
                    idempotency_key=promotion_key,
                )
                cur.execute(
                    """
                    insert into research_lineage(source_type, source_id, target_type, target_id, relation_type, evidence_json)
                    select source_type, source_id, target_type, target_id, relation_type, evidence_json::jsonb
                    from (values
                      ('candidate', %s, 'idea', %s, 'admitted_as', %s),
                      ('idea', %s, 'project', %s, 'queued_as', %s)
                    ) as v(source_type, source_id, target_type, target_id, relation_type, evidence_json)
                    where not exists (
                      select 1 from research_lineage rl
                      where rl.source_type=v.source_type and rl.source_id=v.source_id
                        and rl.target_type=v.target_type and rl.target_id=v.target_id
                        and rl.relation_type=v.relation_type
                    )
                    """,
                    (
                        candidate_id,
                        idea_id,
                        self._json_text(
                            {
                                "admission_reason": _text(wb.get("admission_reason")),
                                "promoted_by": requested_by,
                            }
                        ),
                        idea_id,
                        idea_id,
                        self._json_text(
                            {"queued_by": requested_by, "dispatch_started": False}
                        ),
                    ),
                )
                response["queue_upserted"] = queue_rowcount
                response["admission_inserted"] = admission_inserted
                response["lineage_inserted"] = int(cur.rowcount or 0)
                return response

    def _upsert_research_source_record(
        self, cur: Any, source: dict[str, Any], candidate: dict[str, Any]
    ) -> bool:
        source_id = _text(source.get("source_id"))
        if not source_id:
            return False
        cur.execute(
            """
            insert into research_sources(source_id, source_kind, title, url, external_id, retrieved_at, summary, payload_json, content_hash)
            values (%s,%s,%s,%s,%s,nullif(%s,'')::timestamptz,%s,%s::jsonb,%s)
            on conflict (source_id) do update set
              source_kind=excluded.source_kind,
              title=excluded.title,
              url=excluded.url,
              external_id=excluded.external_id,
              summary=excluded.summary,
              payload_json=excluded.payload_json,
              content_hash=excluded.content_hash,
              updated_at=now()
            """,
            (
                source_id,
                _text(
                    source.get("source_kind") or candidate.get("source_kind") or "other"
                ),
                _text(source.get("title") or candidate.get("title")),
                _text(source.get("url")),
                _text(source.get("external_id")),
                _text(source.get("retrieved_at")),
                _text(source.get("summary")),
                self._json_text(source.get("payload_json") or {}),
                _text(source.get("content_hash"))
                or hashlib.sha256(self._json_text(source).encode("utf-8")).hexdigest(),
            ),
        )
        return True

    def _research_candidate_upsert_params(
        self,
        candidate: dict[str, Any],
        candidate_id: str,
        plan_json: dict[str, Any],
        source_ids: list[str],
        source_urls: list[str],
    ) -> tuple[Any, ...]:
        text = _research_candidate_text_value
        score = _research_candidate_float_value
        json_value = _research_candidate_json_value
        return (
            candidate_id,
            text(candidate, "generation_mode", "manual_import"),
            text(candidate, "status", "generated"),
            text(candidate, "title", candidate_id),
            text(candidate, "category"),
            text(candidate, "priority"),
            text(candidate, "source_kind"),
            self._json_text(source_ids),
            self._json_text(source_urls),
            text(candidate, "parent_project_id"),
            text(candidate, "parent_run_id"),
            text(candidate, "hypothesis"),
            text(candidate, "mechanism"),
            text(candidate, "description"),
            text(candidate, "implementation"),
            text(candidate, "baseline_to_beat"),
            text(candidate, "success_threshold"),
            text(candidate, "kill_condition"),
            text(candidate, "accessibility_delta"),
            self._json_text(json_value(candidate, "expected_artifacts", [])),
            self._json_text(json_value(candidate, "required_evidence", [])),
            self._json_text(json_value(candidate, "likely_failure_modes", [])),
            text(candidate, "estimated_runtime_class"),
            text(candidate, "expected_token_budget"),
            text(candidate, "machine_target"),
            text(candidate, "model"),
            text(candidate, "sandbox"),
            score(candidate, "novelty_score"),
            score(candidate, "feasibility_score"),
            score(candidate, "accessibility_score"),
            score(candidate, "falsifiability_score"),
            score(candidate, "total_score"),
            self._json_text(json_value(candidate, "score_breakdown", {})),
            text(candidate, "dedupe_key", candidate_id),
            self._json_text(json_value(candidate, "similar_prior_projects", [])),
            text(candidate, "novelty_comparison"),
            text(candidate, "risk_notes"),
            _research_candidate_rejection_reason(plan_json),
            text(candidate, "provider"),
            text(candidate, "provider_model"),
            text(candidate, "prompt_version"),
            text(candidate, "generated_by"),
            self._json_text(json_value(candidate, "raw_candidate_json", candidate)),
        )

    def _upsert_research_candidate_row(
        self,
        cur: Any,
        candidate: dict[str, Any],
        candidate_id: str,
        plan_json: dict[str, Any],
        source_ids: list[str],
        source_urls: list[str],
    ) -> None:
        cur.execute(
            """
            insert into research_candidates(
              candidate_id,generation_mode,status,title,category,priority,source_kind,source_ids,source_urls,
              parent_project_id,parent_run_id,hypothesis,mechanism,description,implementation,baseline_to_beat,
              success_threshold,kill_condition,accessibility_delta,expected_artifacts,required_evidence,likely_failure_modes,
              estimated_runtime_class,expected_token_budget,machine_target,model,sandbox,novelty_score,feasibility_score,
              accessibility_score,falsifiability_score,total_score,score_breakdown,dedupe_key,similar_prior_projects,
              novelty_comparison,risk_notes,rejection_reason,provider,provider_model,prompt_version,generated_by,raw_candidate_json
            ) values (
              %s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,
              %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s::jsonb
            )
            on conflict (candidate_id) do update set
              status=excluded.status,
              total_score=excluded.total_score,
              score_breakdown=excluded.score_breakdown,
              raw_candidate_json=excluded.raw_candidate_json,
              updated_at=now()
            """,
            self._research_candidate_upsert_params(
                candidate, candidate_id, plan_json, source_ids, source_urls
            ),
        )

    def _insert_source_candidate_lineage(
        self, cur: Any, source_ids: list[str], candidate_id: str
    ) -> int:
        inserted = 0
        for source_id in source_ids:
            cur.execute(
                """
                insert into research_lineage(source_type, source_id, target_type, target_id, relation_type, evidence_json)
                select 'source', %s, 'candidate', %s, 'generated_from', %s::jsonb
                where not exists (
                  select 1 from research_lineage
                  where source_type='source' and source_id=%s and target_type='candidate' and target_id=%s and relation_type='generated_from'
                )
                """,
                (
                    str(source_id),
                    candidate_id,
                    self._json_text({"source_ids": source_ids}),
                    str(source_id),
                    candidate_id,
                ),
            )
            inserted += int(cur.rowcount or 0)
        return inserted

    def _persist_research_facility_plan(
        self,
        cur: Any,
        plan: Any,
        *,
        requested_by: str,
        counters: dict[str, int],
    ) -> None:
        plan_json = _plan_to_json(plan)
        candidate = dict(plan_json.get("candidate") or {})
        candidate_id = str(candidate.get("candidate_id") or "").strip()
        if not candidate_id:
            return
        source_records = _candidate_source_records(candidate)
        source_ids = _unique_candidate_source_ids(candidate, source_records)
        source_urls = _candidate_source_url_list(candidate)
        for source in source_records:
            if self._upsert_research_source_record(cur, source, candidate):
                counters["sources_upserted"] += 1
        self._upsert_research_candidate_row(
            cur, candidate, candidate_id, plan_json, source_ids, source_urls
        )
        counters["candidates_upserted"] += 1
        counters["lineage_inserted"] += self._insert_source_candidate_lineage(
            cur, source_ids, candidate_id
        )
        idempotency_key = (
            f"research-admission:{candidate_id}:{plan_json.get('admission_decision')}"
        )
        counters["admissions_inserted"] += self._insert_research_admission(
            cur,
            candidate_id=candidate_id,
            admission_decision=str(
                plan_json.get("admission_decision") or "needs_review"
            ),
            admission_reason=str(plan_json.get("admission_reason") or ""),
            score_breakdown=plan_json.get("score_breakdown") or {},
            admitted_idea_id=None,
            operator=requested_by,
            idempotency_key=idempotency_key,
        )

    def record_research_facility_plans(
        self, plans: Sequence[Any], *, requested_by: str, queue_admitted: bool = False
    ) -> dict[str, Any]:
        """Persist Research Facility candidate/admission ledgers.

        This method intentionally does not queue admitted ideas unless
        ``queue_admitted`` is explicitly enabled by a later, bounded promotion
        path.  The dashboard generation smoke uses it only for source,
        candidate, admission, and lineage ledgers.
        """

        if queue_admitted:
            raise ValueError(
                "queue_admitted promotion is not supported by this ledger-only writer"
            )
        counters = {
            "sources_upserted": 0,
            "candidates_upserted": 0,
            "admissions_inserted": 0,
            "lineage_inserted": 0,
        }
        with self._connect() as conn:
            with conn.cursor() as cur:
                for plan in plans:
                    self._persist_research_facility_plan(
                        cur, plan, requested_by=requested_by, counters=counters
                    )
        return counters

    def paper_notion_projection(self) -> list[dict[str, Any]]:
        return [
            {
                "paper_id": paper.get("paper_id") or "",
                "project_id": paper.get("project_id") or "",
                "project_name": paper.get("project_name")
                or paper.get("project_id")
                or "",
                "paper_status": paper.get("paper_status") or "",
                "paper_type": paper.get("paper_type") or "",
                "run_id": paper.get("run_id") or "",
                "draft_markdown_path": paper.get("draft_markdown_path") or "",
                "draft_latex_path": paper.get("draft_latex_path") or "",
                "evidence_bundle_path": paper.get("evidence_bundle_path") or "",
                "claim_ledger_path": paper.get("claim_ledger_path") or "",
                "manifest_path": paper.get("manifest_path") or "",
                "notion_page_url": paper.get("notion_page_url") or "",
                "updated_at": paper.get("updated_at") or "",
            }
            for paper in self.paper_rows()
        ]

    def _replayed_event_id(
        self,
        idempotency_key: str,
        payload: dict[str, Any],
        *,
        event_type: str,
        entity_type: str,
        entity_id: str,
    ) -> int | None:
        payload_hash = _hash(payload)
        row = self._one(
            "select event_id, event_type, entity_type, entity_id, payload_hash from control_events where idempotency_key = %s",
            (idempotency_key,),
        )
        if row is None:
            return None
        if (
            row["event_type"] != event_type
            or row["entity_type"] != entity_type
            or row["entity_id"] != entity_id
            or row["payload_hash"] != payload_hash
        ):
            raise IdempotencyConflict(
                f"idempotency key {idempotency_key!r} was reused with different event identity"
            )
        return int(row["event_id"])

    def mark_dispatch_started(
        self,
        *,
        project_id: str,
        run_id: str,
        session_id: str,
        dispatch_payload: dict[str, Any],
        requested_by: str,
    ) -> tuple[int, dict[str, Any]]:
        now = utc_now()
        event_payload = {
            "requested_by": requested_by,
            "run_id": run_id,
            "session_id": session_id,
            "dispatch": dispatch_payload,
        }
        with self._connect() as conn:
            with conn.cursor() as cur:
                event_id, inserted = self._append_event_in_cursor(
                    cur,
                    idempotency_key=f"live-dispatch:{run_id}",
                    event_type="controller.live_dispatch",
                    entity_type="project",
                    entity_id=project_id,
                    payload=event_payload,
                )
                if not inserted:
                    rows = self._queue_rows_from_cursor(
                        cur, "where q.project_id = %s", (project_id,)
                    )
                    return event_id, rows[0] if rows else {}
                cur.execute(
                    """
                    update queue_items
                    set status=%s, current_run_id=%s, current_session_id=%s, last_run_state=%s,
                        last_event_type=%s, next_action_hint=%s, last_error=%s, last_result_summary=%s,
                        last_dispatch_at=%s, updated_at=%s
                    where project_id=%s
                    """,
                    (
                        QueueStatus.AWAITING_WAKE.value,
                        run_id,
                        session_id,
                        QueueStatus.AWAITING_WAKE.value,
                        "live_dispatch",
                        "await_callback",
                        "",
                        "",
                        now,
                        now,
                        project_id,
                    ),
                )
                cur.execute(
                    """
                    insert into runs(run_id,project_id,session_id,state,dispatch_mode,started_at,ended_at,last_callback_at,gate_state,current_activity,idempotency_key,updated_at)
                    values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    on conflict (run_id) do update set
                      project_id=excluded.project_id, session_id=excluded.session_id, state=excluded.state,
                      dispatch_mode=excluded.dispatch_mode, started_at=excluded.started_at, ended_at=excluded.ended_at,
                      last_callback_at=excluded.last_callback_at, gate_state=excluded.gate_state,
                      current_activity=excluded.current_activity, idempotency_key=excluded.idempotency_key, updated_at=excluded.updated_at
                    """,
                    (
                        run_id,
                        project_id,
                        session_id,
                        "running",
                        "exec",
                        now,
                        None,
                        None,
                        "running",
                        "dispatched",
                        f"live-dispatch:{run_id}",
                        now,
                    ),
                )
        return event_id, self.queue_row(project_id) or {}

    def _replayed_worker_callback_event_id(
        self, idempotency_key: str, incoming_payload: dict[str, Any]
    ) -> int | None:
        """Return existing worker callback event id for an exact incoming retry."""

        row = self._one(
            "select event_id, payload_json from control_events where idempotency_key = %s",
            (idempotency_key,),
        )
        if row is None or "payload_json" not in row:
            return None
        raw_payload = row.get("payload_json")
        if isinstance(raw_payload, dict):
            existing_payload = raw_payload
        else:
            try:
                existing_payload = json.loads(raw_payload or "{}")
            except (TypeError, json.JSONDecodeError) as exc:
                raise IdempotencyConflict(
                    f"idempotency key {idempotency_key!r} has unreadable payload"
                ) from exc
        if not isinstance(existing_payload, dict):
            raise IdempotencyConflict(
                f"idempotency key {idempotency_key!r} has non-object payload"
            )
        existing_callback_payload = {
            key: value
            for key, value in existing_payload.items()
            if key not in WORKER_CALLBACK_AUDIT_KEYS
        }
        incoming_callback_payload = {
            key: value
            for key, value in incoming_payload.items()
            if key not in WORKER_CALLBACK_AUDIT_KEYS
        }
        if existing_callback_payload != incoming_callback_payload:
            raise IdempotencyConflict(
                f"idempotency key {idempotency_key!r} was reused with different callback payload"
            )
        return int(row["event_id"])

    def _resolve_worker_callback_project_id(self, project_id: str, run_id: str) -> str:
        if project_id or not run_id:
            return project_id
        row = self._one("select project_id from runs where run_id = %s", (run_id,))
        return _text(row.get("project_id") if row else "")

    def _worker_callback_queue_snapshot(
        self, project_id: str, run_id: str
    ) -> tuple[dict[str, Any] | None, bool, str]:
        if not project_id:
            return None, False, ""
        current_queue_row = self._one(
            "select status,current_run_id,current_session_id,last_run_state,next_action_hint from queue_items where project_id = %s",
            (project_id,),
        )
        current_run_id = _text((current_queue_row or {}).get("current_run_id"))
        current_status = _text((current_queue_row or {}).get("status"))
        stale_callback = bool(
            current_queue_row is not None and (not run_id or current_run_id != run_id)
        )
        return current_queue_row, stale_callback, current_status

    def _worker_callback_result_row(self, project_id: str) -> dict[str, Any]:
        return self.queue_row(project_id) or {}

    def _emit_worker_callback_side_effect(
        self,
        *,
        idempotency_key: str,
        event_payload: dict[str, Any],
        event_type: str,
        run_id: str,
        project_id: str,
    ) -> tuple[int, bool, dict[str, Any]]:
        event_type_name = _worker_callback_event_type_name(event_type)
        entity_id = _worker_callback_entity_id(run_id, project_id)
        replayed_event_id = self._replayed_event_id(
            idempotency_key,
            event_payload,
            event_type=event_type_name,
            entity_type="run",
            entity_id=entity_id,
        )
        if replayed_event_id is not None:
            return (
                replayed_event_id,
                False,
                self._worker_callback_result_row(project_id),
            )
        event_id, inserted = self.append_event(
            idempotency_key=idempotency_key,
            event_type=event_type_name,
            entity_type="run",
            entity_id=entity_id,
            payload=event_payload,
        )
        return event_id, inserted, self._worker_callback_result_row(project_id)

    def _try_record_late_terminal_success_worker_callback(
        self,
        *,
        payload: dict[str, Any],
        current_queue_row: dict[str, Any] | None,
        run_id: str,
        project_id: str,
        event_type: str,
        idempotency_key: str,
        received_by: str,
    ) -> tuple[int, bool, dict[str, Any]] | None:
        if not (
            _completed_success_queue_row(current_queue_row, run_id)
            and event_type not in TERMINAL_SUCCESS_CALLBACK_STATES
        ):
            return None
        assert current_queue_row is not None
        event_payload = _late_terminal_success_worker_callback_payload(
            payload, current_queue_row, received_by=received_by
        )
        return self._emit_worker_callback_side_effect(
            idempotency_key=idempotency_key,
            event_payload=event_payload,
            event_type=event_type,
            run_id=run_id,
            project_id=project_id,
        )

    def _try_record_stale_worker_callback(
        self,
        *,
        payload: dict[str, Any],
        current_queue_row: dict[str, Any] | None,
        stale_callback: bool,
        run_id: str,
        project_id: str,
        event_type: str,
        idempotency_key: str,
        received_by: str,
        current_status: str,
    ) -> tuple[int, bool, dict[str, Any]] | None:
        if not (stale_callback and current_queue_row):
            return None
        preserved_status = (
            _text(current_queue_row.get("status")) or QueueStatus.NEEDS_REVIEW.value
        )
        preserved_hint = (
            _text(current_queue_row.get("next_action_hint")) or "await_callback"
        )
        event_payload = _stale_worker_callback_payload(
            payload,
            current_queue_row,
            received_by=received_by,
            status=preserved_status,
            next_action_hint=preserved_hint,
            ignore_reason=_stale_worker_callback_ignore_reason(
                run_id=run_id, current_status=current_status
            ),
        )
        return self._emit_worker_callback_side_effect(
            idempotency_key=idempotency_key,
            event_payload=event_payload,
            event_type=event_type,
            run_id=run_id,
            project_id=project_id,
        )

    def _persist_applied_worker_callback(
        self,
        cur: Any,
        *,
        now: str,
        payload: dict[str, Any],
        project_id: str,
        run_id: str,
        event_type: str,
        idempotency_key: str,
        event_payload: dict[str, Any],
        status: str,
        next_action_hint: str,
        manual_review_required: bool,
        last_error: str,
    ) -> tuple[int, bool]:
        summary = (
            f"worker callback {event_type}: "
            f"{_text(payload.get('reason')) or 'worker reported ready'}"
        )
        last_run_state, run_state, gate_state = _contract_worker_callback_states(
            event_type, _text(payload.get("gate_state"))
        )
        run_ended_at = None if event_type == "session_started" else now
        if project_id:
            cur.execute(
                """
                update queue_items
                set status=%s, current_session_id=coalesce(nullif(%s, ''), current_session_id), last_run_state=%s,
                    last_event_type=%s, next_action_hint=%s, manual_review_required=%s, last_error=%s,
                    last_result_summary=%s, last_callback_at=%s, updated_at=%s
                where project_id=%s
                """,
                (
                    status,
                    _text(payload.get("session_id")),
                    last_run_state,
                    "worker_callback",
                    next_action_hint,
                    manual_review_required,
                    last_error,
                    summary,
                    now,
                    now,
                    project_id,
                ),
            )
        if run_id and project_id:
            cur.execute(
                """
                insert into runs(run_id,project_id,session_id,state,dispatch_mode,started_at,ended_at,last_callback_at,gate_state,current_activity,idempotency_key,updated_at)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                on conflict (run_id) do update set
                    session_id=coalesce(nullif(excluded.session_id, ''), runs.session_id),
                    state=excluded.state,
                    ended_at=excluded.ended_at,
                    last_callback_at=excluded.last_callback_at,
                    gate_state=excluded.gate_state,
                    current_activity=excluded.current_activity,
                    updated_at=excluded.updated_at
                """,
                (
                    run_id,
                    project_id,
                    _text(payload.get("session_id")),
                    run_state,
                    "callback",
                    now,
                    run_ended_at,
                    now,
                    gate_state,
                    "worker_callback",
                    idempotency_key,
                    now,
                ),
            )
        return self._append_event_in_cursor(
            cur,
            idempotency_key=idempotency_key,
            event_type=_worker_callback_event_type_name(event_type),
            entity_type="run",
            entity_id=_worker_callback_entity_id(run_id, project_id),
            payload=event_payload,
        )

    def record_worker_callback(
        self, callback: Any, *, received_by: str = "worker-callback"
    ) -> tuple[int, bool, dict[str, Any]]:
        now = utc_now()
        payload = _worker_callback_payload(callback)
        run_id = _text(payload.get("run_id"))
        project_id = _text(payload.get("project_id"))
        event_type = _text(payload.get("event_type"))
        idempotency_key = _derived_worker_callback_idempotency_key(
            payload,
            run_id=run_id,
            event_type=event_type,
            idempotency_key=_text(payload.get("idempotency_key")),
        )
        project_id = self._resolve_worker_callback_project_id(project_id, run_id)
        replayed_callback_event_id = self._replayed_worker_callback_event_id(
            idempotency_key, payload
        )
        if replayed_callback_event_id is not None:
            return (
                replayed_callback_event_id,
                False,
                self._worker_callback_result_row(project_id),
            )
        current_queue_row, stale_callback, current_status = (
            self._worker_callback_queue_snapshot(project_id, run_id)
        )
        late_result = self._try_record_late_terminal_success_worker_callback(
            payload=payload,
            current_queue_row=current_queue_row,
            run_id=run_id,
            project_id=project_id,
            event_type=event_type,
            idempotency_key=idempotency_key,
            received_by=received_by,
        )
        if late_result is not None:
            return late_result
        status, next_action_hint, manual_review_required, last_error = (
            _worker_callback_transition(event_type, payload)
        )
        stale_result = self._try_record_stale_worker_callback(
            payload=payload,
            current_queue_row=current_queue_row,
            stale_callback=stale_callback,
            run_id=run_id,
            project_id=project_id,
            event_type=event_type,
            idempotency_key=idempotency_key,
            received_by=received_by,
            current_status=current_status,
        )
        if stale_result is not None:
            return stale_result
        event_payload = {
            **payload,
            "received_by": received_by,
            "applied_status": status,
            "applied_next_action_hint": next_action_hint,
        }
        replayed_event_id = self._replayed_event_id(
            idempotency_key,
            event_payload,
            event_type=_worker_callback_event_type_name(event_type),
            entity_type="run",
            entity_id=_worker_callback_entity_id(run_id, project_id),
        )
        if replayed_event_id is not None:
            return (
                replayed_event_id,
                False,
                self._worker_callback_result_row(project_id),
            )
        with self._connect() as conn:
            with conn.cursor() as cur:
                event_id, inserted = self._persist_applied_worker_callback(
                    cur,
                    now=now,
                    payload=payload,
                    project_id=project_id,
                    run_id=run_id,
                    event_type=event_type,
                    idempotency_key=idempotency_key,
                    event_payload=event_payload,
                    status=status,
                    next_action_hint=next_action_hint,
                    manual_review_required=bool(manual_review_required),
                    last_error=last_error,
                )
        return event_id, inserted, self._worker_callback_result_row(project_id)

    def record_project_decision_gate(
        self,
        *,
        project_id: str,
        run_id: str = "",
        artifact_root: str | Path,
        decided_at: str | None = None,
    ) -> dict[str, Any]:
        """Persist the local project decision artifact into Supabase.

        Filesystem artifacts remain the worker's durable evidence bundle, but
        Supabase owns the operator ledger after cutover. Missing artifacts are
        not persisted as decisions; the paper_eligibility view already treats
        absent rows as `missing` and non-writable.
        """
        project_id = _text(project_id)
        if not project_id:
            return {"ok": False, "persisted": False, "reason": "missing project_id"}
        artifact_root_path = _expanduser_or_none(str(artifact_root))
        if artifact_root_path is None:
            return {
                "ok": False,
                "persisted": False,
                "reason": "artifact root contains an unexpandable user home",
            }
        gate = paper_draft_decision_gate(artifact_root_path)
        if (
            not gate.get("values")
            and gate.get("reason") == "missing project decision artifact"
        ):
            return {
                "ok": True,
                "persisted": False,
                "reason": "missing project decision artifact",
                "gate": gate,
            }
        artifact_path = artifact_root_path / ".enoch" / PROJECT_DECISION_JSON_FILENAME
        if not artifact_path.exists():
            artifact_path = artifact_root_path / ".omx" / PROJECT_DECISION_JSON_FILENAME
        if not artifact_path.exists():
            artifact_path = artifact_root_path / PROJECT_DECISION_JSON_FILENAME
        decision_payload = project_decision_payload(artifact_root_path)
        followup = followup_candidate_from_decision_payload(decision_payload)
        run_id_value = _text(run_id) or None
        idea_source_payload: dict[str, Any] = {}
        with self._connect() as conn:
            with conn.cursor() as cur:
                source_row = cur.execute(
                    "select source_payload_json from ideas where idea_id = %s",
                    (project_id,),
                ).fetchone()
                if source_row:
                    raw_source = (
                        source_row[0]
                        if not isinstance(source_row, dict)
                        else source_row.get("source_payload_json")
                    )
                    if isinstance(raw_source, dict):
                        idea_source_payload = raw_source
                    elif isinstance(raw_source, str):
                        idea_source_payload = _json_dict(raw_source)
                followup_depth = _enforced_followup_depth(
                    decision_payload, {"source_payload_json": idea_source_payload}
                )
                payload = {
                    "gate": gate,
                    "project_root": str(artifact_root_path),
                    "project_decision": decision_payload,
                    "idea_source_payload_json": idea_source_payload,
                    "enforced_followup_depth": followup_depth,
                }
                payload_json = _json(payload)
                if run_id_value:
                    found_run = cur.execute(
                        "select 1 from runs where run_id = %s", (run_id_value,)
                    ).fetchone()
                    if not found_run:
                        run_id_value = None
                cur.execute(
                    """
                    insert into project_decisions(project_id, run_id, decision_type, decision_gate_state,
                      decision_summary, artifact_path, payload_json, payload_hash, decided_at,
                      followup_recommended, followup_type, followup_title, followup_hypothesis,
                      followup_required_evidence, followup_success_threshold, followup_stop_condition, followup_depth)
                    values (%s,%s,'project_outcome',%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
                    on conflict (project_id, run_id, decision_type) do update set
                      decision_gate_state=excluded.decision_gate_state,
                      decision_summary=excluded.decision_summary,
                      artifact_path=excluded.artifact_path,
                      payload_json=excluded.payload_json,
                      payload_hash=excluded.payload_hash,
                      decided_at=excluded.decided_at,
                      followup_recommended=excluded.followup_recommended,
                      followup_type=excluded.followup_type,
                      followup_title=excluded.followup_title,
                      followup_hypothesis=excluded.followup_hypothesis,
                      followup_required_evidence=excluded.followup_required_evidence,
                      followup_success_threshold=excluded.followup_success_threshold,
                      followup_stop_condition=excluded.followup_stop_condition,
                      followup_depth=excluded.followup_depth,
                      updated_at=now()
                    where project_decisions.decided_at is null or excluded.decided_at >= project_decisions.decided_at
                    """,
                    (
                        project_id,
                        run_id_value,
                        _decision_gate_state(gate),
                        _decision_summary(gate),
                        str(artifact_path),
                        payload_json,
                        _hash(payload),
                        decided_at or utc_now(),
                        bool(followup.get("followup_recommended")),
                        _text(followup.get("followup_type")),
                        _text(followup.get("followup_title")),
                        _text(followup.get("followup_hypothesis")),
                        _json(followup.get("followup_required_evidence") or []),
                        _text(followup.get("followup_success_threshold")),
                        _text(followup.get("followup_stop_condition")),
                        followup_depth,
                    ),
                )
                persisted = getattr(cur, "rowcount", None) != 0
        if not persisted:
            return {
                "ok": True,
                "persisted": False,
                "project_id": project_id,
                "run_id": run_id_value or "",
                "reason": "stale project decision ignored",
                "decision_gate_state": _decision_gate_state(gate),
                "decision_summary": _decision_summary(gate),
                "artifact_path": str(artifact_path),
            }
        return {
            "ok": True,
            "persisted": True,
            "project_id": project_id,
            "run_id": run_id_value or "",
            "decision_gate_state": _decision_gate_state(gate),
            "decision_summary": _decision_summary(gate),
            "artifact_path": str(artifact_path),
            **followup,
            "followup_depth": followup_depth,
        }

    def next_followup_candidate(
        self, *, project_id: str = "", max_followup_depth: int = 4
    ) -> dict[str, Any] | None:
        clauses = [
            "q.status = %s",
            "q.manual_review_required = false",
            "coalesce(pe.followup_recommended, false) = true",
            "coalesce(pe.followup_title, '') <> ''",
            "coalesce(pe.followup_hypothesis, '') <> ''",
            """(
                select count(*)
                from jsonb_array_elements_text(
                    case
                        when jsonb_typeof(coalesce(pe.followup_required_evidence, '[]'::jsonb)) = 'array'
                        then coalesce(pe.followup_required_evidence, '[]'::jsonb)
                        else '[]'::jsonb
                    end
                ) as evidence(item)
                where btrim(evidence.item) <> ''
            ) >= 2""",
            "lower(replace(replace(coalesce(pe.followup_type, ''), '-', '_'), ' ', '_')) in ('deepen', 'branch', 'retry')",
            "coalesce(pe.followup_success_threshold, '') <> ''",
            "coalesce(pe.followup_stop_condition, '') <> ''",
            "greatest(coalesce(pe.followup_depth, 0), case when coalesce(i.source_payload_json->>'followup_depth', '') ~ '^[0-9]+$' then (i.source_payload_json->>'followup_depth')::integer when coalesce(i.source_payload_json->>'parent_followup_depth', '') ~ '^[0-9]+$' then (i.source_payload_json->>'parent_followup_depth')::integer else 0 end) < %s",
            "not coalesce(pe.has_live_paper_row, false)",
            "not exists (select 1 from control_events ev where ev.event_type = 'followup.launch' and ev.entity_type = 'project' and ev.entity_id = q.project_id)",
        ]
        params: list[Any] = [QueueStatus.COMPLETED.value, max_followup_depth]
        if project_id:
            clauses.append("q.project_id = %s")
            params.append(project_id)
        rows = self._queue_rows(
            "left join paper_eligibility pe on pe.project_id = q.project_id "
            + "where "
            + " and ".join(clauses)
            + " order by q.updated_at desc",
            params,
        )
        candidates = [
            row
            for row in rows
            if ranked_followup_readiness(
                row,
                max_followup_depth=max_followup_depth,
                explicit_project=bool(project_id),
            )["ready"]
        ]
        candidates.sort(key=promising_followup_priority_key)
        return candidates[0] if candidates else None

    def launch_followup_candidate(
        self,
        *,
        project_id: str = "",
        dry_run: bool = True,
        requested_by: str = "operator",
        max_followup_depth: int = 4,
    ) -> dict[str, Any]:
        candidate = self.next_followup_candidate(
            project_id=project_id, max_followup_depth=max_followup_depth
        )
        if not candidate:
            return {
                "ok": True,
                "action": "noop",
                "reason": "no follow-up candidate",
                "candidate": None,
                "followup": None,
            }
        title = (
            _text(candidate.get("followup_title"))
            or f"Follow-up: {_text(candidate.get('project_name')) or _text(candidate.get('project_id'))}"
        )
        hypothesis = _text(candidate.get("followup_hypothesis")) or _text(
            candidate.get("operator_explanation")
        )
        parent_id = _text(candidate.get("project_id"))
        followup_id = _stable_followup_id(parent_id, title, hypothesis)
        depth = _int(candidate.get("followup_depth"), 0) + 1
        followup_payload = {
            "idea_id": followup_id,
            "title": title,
            "parent_project_id": parent_id,
            "parent_run_id": _text(candidate.get("current_run_id")),
            "followup_depth": depth,
            "followup_type": _text(candidate.get("followup_type"))
            .lower()
            .replace("-", "_")
            .replace(" ", "_"),
            "followup_hypothesis": hypothesis,
            "followup_required_evidence": _followup_required_evidence_items(candidate),
            "followup_success_threshold": _text(
                candidate.get("followup_success_threshold")
            ),
            "followup_stop_condition": _text(candidate.get("followup_stop_condition")),
            **_followup_escalation_payload(candidate, depth),
        }
        parent_source = _followup_parent_source_record(candidate, followup_payload)
        if dry_run:
            return {
                "ok": True,
                "action": "dry_run_followup",
                "reason": "follow-up candidate selected; no row inserted",
                "candidate": candidate,
                "followup": followup_payload,
            }
        now = utc_now()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "select idea_id, title, source_payload_json from ideas where idea_id = %s",
                    (followup_id,),
                )
                existing_idea = cur.fetchone()
                if existing_idea and (
                    self._row_value(existing_idea, "title", 1) != title
                    or self._json_text(
                        self._row_value(existing_idea, "source_payload_json", 2)
                    )
                    != self._json_text(followup_payload)
                ):
                    raise IdempotencyConflict(
                        f"follow-up idea id {followup_id!r} was reused with different idea identity"
                    )
                cur.execute(
                    """
                    insert into ideas(
                      idea_id, title, idea_status, category, priority, source_kind, source_external_url, description, implementation,
                      baseline_to_beat, kill_condition, expected_token_budget, confidence, feasibility, leverage,
                      machine_target, model, sandbox, selection_rank, dispatch_priority, source_payload_json, created_at, updated_at
                    ) values (%s,%s,'testing','follow-up','High','followup_branch',%s,%s,%s,%s,%s,'medium','medium','medium','high',%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
                    on conflict (idea_id) do nothing
                    """,
                    (
                        followup_id,
                        title,
                        parent_source["url"],
                        hypothesis,
                        "Bounded follow-up investigation generated from prior no-paper evidence; do not write a paper unless this run independently becomes paper-positive.",
                        _text(candidate.get("project_name")),
                        _text(candidate.get("followup_stop_condition")),
                        _text(candidate.get("machine_target")),
                        _text(candidate.get("model")),
                        _text(candidate.get("sandbox")),
                        _int(candidate.get("selection_rank"), 50),
                        _int(candidate.get("dispatch_priority"), 50),
                        _json(followup_payload),
                        now,
                        now,
                    ),
                )
                cur.execute(
                    "select project_id, project_name, project_dir, origin_idea_status from projects where project_id = %s",
                    (followup_id,),
                )
                existing_project = cur.fetchone()
                if existing_project and (
                    self._row_value(existing_project, "project_name", 1) != title
                    or self._row_value(existing_project, "project_dir", 2)
                    != followup_id
                    or self._row_value(existing_project, "origin_idea_status", 3)
                    != "testing"
                ):
                    raise IdempotencyConflict(
                        f"follow-up project id {followup_id!r} was reused with different project identity"
                    )
                cur.execute(
                    """
                    insert into projects(project_id, project_name, project_dir, notion_page_url, notion_page_id, origin_idea_status, created_at, updated_at)
                    values (%s,%s,%s,'','','testing',%s,%s)
                    on conflict (project_id) do nothing
                    """,
                    (followup_id, title, followup_id, now, now),
                )
                cur.execute(
                    "select project_id, status, current_run_id, next_action_hint from queue_items where project_id = %s",
                    (followup_id,),
                )
                existing_queue = cur.fetchone()
                if existing_queue and (
                    self._row_value(existing_queue, "status", 1)
                    != QueueStatus.QUEUED.value
                    or self._row_value(existing_queue, "current_run_id", 2)
                    or self._row_value(existing_queue, "next_action_hint", 3)
                    != "controller_review"
                ):
                    raise IdempotencyConflict(
                        f"follow-up queue id {followup_id!r} was reused with different queue identity"
                    )
                cur.execute(
                    """
                    insert into queue_items(project_id,status,selection_rank,dispatch_priority,auto_continue,continue_count,max_continues,retry_count,max_retries,current_run_id,current_session_id,last_run_state,last_event_type,next_action_hint,manual_review_required,blocked_reason,last_error,last_result_summary,machine_target,model,sandbox,last_dispatch_at,last_callback_at,stale_after,updated_at)
                    values (%s,'queued',%s,%s,true,0,0,0,2,'','','','','controller_review',false,'','','',%s,%s,%s,null,null,null,%s)
                    on conflict (project_id) do nothing
                    """,
                    (
                        followup_id,
                        _int(candidate.get("selection_rank"), 50),
                        _int(candidate.get("dispatch_priority"), 50),
                        _text(candidate.get("machine_target")),
                        _text(candidate.get("model")),
                        _text(candidate.get("sandbox")),
                        now,
                    ),
                )
                cur.execute(
                    """
                    insert into research_sources(source_id, source_kind, title, url, external_id, retrieved_at, summary, payload_json, content_hash)
                    values (%s,%s,%s,%s,%s,null,%s,%s::jsonb,%s)
                    on conflict (source_id) do update set
                      source_kind=excluded.source_kind,
                      title=excluded.title,
                      url=excluded.url,
                      external_id=excluded.external_id,
                      summary=excluded.summary,
                      payload_json=excluded.payload_json,
                      content_hash=excluded.content_hash,
                      updated_at=now()
                    """,
                    (
                        parent_source["source_id"],
                        parent_source["source_kind"],
                        parent_source["title"],
                        parent_source["url"],
                        parent_source["external_id"],
                        parent_source["summary"],
                        self._json_text(parent_source["payload_json"]),
                        hashlib.sha256(
                            self._json_text(parent_source["payload_json"]).encode(
                                "utf-8"
                            )
                        ).hexdigest(),
                    ),
                )
                cur.execute(
                    """
                    insert into research_lineage(source_type, source_id, target_type, target_id, relation_type, evidence_json)
                    select source_type, source_id, target_type, target_id, relation_type, evidence_json::jsonb
                    from (values
                      ('source', %s, 'candidate', %s, 'generated_from', %s),
                      ('project', %s, 'project', %s, 'followup_parent', %s)
                    ) as v(source_type, source_id, target_type, target_id, relation_type, evidence_json)
                    where not exists (
                      select 1 from research_lineage rl
                      where rl.source_type=v.source_type and rl.source_id=v.source_id
                        and rl.target_type=v.target_type and rl.target_id=v.target_id
                        and rl.relation_type=v.relation_type
                    )
                    """,
                    (
                        parent_source["source_id"],
                        followup_id,
                        self._json_text(
                            {
                                "source_id": parent_source["source_id"],
                                "source_url": parent_source["url"],
                                "captured_by": "followup.launch",
                            }
                        ),
                        parent_id,
                        followup_id,
                        self._json_text(
                            {
                                "parent_run_id": _text(candidate.get("current_run_id")),
                                "followup_type": followup_payload["followup_type"],
                            }
                        ),
                    ),
                )
                event_id, _inserted = self._append_event_in_cursor(
                    cur,
                    idempotency_key=f"followup.launch:{parent_id}:{followup_id}",
                    event_type="followup.launch",
                    entity_type="project",
                    entity_id=parent_id,
                    payload={
                        "requested_by": requested_by,
                        "candidate": {"project_id": parent_id},
                        "followup": followup_payload,
                    },
                )
        return {
            "ok": True,
            "action": "followup_queued",
            "reason": "bounded follow-up queued",
            "candidate": candidate,
            "followup": followup_payload,
            "event_id": event_id,
        }

    def mark_queue_item_paused(
        self, *, project_id: str, reason: str, updated_by: str = "operator"
    ) -> bool:
        now = utc_now()
        with self._connect() as conn:
            with conn.cursor() as cur:
                result = cur.execute(
                    """
                    update queue_items
                    set status=%s, next_action_hint=%s, last_result_summary=%s, updated_at=%s
                    where project_id=%s
                    """,
                    (
                        QueueStatus.PAUSED.value,
                        "maintenance_cutover_reconcile",
                        reason,
                        now,
                        project_id,
                    ),
                )
                if result.rowcount < 1:
                    return False
                self._append_event_in_cursor(
                    cur,
                    idempotency_key=f"queue-item-paused:{project_id}:{now}",
                    event_type="queue.item_paused",
                    entity_type="project",
                    entity_id=project_id,
                    payload={"reason": reason, "updated_by": updated_by},
                )
        return True

    def update_project_dir(self, project_id: str, project_dir: str) -> None:
        now = utc_now()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update projects set project_dir=%s, updated_at=%s where project_id=%s",
                    (_text(project_dir), now, project_id),
                )

    def _upsert_paper_in_cursor(self, cur: Any, paper: PaperRecord) -> None:
        status = (
            paper.paper_status.value
            if hasattr(paper.paper_status, "value")
            else str(paper.paper_status)
        )
        cur.execute(
            "select project_id, run_id, paper_type, updated_at from papers where paper_id=%s",
            (paper.paper_id,),
        )
        existing = cur.fetchone()
        existing_run_id = (
            _text(self._row_value(existing, "run_id", 1)) if existing else ""
        )
        if existing and (
            self._row_value(existing, "project_id", 0) != _text(paper.project_id)
            or (existing_run_id and existing_run_id != _text(paper.run_id))
            or self._row_value(existing, "paper_type", 2) != _text(paper.paper_type)
        ):
            raise IdempotencyConflict(
                f"paper id {paper.paper_id!r} was reused with different paper identity"
            )
        if existing and _is_older_timestamp(
            paper.updated_at, existing.get("updated_at")
        ):
            return
        cur.execute(
            """
            insert into papers(paper_id,project_id,run_id,paper_type,paper_status,draft_markdown_path,draft_latex_path,evidence_bundle_path,claim_ledger_path,manifest_path,generated_at,updated_at)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            on conflict (paper_id) do update set
              project_id=excluded.project_id, run_id=excluded.run_id, paper_type=excluded.paper_type,
              paper_status=excluded.paper_status, draft_markdown_path=excluded.draft_markdown_path,
              draft_latex_path=excluded.draft_latex_path, evidence_bundle_path=excluded.evidence_bundle_path,
              claim_ledger_path=excluded.claim_ledger_path, manifest_path=excluded.manifest_path,
              generated_at=excluded.generated_at, updated_at=excluded.updated_at
            """,
            (
                paper.paper_id,
                paper.project_id,
                _text(paper.run_id) or None,
                paper.paper_type,
                status,
                paper.draft_markdown_path,
                paper.draft_latex_path,
                paper.evidence_bundle_path,
                paper.claim_ledger_path,
                paper.manifest_path,
                paper.generated_at,
                paper.updated_at,
            ),
        )

    def upsert_paper(self, paper: PaperRecord) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._upsert_paper_in_cursor(cur, paper)

    def record_paper_draft(
        self,
        *,
        paper: PaperRecord,
        project_dir: str,
        idempotency_key: str,
        event_payload: dict[str, Any],
    ) -> tuple[int, bool]:
        now = utc_now()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update projects set project_dir=%s, updated_at=%s where project_id=%s",
                    (_text(project_dir), now, paper.project_id),
                )
                self._upsert_paper_in_cursor(cur, paper)
                return self._append_event_in_cursor(
                    cur,
                    idempotency_key=idempotency_key,
                    event_type="paper.drafted",
                    entity_type="paper",
                    entity_id=paper.paper_id,
                    payload=event_payload,
                )

    def import_snapshot(
        self, request: ImportSnapshotRequest
    ) -> tuple[bool, int, int, int]:
        queue_rows = [*request.queue_rows, *_snapshot_rows(request.queue_snapshot)]
        paper_rows = [
            *request.paper_rows,
            *_snapshot_rows(request.paper_snapshot, paper=True),
        ]
        _validate_import_snapshot_rows(queue_rows, paper_rows)
        event_payload = _import_snapshot_event_payload(request, queue_rows, paper_rows)
        projects = queue_items = papers = 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                _, inserted = self._append_event_in_cursor(
                    cur,
                    idempotency_key=request.idempotency_key,
                    event_type="legacy.import_snapshot",
                    entity_type="snapshot",
                    entity_id=request.source,
                    payload=event_payload,
                )
                if not inserted:
                    return False, 0, 0, 0
                for raw in queue_rows:
                    row_projects, row_queue_items = _supabase_import_queue_row(cur, raw)
                    projects += row_projects
                    queue_items += row_queue_items
                for raw in paper_rows:
                    papers += _supabase_import_paper_row(cur, raw)
        return inserted, projects, queue_items, papers


def _supabase_queue_status_value(raw: dict[str, Any]) -> str:
    status_value = (
        _text(_first_present(raw, "status", "queue_status")) or QueueStatus.QUEUED.value
    )
    if status_value not in QueueStatus._value2member_map_:
        return QueueStatus.QUEUED.value
    return status_value


def _supabase_project_timestamps_from_queue_raw(
    raw: dict[str, Any],
) -> tuple[str, str]:
    created_at = _text(_first_present(raw, "createdAt", "created_at")) or utc_now()
    updated_at = (
        _text(_first_present(raw, "updatedAt", "updated_at", "last_execution_update"))
        or utc_now()
    )
    return created_at, updated_at


def _supabase_upsert_import_project_from_queue_raw(
    cur: Any,
    raw: dict[str, Any],
    *,
    project_id: str,
    created_at: str,
    updated_at: str,
) -> None:
    cur.execute(
        """
        insert into projects(project_id,project_name,project_dir,notion_page_url,notion_page_id,origin_idea_status,created_at,updated_at)
        values (%s,%s,%s,%s,%s,%s,%s,%s)
        on conflict (project_id) do update set
          project_name=excluded.project_name,
          project_dir=coalesce(nullif(projects.project_dir,''), excluded.project_dir),
          notion_page_url=coalesce(nullif(excluded.notion_page_url,''), projects.notion_page_url),
          notion_page_id=coalesce(nullif(excluded.notion_page_id,''), projects.notion_page_id),
          origin_idea_status=coalesce(nullif(excluded.origin_idea_status,''), projects.origin_idea_status),
          updated_at=excluded.updated_at
        where excluded.updated_at >= projects.updated_at
        """,
        (
            project_id,
            _text(_first_present(raw, "project_name", "name", "title")) or project_id,
            _text(_first_present(raw, "project_dir", "project_path")),
            _text(_first_present(raw, "notion_page_url", "url")),
            _text(_first_present(raw, "notion_page_id", "page_id", "id"))
            or _notion_page_id_from_url(
                _text(_first_present(raw, "notion_page_url", "url"))
            ),
            _text(_first_present(raw, "origin_idea_status", "idea_status"))
            or "unknown",
            created_at,
            updated_at,
        ),
    )


def _supabase_existing_queue_row_for_import(
    cur: Any, project_id: str
) -> dict[str, Any] | None:
    cur.execute(
        "select status,current_run_id,current_session_id,last_run_state,last_event_type,next_action_hint,manual_review_required,blocked_reason,last_error,last_result_summary,last_dispatch_at,last_callback_at,stale_after,updated_at from queue_items where project_id = %s",
        (project_id,),
    )
    existing_queue = cur.fetchone()
    return dict(existing_queue) if existing_queue else None


def _supabase_should_preserve_active_runtime_on_import(
    existing_queue: dict[str, Any],
    *,
    status_value: str,
    raw: dict[str, Any],
) -> bool:
    existing_run_id = _text(existing_queue.get("current_run_id"))
    incoming_run_id = _text(raw.get("current_run_id"))
    return bool(
        _text(existing_queue["status"]) in ACTIVE_STATUSES
        and (
            not existing_run_id
            or incoming_run_id != existing_run_id
            or status_value not in ACTIVE_STATUSES
        )
    )


def _supabase_queue_runtime_fields_for_import(
    existing_queue: dict[str, Any] | None,
    raw: dict[str, Any],
    status_value: str,
) -> dict[str, Any]:
    if existing_queue and _supabase_should_preserve_active_runtime_on_import(
        existing_queue, status_value=status_value, raw=raw
    ):
        return {
            "status_value": _text(existing_queue["status"]),
            "current_run_id": _text(existing_queue.get("current_run_id")),
            "current_session_id": _text(existing_queue["current_session_id"]),
            "last_run_state": _text(existing_queue["last_run_state"]),
            "last_event_type": _text(existing_queue["last_event_type"]),
            "next_action_hint": _text(existing_queue["next_action_hint"])
            or "await_callback",
            "manual_review_required": _bool(existing_queue["manual_review_required"]),
            "blocked_reason": _text(existing_queue["blocked_reason"]),
            "last_error": _text(existing_queue["last_error"]),
            "last_result_summary": _text(existing_queue["last_result_summary"]),
            "last_dispatch_at": existing_queue["last_dispatch_at"],
            "last_callback_at": existing_queue["last_callback_at"],
            "stale_after": existing_queue["stale_after"],
        }
    return {
        "status_value": status_value,
        "current_run_id": _text(raw.get("current_run_id")),
        "current_session_id": _text(raw.get("current_session_id")),
        "last_run_state": _text(raw.get("last_run_state")),
        "last_event_type": _text(raw.get("last_event_type")),
        "next_action_hint": _text(raw.get("next_action_hint")) or "controller_review",
        "manual_review_required": _bool(raw.get("manual_review_required")),
        "blocked_reason": _text(raw.get("blocked_reason")),
        "last_error": _text(raw.get("last_error")),
        "last_result_summary": _text(raw.get("last_result_summary")),
        "last_dispatch_at": _first_present(
            raw, "last_dispatch_at", "last_execution_update"
        ),
        "last_callback_at": raw.get("last_callback_at"),
        "stale_after": raw.get("stale_after"),
    }


def _supabase_upsert_import_queue_item(
    cur: Any,
    raw: dict[str, Any],
    *,
    project_id: str,
    updated_at: str,
    runtime: dict[str, Any],
) -> None:
    cur.execute(
        """
        insert into queue_items(project_id,status,selection_rank,dispatch_priority,auto_continue,continue_count,max_continues,retry_count,max_retries,current_run_id,current_session_id,last_run_state,last_event_type,next_action_hint,manual_review_required,blocked_reason,last_error,last_result_summary,machine_target,model,sandbox,last_dispatch_at,last_callback_at,stale_after,updated_at)
        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        on conflict (project_id) do update set
          status=excluded.status, selection_rank=excluded.selection_rank, dispatch_priority=excluded.dispatch_priority,
          auto_continue=excluded.auto_continue, continue_count=excluded.continue_count, max_continues=excluded.max_continues,
          retry_count=excluded.retry_count, max_retries=excluded.max_retries, current_run_id=excluded.current_run_id,
          current_session_id=excluded.current_session_id, last_run_state=excluded.last_run_state, last_event_type=excluded.last_event_type,
          next_action_hint=excluded.next_action_hint, manual_review_required=excluded.manual_review_required, blocked_reason=excluded.blocked_reason,
          last_error=excluded.last_error, last_result_summary=excluded.last_result_summary, machine_target=excluded.machine_target,
          model=excluded.model, sandbox=excluded.sandbox, last_dispatch_at=excluded.last_dispatch_at,
          last_callback_at=excluded.last_callback_at, stale_after=excluded.stale_after, updated_at=excluded.updated_at
        """,
        (
            project_id,
            runtime["status_value"],
            _int(_first_present(raw, "selection_rank", "rank"), 50),
            _int(_first_present(raw, "dispatch_priority", "priority"), 50),
            _bool(_first_present(raw, "auto_continue", "autoContinue")),
            _int(_first_present(raw, "continue_count", "continueCount"), 0),
            _int(_first_present(raw, "max_continues", "maxContinues"), 0),
            _int(_first_present(raw, "retry_count", "retryCount"), 0),
            _int(_first_present(raw, "max_retries", "maxRetries"), 2),
            runtime["current_run_id"],
            runtime["current_session_id"],
            runtime["last_run_state"],
            runtime["last_event_type"],
            runtime["next_action_hint"],
            runtime["manual_review_required"],
            runtime["blocked_reason"],
            runtime["last_error"],
            runtime["last_result_summary"],
            _text(raw.get("machine_target")) or "worker.example",
            _text(raw.get("model")) or "gpt-5.5",
            _text(raw.get("sandbox")) or "danger-full-access",
            runtime["last_dispatch_at"],
            runtime["last_callback_at"],
            runtime["stale_after"],
            updated_at,
        ),
    )


def _supabase_import_queue_row(cur: Any, raw: dict[str, Any]) -> tuple[int, int]:
    project_id = _text(raw.get("project_id"))
    if not project_id:
        return 0, 0
    status_value = _supabase_queue_status_value(raw)
    created_at, updated_at = _supabase_project_timestamps_from_queue_raw(raw)
    _supabase_upsert_import_project_from_queue_raw(
        cur,
        raw,
        project_id=project_id,
        created_at=created_at,
        updated_at=updated_at,
    )
    projects = 1
    existing_queue = _supabase_existing_queue_row_for_import(cur, project_id)
    if existing_queue and _is_older_timestamp(
        updated_at, existing_queue.get("updated_at")
    ):
        return projects, 0
    runtime = _supabase_queue_runtime_fields_for_import(
        existing_queue, raw, status_value
    )
    _supabase_upsert_import_queue_item(
        cur, raw, project_id=project_id, updated_at=updated_at, runtime=runtime
    )
    return projects, 1


def _supabase_ensure_import_project_for_paper(
    cur: Any, raw: dict[str, Any], project_id: str
) -> None:
    cur.execute(
        """
        insert into projects(project_id,project_name,project_dir,notion_page_url,notion_page_id,origin_idea_status,created_at,updated_at)
        values (%s,%s,%s,%s,%s,%s,%s,%s)
        on conflict (project_id) do nothing
        """,
        (
            project_id,
            _text(raw.get("project_name")) or project_id,
            _text(raw.get("project_dir")),
            _text(raw.get("notion_page_url")),
            _text(raw.get("notion_page_id"))
            or _notion_page_id_from_url(_text(raw.get("notion_page_url"))),
            "unknown",
            utc_now(),
            utc_now(),
        ),
    )


def _supabase_import_paper_row(cur: Any, raw: dict[str, Any]) -> int:
    paper_id = _text(raw.get("paper_id"))
    project_id = _text(raw.get("project_id"))
    if not paper_id or not project_id:
        return 0
    _supabase_ensure_import_project_for_paper(cur, raw, project_id)
    status = _paper_status_from_import_raw(raw)
    cur.execute(
        "select project_id, run_id, paper_type, updated_at from papers where paper_id=%s",
        (paper_id,),
    )
    existing_paper = cur.fetchone()
    if _paper_identity_conflicts(
        existing_paper,
        {
            "project_id": project_id,
            "run_id": _text(raw.get("run_id")),
            "paper_type": _text(raw.get("paper_type")) or "arxiv_draft",
        },
    ):
        raise IdempotencyConflict(
            f"paper id {paper_id!r} was reused with different paper identity"
        )
    if existing_paper and _is_older_timestamp(
        raw.get("updated_at"), existing_paper["updated_at"]
    ):
        return 0
    cur.execute(
        """
        insert into papers(paper_id,project_id,run_id,paper_type,paper_status,draft_markdown_path,draft_latex_path,evidence_bundle_path,claim_ledger_path,manifest_path,generated_at,updated_at)
        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        on conflict (paper_id) do update set
          project_id=excluded.project_id, run_id=excluded.run_id, paper_type=excluded.paper_type,
          paper_status=excluded.paper_status, draft_markdown_path=excluded.draft_markdown_path,
          draft_latex_path=excluded.draft_latex_path, evidence_bundle_path=excluded.evidence_bundle_path,
          claim_ledger_path=excluded.claim_ledger_path, manifest_path=excluded.manifest_path,
          generated_at=excluded.generated_at, updated_at=excluded.updated_at
        """,
        (
            paper_id,
            project_id,
            _text(raw.get("run_id")) or None,
            _text(raw.get("paper_type")) or "arxiv_draft",
            status,
            _text(raw.get("draft_markdown_path")),
            _text(raw.get("draft_latex_path")),
            _text(raw.get("evidence_bundle_path")),
            _text(raw.get("claim_ledger_path")),
            _text(raw.get("manifest_path")),
            _text(raw.get("generated_at")) or utc_now(),
            _text(raw.get("updated_at")) or utc_now(),
        ),
    )
    return 1


def resolve_supabase_database_url(configured_url: str) -> str:
    return (
        configured_url.strip()
        or os.environ.get("ENOCH_SUPABASE_DATABASE_URL", "").strip()
    )
