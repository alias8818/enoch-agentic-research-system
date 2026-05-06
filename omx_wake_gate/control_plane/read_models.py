from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omx_wake_gate.enoch_core.logic import draft_candidate_payload, eligible_paper_draft_candidates, paper_draft_decision_gate

from .models import PaperStatus, QueueStatus, ReviewStatus, RunState

WAKE_GATE_COMPLETION_STATES = {RunState.WAKE_READY.value, RunState.SESSION_FINISHED_READY.value}
PAPER_DRAFT_NEXT_ACTION = "draft_paper_or_select_next_project"
ACTIVE_QUEUE_STATUSES = {QueueStatus.DISPATCHING.value, QueueStatus.RUNNING.value, QueueStatus.AWAITING_WAKE.value, QueueStatus.WAKE_RECEIVED.value, QueueStatus.RECONCILING.value}
ATTENTION_QUEUE_STATUSES = {QueueStatus.BLOCKED.value, QueueStatus.NEEDS_REVIEW.value, QueueStatus.DISPATCH_ERROR.value}
DRAFT_PAPER_STATUSES = {PaperStatus.DRAFT_REVIEW.value, PaperStatus.DRAFT_GENERATING.value, PaperStatus.PUBLICATION_GENERATING.value, PaperStatus.HUMAN_REVIEW_REQUIRED.value}
READY_REVIEW_STATUSES = {ReviewStatus.FINALIZED.value}
# Paper review rows are an automation lane, not an operator-approval lane.
# Queue blockers/questions still require operator attention; publication drafts should
# flow through rewrite/finalization automatically unless explicitly rejected.
ATTENTION_REVIEW_STATUSES: set[str] = set()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _stage(label: str, *, tone: str, attention: bool, next_step: str, explanation: str, **extra: Any) -> dict[str, Any]:
    stage = {
        "operator_stage": label,
        "operator_stage_label": label.replace("_", " ").title(),
        "operator_tone": tone,
        "operator_attention": attention,
        "operator_next_step": next_step,
        "operator_explanation": explanation,
    }
    stage.update({key: value for key, value in extra.items() if value is not None})
    return stage


def _configured_project_root() -> str:
    config_path = os.environ.get("OMX_WAKE_GATE_CONFIG", "/etc/omx-wake-gate/config.json")
    try:
        with open(config_path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return ""
    return _text(payload.get("project_root"))


def _project_dir_candidates(project_dir: str) -> list[Path]:
    raw = Path(project_dir).expanduser()
    candidates = [raw]
    if not raw.is_absolute():
        configured_root = _configured_project_root()
        if configured_root:
            candidates.append(Path(configured_root).expanduser() / raw)
        candidates.append(Path("/var/lib/enoch-control-plane/projects") / raw)
    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            deduped.append(candidate)
    return deduped


def _paper_draft_gate_for_row(row: dict[str, Any]) -> dict[str, Any] | None:
    project_dir = _text(row.get("project_dir"))
    if not project_dir:
        project_dir = _text(row.get("project_id"))
    if not project_dir:
        return {"eligible": False, "reason": "missing project decision artifact", "values": [], "project_dir": ""}
    last_gate: dict[str, Any] | None = None
    for candidate in _project_dir_candidates(project_dir):
        try:
            gate = paper_draft_decision_gate(candidate)
        except (OSError, ValueError):
            last_gate = {"eligible": False, "reason": "project decision artifact could not be read", "values": [], "project_dir": str(candidate)}
            continue
        values = gate.get("values")
        if isinstance(values, list):
            gate = {**gate, "values": values[:8]}
        gate = {**gate, "project_dir": str(candidate)}
        if values or _text(gate.get("reason")) != "missing project decision artifact":
            return gate
        last_gate = gate
    return last_gate


def _decision_summary_from_gate(gate: dict[str, Any] | None) -> str:
    if not gate:
        return ""
    decision = _text(gate.get("decision"))
    reason = _text(gate.get("reason"))
    if decision and reason:
        return f"{decision} ({reason})"
    return decision or reason


def operator_stage_for_record(row: dict[str, Any]) -> dict[str, Any]:
    """Translate raw control-plane state into a deterministic operator stage.

    Raw queue/run/paper/review values remain available for detail/debugging, but
    the dashboard should lead with this normalized stage. `wake_ready` and
    `session_finished_ready` are worker-delivery callbacks, not publication
    polarity; paper polarity is decided by artifacts/review state.
    """

    queue_status = _text(row.get("status") or row.get("queue_status"))
    last_run_state = _text(row.get("last_run_state") or row.get("state") or row.get("gate_state"))
    next_action = _text(row.get("next_action_hint"))
    paper_status = _text(row.get("paper_status") or row.get("related_paper_status"))
    review_status = _text(row.get("review_status") or row.get("related_review_status"))
    has_paper = bool(_text(row.get("paper_id") or row.get("related_paper_id")) or paper_status)
    manual_review = bool(row.get("manual_review_required"))

    if queue_status in ATTENTION_QUEUE_STATUSES or manual_review:
        return _stage(
            "blocked_needs_operator",
            tone="bad",
            attention=True,
            next_step="Open the item and resolve the blocker or worker question.",
            explanation="Queue status or manual-action flag requires operator action.",
        )
    if queue_status == QueueStatus.PAUSED.value:
        return _stage(
            "paused_work",
            tone="muted",
            attention=False,
            next_step="Resume only when maintenance policy says this project should re-enter the queue.",
            explanation="Paused work is tracked separately from operator blockers.",
        )
    if review_status == "rejected" or paper_status == "archived":
        return _stage(
            "run_complete_no_paper",
            tone="muted",
            attention=False,
            next_step="No paper publication action is needed for this record.",
            explanation="The paper/review record is rejected or archived.",
        )
    if paper_status == PaperStatus.PUBLICATION_DRAFT.value and review_status in READY_REVIEW_STATUSES and _text(row.get("finalization_package_path") or row.get("related_finalization_package_path")):
        return _stage(
            "ready_to_publish",
            tone="good",
            attention=False,
            next_step="Import this finalized publication draft into the public corpus if it is not already present.",
            explanation="Publication draft artifacts are finalized and a finalization package exists; corpus publication is tracked outside this control-plane row.",
        )
    if paper_status == PaperStatus.PUBLICATION_DRAFT.value:
        return _stage(
            "finalization_needed",
            tone="warn",
            attention=False,
            next_step="Run automated rewrite/finalization; no human approval is required.",
            explanation="Publication draft exists and should move through the automated finalization lane without operator approval.",
        )
    if paper_status in DRAFT_PAPER_STATUSES or (has_paper and paper_status):
        return _stage(
            "draft_created",
            tone="info",
            attention=False,
            next_step="Continue automated rewrite/finalization or inspect artifacts if automation failed.",
            explanation="A paper record exists, but it is not yet a finalized publication draft.",
        )
    if queue_status in ACTIVE_QUEUE_STATUSES or last_run_state in ACTIVE_QUEUE_STATUSES:
        return _stage(
            "running",
            tone="info",
            attention=False,
            next_step="Wait for worker callback or gate completion.",
            explanation="The worker lane is active or awaiting wake callback.",
        )
    if queue_status == "queued":
        return _stage(
            "idea_queued",
            tone="info",
            attention=False,
            next_step="Dispatch when the lane is available.",
            explanation="The idea is queued and not currently running.",
        )
    if queue_status == "completed" and last_run_state in WAKE_GATE_COMPLETION_STATES and next_action == PAPER_DRAFT_NEXT_ACTION:
        gate = _paper_draft_gate_for_row(row)
        decision_summary = _decision_summary_from_gate(gate)
        if gate is None or not bool(gate.get("eligible")):
            return _stage(
                "run_complete_no_paper",
                tone="muted",
                attention=False,
                next_step="No paper draft is needed; select the next project.",
                explanation=f"Worker delivery is complete, but the project decision is not a positive paper signal: {decision_summary or 'not eligible'}.",
                paper_draft_eligible=False if gate is not None else None,
                project_decision_summary=decision_summary,
                project_decision_gate=gate,
            )
        return _stage(
            "run_complete_draft_needed",
            tone="warn",
            attention=False,
            next_step="Run draft-next because the decision artifacts are positive.",
            explanation="Worker delivery is complete and the project decision artifacts indicate a positive paper signal.",
            paper_draft_eligible=True if gate is not None else None,
            project_decision_summary=decision_summary,
            project_decision_gate=gate,
        )
    if queue_status == "completed" or last_run_state in WAKE_GATE_COMPLETION_STATES:
        return _stage(
            "run_complete_no_paper",
            tone="muted",
            attention=False,
            next_step="Select the next project unless separate paper evidence appears.",
            explanation="The worker run is complete; no current draft-needed signal is visible in this row.",
        )
    return _stage(
        "blocked_needs_operator",
        tone="warn",
        attention=True,
        next_step="Inspect raw state because this row does not match a known operator lifecycle stage.",
        explanation="Unknown or inconsistent raw state.",
    )


def with_operator_stage(row: dict[str, Any]) -> dict[str, Any]:
    stage = operator_stage_for_record(row)
    return {**stage, **row}

from .store import ControlPlaneStore


def page_size(value: int, *, default: int = 50, cap: int = 200) -> int:
    try:
        requested = int(value)
    except (TypeError, ValueError):
        requested = default
    return max(1, min(requested, cap))


def row_age_seconds(row: dict[str, Any]) -> int | None:
    raw = str(row.get("updated_at") or row.get("created_at") or "")
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, int((datetime.now(timezone.utc) - ts).total_seconds()))


def queue_links(row: dict[str, Any]) -> dict[str, str]:
    project_id = str(row.get("project_id") or "")
    run_id = str(row.get("current_run_id") or "")
    return {
        "project": f"/control/api/v1/projects/{project_id}" if project_id else "",
        "run": f"/control/api/v1/runs/{run_id}" if run_id else "",
        "legacy_project": f"/control/api/projects/{project_id}" if project_id else "",
        "legacy_run": f"/control/api/runs/{run_id}" if run_id else "",
    }


def paper_links(row: dict[str, Any]) -> dict[str, str]:
    paper_id = str(row.get("paper_id") or "")
    project_id = str(row.get("project_id") or "")
    run_id = str(row.get("run_id") or "")
    return {
        "paper": f"/control/api/v1/papers/{paper_id}" if paper_id else "",
        "project": f"/control/api/v1/projects/{project_id}" if project_id else "",
        "run": f"/control/api/v1/runs/{run_id}" if run_id else "",
        "legacy_paper": f"/control/api/papers/{paper_id}" if paper_id else "",
    }


def summarize_queue_row(row: dict[str, Any]) -> dict[str, Any]:
    return with_operator_stage({
        "project_id": row.get("project_id", ""),
        "project_name": row.get("project_name", ""),
        "status": row.get("status", ""),
        "dispatch_priority": row.get("dispatch_priority", 0),
        "selection_rank": row.get("selection_rank", 0),
        "current_run_id": row.get("current_run_id", ""),
        "current_session_id": row.get("current_session_id", ""),
        "last_run_state": row.get("last_run_state", ""),
        "next_action_hint": row.get("next_action_hint", ""),
        "manual_review_required": bool(row.get("manual_review_required")),
        "blocked_reason": row.get("blocked_reason", ""),
        "project_dir": row.get("project_dir", ""),
        "related_paper_id": row.get("related_paper_id", ""),
        "related_paper_status": row.get("related_paper_status", ""),
        "related_review_status": row.get("related_review_status", ""),
        "related_finalization_package_path": row.get("related_finalization_package_path", ""),
        "updated_at": row.get("updated_at", ""),
        "age_seconds": row_age_seconds(row),
        "links": queue_links(row),
    })


def summarize_paper_row(row: dict[str, Any]) -> dict[str, Any]:
    return with_operator_stage({
        "paper_id": row.get("paper_id", ""),
        "project_id": row.get("project_id", ""),
        "project_name": row.get("project_name", ""),
        "run_id": row.get("run_id", ""),
        "paper_type": row.get("paper_type", ""),
        "paper_status": row.get("paper_status", ""),
        "review_status": row.get("review_status", ""),
        "finalization_package_path": row.get("finalization_package_path", ""),
        "generated_at": row.get("generated_at", ""),
        "updated_at": row.get("updated_at", ""),
        "age_seconds": row_age_seconds(row),
        "artifact_paths_present": {
            name: bool(row.get(name))
            for name in ("draft_markdown_path", "draft_latex_path", "evidence_bundle_path", "claim_ledger_path", "manifest_path")
        },
        "links": paper_links(row),
    })


def summarize_run_row(row: dict[str, Any]) -> dict[str, Any]:
    run_id = str(row.get("run_id") or "")
    project_id = str(row.get("project_id") or "")
    return with_operator_stage({
        "run_id": run_id,
        "project_id": project_id,
        "project_name": row.get("project_name", ""),
        "session_id": row.get("session_id", ""),
        "related_paper_id": row.get("related_paper_id", ""),
        "related_paper_status": row.get("related_paper_status", ""),
        "related_review_status": row.get("related_review_status", ""),
        "related_finalization_package_path": row.get("related_finalization_package_path", ""),
        "state": row.get("state", ""),
        "gate_state": row.get("gate_state", ""),
        "dispatch_mode": row.get("dispatch_mode", ""),
        "started_at": row.get("started_at", ""),
        "ended_at": row.get("ended_at", ""),
        "last_callback_at": row.get("last_callback_at", ""),
        "current_activity": row.get("current_activity", ""),
        "updated_at": row.get("updated_at", ""),
        "age_seconds": row_age_seconds(row),
        "links": {
            "run": f"/control/api/v1/runs/{run_id}" if run_id else "",
            "project": f"/control/api/v1/projects/{project_id}" if project_id else "",
            "legacy_run": f"/control/api/runs/{run_id}" if run_id else "",
        },
    })


OPERATOR_STAGE_PRECEDENCE = {
    "blocked_needs_operator": 100,
    "needs_review": 90,
    "ready_to_publish": 80,
    "finalization_needed": 75,
    "draft_created": 70,
    "run_complete_draft_needed": 60,
    "running": 50,
    "idea_queued": 40,
    "run_complete_no_paper": 30,
    "paused_work": 20,
}


def _typed_lifecycle_key(row: dict[str, Any]) -> str:
    paper_id = _text(row.get("paper_id"))
    if paper_id:
        return f"paper:{paper_id}"
    project_id = _text(row.get("project_id"))
    if project_id:
        return f"queue:{project_id}"
    run_id = _text(row.get("run_id") or row.get("current_run_id"))
    if run_id:
        return f"run:{run_id}"
    return ""


def _queue_is_superseded_by_paper(
    row: dict[str, Any],
    paper_projects: set[str],
    paper_runs: set[str],
) -> bool:
    if _text(row.get("operator_stage")) != "run_complete_draft_needed":
        return False
    run_id = _text(row.get("run_id") or row.get("current_run_id"))
    if run_id:
        return run_id in paper_runs
    project_id = _text(row.get("project_id"))
    return bool(project_id and project_id in paper_projects)


def operator_counts_from_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    staged_rows = [row if row.get("operator_stage") else with_operator_stage(row) for row in rows]
    paper_projects = {
        _text(row.get("project_id"))
        for row in staged_rows
        if _text(row.get("paper_id")) and _text(row.get("project_id"))
    }
    paper_runs = {_text(row.get("run_id")) for row in staged_rows if _text(row.get("paper_id")) and _text(row.get("run_id"))}
    by_key: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    for staged in staged_rows:
        if not _text(staged.get("paper_id")) and _text(staged.get("related_paper_id")):
            continue
        if _queue_is_superseded_by_paper(staged, paper_projects, paper_runs):
            continue
        key = _typed_lifecycle_key(staged)
        if not key:
            anonymous.append(staged)
            continue
        current = by_key.get(key)
        stage = _text(staged.get("operator_stage"))
        current_stage = _text((current or {}).get("operator_stage"))
        if current is None or OPERATOR_STAGE_PRECEDENCE.get(stage, 0) > OPERATOR_STAGE_PRECEDENCE.get(current_stage, 0):
            by_key[key] = staged
    reconciled = [*by_key.values(), *anonymous]
    for row in reconciled:
        stage = _text(row.get("operator_stage")) or operator_stage_for_record(row)["operator_stage"]
        counts[stage] = counts.get(stage, 0) + 1
    counts["needs_attention"] = sum(1 for row in reconciled if bool(row.get("operator_attention") or operator_stage_for_record(row)["operator_attention"]))
    counts["ready_to_publish"] = counts.get("ready_to_publish", 0)
    counts["total_operator_items"] = len(reconciled)
    return counts


def page_response(*, rows: list[dict[str, Any]], next_cursor: str | None, has_more: bool, page_size_value: int, cursor: str, filters: dict[str, Any]) -> dict[str, Any]:
    return {
        "page_size": page_size_value,
        "returned": len(rows),
        "cursor": cursor or "",
        "next_cursor": next_cursor or "",
        "has_more": has_more,
        "filters": filters,
    }


def overview(store: ControlPlaneStore, *, active_limit: int = 5, event_limit: int = 10) -> dict[str, Any]:
    counts = store.queue_counts_sql()
    paper_counts = store.paper_counts_sql()
    active = [summarize_queue_row(row) for row in store.active_items_sql(limit=active_limit)]
    next_candidate = store.next_candidate_sql()
    raw_queue_rows = store.operator_queue_rows_sql()
    raw_paper_rows = store.operator_paper_rows_sql()
    queue_rows = [summarize_queue_row(row) for row in raw_queue_rows]
    paper_rows = [summarize_paper_row(row) for row in raw_paper_rows]
    operator_counts = operator_counts_from_rows([*queue_rows, *paper_rows])
    raw_write_candidates = eligible_paper_draft_candidates(raw_queue_rows, raw_paper_rows)
    write_candidates: list[dict[str, Any]] = []
    gate_rejected: list[dict[str, Any]] = []
    for candidate in raw_write_candidates:
        gate = _paper_draft_gate_for_row(candidate)
        if gate is None or not bool(gate.get("eligible")):
            gate_rejected.append({
                "project_id": candidate.get("project_id", ""),
                "project_name": candidate.get("project_name", ""),
                "run_id": candidate.get("current_run_id") or candidate.get("run_id") or "",
                "decision_summary": _decision_summary_from_gate(gate),
                "gate_reason": (gate or {}).get("reason", "missing project decision artifact"),
            })
            continue
        write_candidates.append(candidate)
    paper_pipeline = {
        "write_needed": len(write_candidates),
        "raw_completed_no_paper_candidates": len(raw_write_candidates),
        "not_writable_by_decision_gate": len(gate_rejected),
        "gate_rejected_sample": gate_rejected[:10],
        "next_write_candidate": draft_candidate_payload(write_candidates[0]) if write_candidates else None,
        "finalize_needed": operator_counts.get("finalization_needed", 0),
        "publish_ready": operator_counts.get("ready_to_publish", 0),
        "definitions": {
            "write_needed": "completed runs with no live paper row that currently pass the paper-positive decision gate",
            "raw_completed_no_paper_candidates": "completed no-paper rows before checking local project decision artifacts",
            "not_writable_by_decision_gate": "completed no-paper rows rejected by local project decision artifacts as negative, needs-review, or otherwise non-positive",
            "finalize_needed": "publication drafts missing automated finalization package",
            "publish_ready": "finalized publication drafts ready for corpus import",
        },
    }
    events, next_cursor, has_more = store.event_page(page_size=event_limit, include_payload=False)
    return {
        "counts": {
            **counts,
            "papers": paper_counts.get("all", 0),
        },
        "paper_counts": paper_counts,
        "operator_counts": operator_counts,
        "paper_pipeline": paper_pipeline,
        "operator_model": {
            "source": "control_plane.read_models.operator_stage_for_record",
            "raw_state_note": "wake_ready/session_finished_ready are worker-delivery callbacks; paper polarity comes from decision artifacts and paper review/finalization state.",
        },
        "active_items": active,
        "next_candidate": summarize_queue_row(next_candidate) if next_candidate else None,
        "recent_events": events,
        "recent_events_page": page_response(rows=events, next_cursor=next_cursor, has_more=has_more, page_size_value=page_size(event_limit), cursor="", filters={}),
    }
