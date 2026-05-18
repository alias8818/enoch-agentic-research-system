from __future__ import annotations

import json
import os
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

from enoch_control_plane.enoch_core.logic import draft_candidate_payload, eligible_paper_draft_candidates, paper_draft_decision_gate
from enoch_control_plane.timeutils import parse_utc_datetime

from .models import PaperStatus, QueueStatus
from .state_contract import (
    ACTIVE_QUEUE_STATUSES,
    ATTENTION_QUEUE_STATUSES,
    DRAFT_PAPER_STATUSES,
    PAPER_DRAFT_NEXT_ACTION,
    PUBLICATION_READY_AUTOMATION_STATUSES,
    OperatorLane,
    WAKE_GATE_COMPLETION_STATES,
)

READY_REVIEW_STATUSES = PUBLICATION_READY_AUTOMATION_STATUSES
# Paper review rows are an automation lane, not an operator-approval lane.
# Queue blockers/questions still require operator attention; publication drafts should
# flow through rewrite/finalization automatically unless explicitly rejected.
ATTENTION_REVIEW_STATUSES: set[str] = set()
MAX_FOLLOWUP_DEPTH = 4
MIN_FOLLOWUP_REQUIRED_EVIDENCE = 2

OPERATOR_LANE_LABELS: dict[str, str] = {
    OperatorLane.RUNNING.value: "Running",
    OperatorLane.READY_QUEUE.value: "Ready",
    OperatorLane.NEEDS_OPERATOR.value: "Needs Attention",
    OperatorLane.COMPLETE_NO_PAPER.value: "Done / No Paper",
    OperatorLane.USEFUL_SIGNAL.value: "Useful Signal",
    OperatorLane.COMPUTE_SCALE_BLOCKED.value: "Scale Blocked",
    OperatorLane.FOLLOWUP_INVESTIGATION.value: "Investigate Next",
    OperatorLane.WRITE_PAPER.value: "Write Paper",
    OperatorLane.AUTOMATE_PUBLICATION.value: "Finalize Draft",
    OperatorLane.READY_TO_PUBLISH.value: "Publish / Import",
    OperatorLane.PUBLISHED.value: "Published",
    OperatorLane.PAUSED.value: "Paused",
    OperatorLane.HISTORICAL.value: "Historical",
}

OPERATOR_DETAIL_LABELS: dict[str, str] = {
    "blocked_needs_operator": "Needs Attention",
    "paused_work": "Paused",
    "run_complete_no_paper": "Done / No Paper",
    "useful_signal": "Useful Local Signal",
    "compute_scale_blocked": "Scale-Limited Signal",
    "published": "Published",
    "ready_to_publish": "Publish / Import",
    "finalization_needed": "Finalize Draft",
    "draft_created": "Draft Exists",
    "followup_candidate": "Investigate Next",
    "running": "Running",
    "idea_queued": "Ready",
    "run_complete_draft_needed": "Write Paper",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def paper_source_fingerprint(paper_id: str) -> str:
    """Stable public-corpus fingerprint for a control-plane paper row."""

    return hashlib.sha256(_text(paper_id).encode("utf-8")).hexdigest()[:16]


def _paper_imported(row: dict[str, Any]) -> bool:
    return bool(
        row.get("corpus_imported")
        or row.get("related_corpus_imported")
        or _text(row.get("corpus_import_id"))
        or _text(row.get("related_corpus_import_id"))
        or _text(row.get("artifact_slug"))
        or _text(row.get("related_artifact_slug"))
        or _text(row.get("source_record_fingerprint"))
        or _text(row.get("related_source_record_fingerprint"))
    )


RELATED_PAPER_ARTIFACT_FIELDS = {
    "finalization_package_path": "related_finalization_package_path",
    "draft_markdown_path": "related_draft_markdown_path",
    "evidence_bundle_path": "related_evidence_bundle_path",
    "claim_ledger_path": "related_claim_ledger_path",
    "manifest_path": "related_manifest_path",
}


def _related_artifact_paths_present(row: dict[str, Any]) -> dict[str, bool]:
    return {name: bool(_text(row.get(field))) for name, field in RELATED_PAPER_ARTIFACT_FIELDS.items()}


def _drop_related_artifact_paths(summary: dict[str, Any]) -> dict[str, Any]:
    summary["related_artifact_paths_present"] = _related_artifact_paths_present(summary)
    for field in RELATED_PAPER_ARTIFACT_FIELDS.values():
        summary.pop(field, None)
    return summary


def _paper_publication_artifacts_present(row: dict[str, Any]) -> bool:
    artifact_flags = row.get("artifact_paths_present")
    required = ("draft_markdown_path", "evidence_bundle_path", "claim_ledger_path", "manifest_path")
    if isinstance(artifact_flags, dict):
        return all(bool(artifact_flags.get(name)) for name in required)
    related_artifact_flags = row.get("related_artifact_paths_present")
    if isinstance(related_artifact_flags, dict):
        related_required = (
            "finalization_package_path",
            "draft_markdown_path",
            "evidence_bundle_path",
            "claim_ledger_path",
            "manifest_path",
        )
        return all(bool(related_artifact_flags.get(name)) for name in related_required)
    if _text(row.get("related_paper_id")):
        return all(_related_artifact_paths_present(row).values())
    return all(bool(_text(row.get(name))) for name in required)


def _paper_finalization_package_present(row: dict[str, Any]) -> bool:
    if _text(row.get("finalization_package_path") or row.get("related_finalization_package_path")):
        return True
    artifact_flags = row.get("related_artifact_paths_present")
    return isinstance(artifact_flags, dict) and bool(artifact_flags.get("finalization_package_path"))


def _stage(
    detail_label: str,
    *,
    lane: OperatorLane,
    tone: str,
    attention: bool,
    next_step: str,
    explanation: str,
    **extra: Any,
) -> dict[str, Any]:
    stage = {
        "operator_stage": lane.value,
        "operator_stage_label": OPERATOR_LANE_LABELS.get(lane.value, lane.value.replace("_", " ").title()),
        "operator_lane": lane.value,
        "operator_detail_stage": detail_label,
        "operator_detail_stage_label": OPERATOR_DETAIL_LABELS.get(detail_label, detail_label.replace("_", " ").title()),
        "operator_tone": tone,
        "operator_attention": attention,
        "operator_next_step": next_step,
        "operator_explanation": explanation,
    }
    stage.update({key: value for key, value in extra.items() if value is not None})
    return stage


def _configured_project_root() -> str:
    config_path = os.environ.get("ENOCH_CONFIG") or os.environ.get("ENOCH_CONTROL_PLANE_CONFIG", "/etc/enoch/config.json")
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
    if gate.get("source") == "supabase_project_decisions" and decision:
        return decision
    if decision and reason:
        return f"{decision} ({reason})"
    return decision or reason


def _truthy(value: Any) -> bool:
    if value is True or value == 1:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _normal(value: Any) -> str:
    return _text(value).lower().replace("-", "_").replace(" ", "_")


def _listish(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_text(item) for item in value if _text(item)]
    if isinstance(value, str):
        return [item.strip() for item in value.replace(";", "\n").splitlines() if item.strip()]
    return []


def _decision_payload_fields(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("decision_payload_json")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    decision = payload.get("project_decision")
    if not isinstance(decision, dict):
        decision = payload
    if not isinstance(decision, dict):
        decision = {}
    return {
        "research_outcome": row.get("research_outcome", decision.get("research_outcome", "")),
        "hypothesis_status": row.get("hypothesis_status", decision.get("hypothesis_status", "")),
        "evidence_strength": row.get("evidence_strength", decision.get("evidence_strength", "")),
        "claim_scope": row.get("claim_scope", decision.get("claim_scope", "")),
        "scale_limits": row.get("scale_limits", decision.get("scale_limits", "")),
        "useful_signal_summary": row.get("useful_signal_summary", decision.get("useful_signal_summary", "")),
        "bounded_paper_ready": row.get("bounded_paper_ready", decision.get("bounded_paper_ready", False)),
        "compute_scale_blocked": row.get("compute_scale_blocked", decision.get("compute_scale_blocked", False)),
        "recommended_next_action": row.get("recommended_next_action", decision.get("recommended_next_action", "")),
        "stop_reason": row.get("stop_reason", decision.get("stop_reason", "")),
    }


def _research_outcome(row: dict[str, Any]) -> str:
    if "decision_payload_json" in row and not _text(row.get("research_outcome")):
        row = {**row, **_decision_payload_fields(row)}
    outcome = _text(row.get("research_outcome")).lower().replace("-", "_").replace(" ", "_")
    if outcome:
        return outcome
    return ""


def _compute_scale_blocked(row: dict[str, Any]) -> bool:
    if "decision_payload_json" in row and not _text(row.get("scale_limits")):
        row = {**row, **_decision_payload_fields(row)}
    if _truthy(row.get("compute_scale_blocked")):
        return True
    outcome = _research_outcome(row)
    haystack = " ".join(
        _text(row.get(key)).lower()
        for key in (
            "scale_limits",
            "stop_reason",
            "recommended_next_action",
            "last_result_summary",
            "decision_summary",
        )
    )
    scale_markers = (
        "hyperscaler",
        "datacenter",
        "large model",
        "large-model",
        "larger model",
        "larger-scale",
        "large-scale",
        "distributed",
        "multi-gpu",
        "full scale",
        "full-scale",
    )
    return outcome in {"useful_signal", "promising_if_scaled"} and any(marker in haystack for marker in scale_markers)


def _is_useful_signal(row: dict[str, Any]) -> bool:
    outcome = _research_outcome(row)
    return outcome in {"useful_signal", "paper_positive", "promising_if_scaled"}


def _useful_signal_from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "research_outcome": _research_outcome(row),
        "hypothesis_status": _text(row.get("hypothesis_status")),
        "evidence_strength": _text(row.get("evidence_strength")),
        "claim_scope": _text(row.get("claim_scope")),
        "scale_limits": _text(row.get("scale_limits")),
        "useful_signal_summary": _text(row.get("useful_signal_summary")),
        "bounded_paper_ready": _truthy(row.get("bounded_paper_ready")),
        "compute_scale_blocked": _compute_scale_blocked(row),
    }


def _followup_from_row(row: dict[str, Any]) -> dict[str, Any]:
    try:
        depth = max(int(row.get("followup_depth") or 0), int(row.get("source_followup_depth") or 0))
    except (TypeError, ValueError):
        depth = 0
    return {
        "followup_recommended": _truthy(row.get("followup_recommended")),
        "followup_type": _normal(row.get("followup_type")),
        "followup_title": _text(row.get("followup_title")),
        "followup_hypothesis": _text(row.get("followup_hypothesis")),
        "followup_required_evidence": _listish(row.get("followup_required_evidence")),
        "followup_success_threshold": _text(row.get("followup_success_threshold")),
        "followup_stop_condition": _text(row.get("followup_stop_condition")),
        "followup_depth": depth,
    }


def _is_followup_candidate(row: dict[str, Any]) -> bool:
    try:
        depth = max(int(row.get("followup_depth") or 0), int(row.get("source_followup_depth") or 0))
    except (TypeError, ValueError):
        depth = 0
    required_evidence = _listish(row.get("followup_required_evidence"))
    return bool(
        _truthy(row.get("followup_recommended"))
        and _text(row.get("status") or row.get("queue_status")) == "completed"
        and not _truthy(row.get("manual_review_required"))
        and not _truthy(row.get("followup_launched"))
        and depth < MAX_FOLLOWUP_DEPTH
        and _normal(row.get("followup_type")) in {"deepen", "branch", "retry"}
        and _text(row.get("followup_title"))
        and _text(row.get("followup_hypothesis"))
        and len(required_evidence) >= MIN_FOLLOWUP_REQUIRED_EVIDENCE
        and _text(row.get("followup_success_threshold"))
        and _text(row.get("followup_stop_condition"))
    )


def _paper_draft_gate_from_row_decision(row: dict[str, Any]) -> dict[str, Any] | None:
    state = _text(row.get("decision_gate_state"))
    if not state:
        return None
    summary = _text(row.get("decision_summary"))
    if state == "positive":
        reason = "bounded useful signal is paper-scoped" if _research_outcome(row) == "useful_signal" and _truthy(row.get("bounded_paper_ready")) else "project decision is positive"
        return {"eligible": True, "reason": reason, "decision": summary or state, "values": [], "source": "supabase_project_decisions"}
    if (
        state == "negative"
        and _research_outcome(row) == "useful_signal"
        and _truthy(row.get("bounded_paper_ready"))
        and _normal(row.get("hypothesis_status")) in {"supported", "mixed"}
        and _normal(row.get("evidence_strength")) in {"moderate", "strong"}
        and _text(row.get("claim_scope"))
        and _text(row.get("scale_limits"))
    ):
        return {
            "eligible": True,
            "reason": "bounded useful signal is paper-scoped",
            "decision": summary or state,
            "values": [],
            "source": "supabase_project_decisions",
        }
    reason_by_state = {
        "negative": "project decision is not positive",
        "needs_review": "project decision is not positive",
        "missing": "missing project decision artifact",
        "malformed": "project decision artifact could not be read",
        "unknown": "project decision lacks positive draft signal",
    }
    return {
        "eligible": False,
        "reason": reason_by_state.get(state, "project decision lacks positive draft signal"),
        "decision": summary,
        "values": [],
        "source": "supabase_project_decisions",
    }


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

    if queue_status == QueueStatus.CANCELED.value and not manual_review:
        return _stage(
            "historical",
            lane=OperatorLane.HISTORICAL,
            tone="muted",
            attention=False,
            next_step="No action is needed for this terminal queue record.",
            explanation="Canceled queue work is terminal historical evidence, not current operator work.",
        )
    if queue_status in ATTENTION_QUEUE_STATUSES or manual_review:
        return _stage(
            "blocked_needs_operator",
            lane=OperatorLane.NEEDS_OPERATOR,
            tone="bad",
            attention=True,
            next_step="Open the item and resolve the blocker or worker question.",
            explanation="Queue status or manual-action flag requires operator action.",
        )
    if queue_status == QueueStatus.PAUSED.value:
        return _stage(
            "paused_work",
            lane=OperatorLane.PAUSED,
            tone="muted",
            attention=False,
            next_step="Resume only when maintenance policy says this project should re-enter the queue.",
            explanation="Paused work is tracked separately from operator blockers.",
        )
    if review_status == "rejected" or paper_status == "archived":
        return _stage(
            "run_complete_no_paper",
            lane=OperatorLane.COMPLETE_NO_PAPER,
            tone="muted",
            attention=False,
            next_step="No paper publication action is needed for this record.",
            explanation="The paper/review record is rejected or archived.",
        )
    if queue_status in ACTIVE_QUEUE_STATUSES or last_run_state in ACTIVE_QUEUE_STATUSES:
        return _stage(
            "running",
            lane=OperatorLane.RUNNING,
            tone="info",
            attention=False,
            next_step="Wait for worker callback or gate completion.",
            explanation="The worker lane is active or awaiting wake callback.",
        )
    if has_paper and _paper_imported(row):
        return _stage(
            "published",
            lane=OperatorLane.PUBLISHED,
            tone="good",
            attention=False,
            next_step="No corpus-import action is needed; this paper is already represented by the import ledger.",
            explanation="The corpus import ledger contains this paper, so it is public/imported rather than publish work.",
        )
    if (
        paper_status in {PaperStatus.PUBLICATION_DRAFT.value, PaperStatus.DRAFT_REVIEW.value}
        and review_status in READY_REVIEW_STATUSES
        and _paper_finalization_package_present(row)
        and _paper_publication_artifacts_present(row)
    ):
        return _stage(
            "ready_to_publish",
            lane=OperatorLane.READY_TO_PUBLISH,
            tone="good",
            attention=False,
            next_step="Import this finalized publication draft into the public corpus.",
            explanation="Publication artifacts have required evidence paths, a finalized automation package, and no corpus-import ledger row is visible.",
        )
    if paper_status == PaperStatus.PUBLICATION_DRAFT.value:
        return _stage(
            "finalization_needed",
            lane=OperatorLane.AUTOMATE_PUBLICATION,
            tone="warn",
            attention=False,
            next_step="Run automated rewrite/finalization; no human approval is required.",
            explanation="Publication draft exists and should move through the automated finalization lane without operator approval.",
        )
    if paper_status in DRAFT_PAPER_STATUSES or (has_paper and paper_status):
        return _stage(
            "draft_created",
            lane=OperatorLane.AUTOMATE_PUBLICATION,
            tone="info",
            attention=False,
            next_step="Continue automated rewrite/finalization or inspect artifacts if automation failed.",
            explanation="A paper record exists, but it is not yet a finalized publication draft.",
        )
    if queue_status == "queued":
        return _stage(
            "idea_queued",
            lane=OperatorLane.READY_QUEUE,
            tone="info",
            attention=False,
            next_step="Dispatch when the lane is available.",
            explanation="The idea is queued and not currently running.",
        )
    if queue_status == "completed" and last_run_state in WAKE_GATE_COMPLETION_STATES and next_action == PAPER_DRAFT_NEXT_ACTION:
        gate = _paper_draft_gate_from_row_decision(row) or _paper_draft_gate_for_row(row)
        decision_summary = _decision_summary_from_gate(gate)
        if gate is None or not bool(gate.get("eligible")):
            if _is_useful_signal(row):
                signal = _useful_signal_from_row(row)
                if signal["compute_scale_blocked"]:
                    return _stage(
                        "compute_scale_blocked",
                        lane=OperatorLane.COMPUTE_SCALE_BLOCKED,
                        tone="info",
                        attention=False,
                        next_step="Park as promising-if-scaled unless a cheaper bounded test is defined.",
                        explanation=f"Worker delivery found a useful signal, but the remaining validation appears to exceed local compute/time limits: {decision_summary or 'not paper-ready'}.",
                        paper_draft_eligible=False if gate is not None else None,
                        project_decision_summary=decision_summary,
                        project_decision_gate=gate,
                        **signal,
                    )
                return _stage(
                    "useful_signal",
                    lane=OperatorLane.USEFUL_SIGNAL,
                    tone="info",
                    attention=False,
                    next_step="Prefer one bounded deepen run if it is cheap; otherwise keep the scoped useful signal as no-paper evidence.",
                    explanation=f"Worker delivery found a useful local signal, but it is not yet paper-positive: {decision_summary or 'not paper-ready'}.",
                    paper_draft_eligible=False if gate is not None else None,
                    project_decision_summary=decision_summary,
                    project_decision_gate=gate,
                    **signal,
                )
            if _is_followup_candidate(row):
                followup = _followup_from_row(row)
                return _stage(
                    "followup_candidate",
                    lane=OperatorLane.FOLLOWUP_INVESTIGATION,
                    tone="info",
                    attention=False,
                    next_step="Launch a bounded follow-up investigation if this adjacent test is still worth spending worker time on.",
                    explanation=f"Worker delivery is complete and not paper-positive ({decision_summary or 'not eligible'}), but the decision artifact recommends a specific next investigation.",
                    paper_draft_eligible=False if gate is not None else None,
                    project_decision_summary=decision_summary,
                    project_decision_gate=gate,
                    **followup,
                )
            return _stage(
                "run_complete_no_paper",
                lane=OperatorLane.COMPLETE_NO_PAPER,
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
            lane=OperatorLane.WRITE_PAPER,
            tone="warn",
            attention=False,
            next_step="Run draft-next because the decision artifacts are positive.",
            explanation="Worker delivery is complete and the project decision artifacts indicate a positive paper signal.",
            paper_draft_eligible=True if gate is not None else None,
            project_decision_summary=decision_summary,
            project_decision_gate=gate,
        )
    if queue_status == "completed" or last_run_state in WAKE_GATE_COMPLETION_STATES:
        if not has_paper and _is_useful_signal(row):
            signal = _useful_signal_from_row(row)
            if signal["compute_scale_blocked"]:
                return _stage(
                    "compute_scale_blocked",
                    lane=OperatorLane.COMPUTE_SCALE_BLOCKED,
                    tone="info",
                    attention=False,
                    next_step="Park as promising-if-scaled unless a cheaper bounded test is defined.",
                    explanation="The prior run found a useful signal, but remaining validation exceeds local compute/time limits.",
                    **signal,
                )
            return _stage(
                "useful_signal",
                lane=OperatorLane.USEFUL_SIGNAL,
                tone="info",
                attention=False,
                next_step="Prefer one bounded deepen run if it is cheap; otherwise keep the scoped useful signal as no-paper evidence.",
                explanation="The prior run found a bounded useful signal but no current paper-draft signal is visible.",
                **signal,
            )
        if not has_paper and _is_followup_candidate(row):
            followup = _followup_from_row(row)
            return _stage(
                "followup_candidate",
                lane=OperatorLane.FOLLOWUP_INVESTIGATION,
                tone="info",
                attention=False,
                next_step="Launch a bounded follow-up investigation if this adjacent test is still worth spending worker time on.",
                explanation="The prior run is complete and no-paper, but its decision artifact recommends a specific next investigation.",
                **followup,
            )
        return _stage(
            "run_complete_no_paper",
            lane=OperatorLane.COMPLETE_NO_PAPER,
            tone="muted",
            attention=False,
            next_step="Select the next project unless separate paper evidence appears.",
            explanation="The worker run is complete; no current draft-needed signal is visible in this row.",
        )
    return _stage(
        "blocked_needs_operator",
        lane=OperatorLane.NEEDS_OPERATOR,
        tone="warn",
        attention=True,
        next_step="Inspect raw state because this row does not match a known operator lifecycle stage.",
        explanation="Unknown or inconsistent raw state.",
    )


def with_operator_stage(row: dict[str, Any]) -> dict[str, Any]:
    stage = operator_stage_for_record(row)
    return {**row, **stage}

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
    ts = parse_utc_datetime(raw)
    if ts is None:
        return None
    return max(0, int((datetime.now(timezone.utc) - ts).total_seconds()))


def _url_path_segment(value: Any) -> str:
    text = str(value or "")
    return quote(text, safe="") if text else ""


def queue_links(row: dict[str, Any]) -> dict[str, str]:
    project_id = _url_path_segment(row.get("project_id"))
    run_id = _url_path_segment(row.get("current_run_id"))
    return {
        "project": f"/control/api/v1/projects/{project_id}" if project_id else "",
        "run": f"/control/api/v1/runs/{run_id}" if run_id else "",
        "legacy_project": f"/control/api/projects/{project_id}" if project_id else "",
        "legacy_run": f"/control/api/runs/{run_id}" if run_id else "",
    }


def paper_links(row: dict[str, Any]) -> dict[str, str]:
    paper_id = _url_path_segment(row.get("paper_id"))
    project_id = _url_path_segment(row.get("project_id"))
    run_id = _url_path_segment(row.get("run_id"))
    return {
        "paper": f"/control/api/v1/papers/{paper_id}" if paper_id else "",
        "project": f"/control/api/v1/projects/{project_id}" if project_id else "",
        "run": f"/control/api/v1/runs/{run_id}" if run_id else "",
        "legacy_paper": f"/control/api/papers/{paper_id}" if paper_id else "",
    }


def summarize_queue_row(row: dict[str, Any]) -> dict[str, Any]:
    decision_fields = _decision_payload_fields(row)
    return _drop_related_artifact_paths(with_operator_stage({
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
        "decision_gate_state": row.get("decision_gate_state", ""),
        "decision_summary": row.get("decision_summary", ""),
        **decision_fields,
        "followup_recommended": row.get("followup_recommended", False),
        "followup_type": row.get("followup_type", ""),
        "followup_title": row.get("followup_title", ""),
        "followup_hypothesis": row.get("followup_hypothesis", ""),
        "followup_required_evidence": row.get("followup_required_evidence", []),
        "followup_success_threshold": row.get("followup_success_threshold", ""),
        "followup_stop_condition": row.get("followup_stop_condition", ""),
        "followup_depth": row.get("followup_depth", 0),
        "source_followup_depth": row.get("source_followup_depth", 0),
        "followup_launched": row.get("followup_launched", False),
        "project_dir": row.get("project_dir", ""),
        "related_paper_id": row.get("related_paper_id", ""),
        "related_paper_status": row.get("related_paper_status", ""),
        "related_review_status": row.get("related_review_status", ""),
        "related_finalization_package_path": row.get("related_finalization_package_path", ""),
        "related_draft_markdown_path": row.get("related_draft_markdown_path", ""),
        "related_evidence_bundle_path": row.get("related_evidence_bundle_path", ""),
        "related_claim_ledger_path": row.get("related_claim_ledger_path", ""),
        "related_manifest_path": row.get("related_manifest_path", ""),
        "related_corpus_imported": row.get("related_corpus_imported", False),
        "related_corpus_import_id": row.get("related_corpus_import_id", ""),
        "related_artifact_slug": row.get("related_artifact_slug", ""),
        "related_source_record_fingerprint": row.get("related_source_record_fingerprint", ""),
        "updated_at": row.get("updated_at", ""),
        "age_seconds": row_age_seconds(row),
        "links": queue_links(row),
    }))


def summarize_paper_row(row: dict[str, Any]) -> dict[str, Any]:
    summary = with_operator_stage({
        "paper_id": row.get("paper_id", ""),
        "project_id": row.get("project_id", ""),
        "project_name": row.get("project_name", ""),
        "run_id": row.get("run_id", ""),
        "paper_type": row.get("paper_type", ""),
        "paper_status": row.get("paper_status", ""),
        "draft_markdown_path": row.get("draft_markdown_path", ""),
        "draft_latex_path": row.get("draft_latex_path", ""),
        "evidence_bundle_path": row.get("evidence_bundle_path", ""),
        "claim_ledger_path": row.get("claim_ledger_path", ""),
        "manifest_path": row.get("manifest_path", ""),
        "review_status": row.get("review_status", ""),
        "finalization_package_path": row.get("finalization_package_path", ""),
        "corpus_imported": row.get("corpus_imported", False),
        "corpus_import_id": row.get("corpus_import_id", ""),
        "artifact_slug": row.get("artifact_slug", ""),
        "source_record_fingerprint": row.get("source_record_fingerprint", ""),
        "corpus_commit_sha": row.get("corpus_commit_sha", ""),
        "corpus_manifest_path": row.get("corpus_manifest_path", ""),
        "corpus_imported_at": row.get("corpus_imported_at", ""),
        "hf_dataset_synced": row.get("hf_dataset_synced", False),
        "generated_at": row.get("generated_at", ""),
        "updated_at": row.get("updated_at", ""),
        "age_seconds": row_age_seconds(row),
        "artifact_paths_present": {
            name: bool(row.get(name))
            for name in ("draft_markdown_path", "draft_latex_path", "evidence_bundle_path", "claim_ledger_path", "manifest_path")
        },
        "links": paper_links(row),
    })
    for private_path_field in (
        "draft_markdown_path",
        "draft_latex_path",
        "evidence_bundle_path",
        "claim_ledger_path",
        "manifest_path",
    ):
        summary.pop(private_path_field, None)
    return summary


def summarize_run_row(row: dict[str, Any]) -> dict[str, Any]:
    run_id = str(row.get("run_id") or "")
    project_id = str(row.get("project_id") or "")
    return _drop_related_artifact_paths(with_operator_stage({
        "run_id": run_id,
        "project_id": project_id,
        "project_name": row.get("project_name", ""),
        "session_id": row.get("session_id", ""),
        "related_paper_id": row.get("related_paper_id", ""),
        "related_paper_status": row.get("related_paper_status", ""),
        "related_review_status": row.get("related_review_status", ""),
        "related_finalization_package_path": row.get("related_finalization_package_path", ""),
        "related_draft_markdown_path": row.get("related_draft_markdown_path", ""),
        "related_evidence_bundle_path": row.get("related_evidence_bundle_path", ""),
        "related_claim_ledger_path": row.get("related_claim_ledger_path", ""),
        "related_manifest_path": row.get("related_manifest_path", ""),
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
    }))


OPERATOR_STAGE_PRECEDENCE = {
    "blocked_needs_operator": 100,
    "needs_review": 90,
    "ready_to_publish": 80,
    "finalization_needed": 75,
    "draft_created": 70,
    "run_complete_draft_needed": 60,
    "compute_scale_blocked": 57,
    "useful_signal": 56,
    "followup_candidate": 55,
    "running": 50,
    "idea_queued": 40,
    "run_complete_no_paper": 30,
    "paused_work": 20,
}

OPERATOR_LANE_PRECEDENCE = {
    OperatorLane.NEEDS_OPERATOR.value: 100,
    OperatorLane.READY_TO_PUBLISH.value: 90,
    OperatorLane.AUTOMATE_PUBLICATION.value: 80,
    OperatorLane.WRITE_PAPER.value: 70,
    OperatorLane.RUNNING.value: 60,
    OperatorLane.COMPUTE_SCALE_BLOCKED.value: 57,
    OperatorLane.USEFUL_SIGNAL.value: 56,
    OperatorLane.FOLLOWUP_INVESTIGATION.value: 55,
    OperatorLane.READY_QUEUE.value: 50,
    OperatorLane.COMPLETE_NO_PAPER.value: 40,
    OperatorLane.PAUSED.value: 30,
    OperatorLane.PUBLISHED.value: 20,
    OperatorLane.HISTORICAL.value: 10,
}


def _typed_lifecycle_key(row: dict[str, Any]) -> str:
    paper_id = _text(row.get("paper_id"))
    project_id = _text(row.get("project_id"))
    if paper_id:
        run_id = _text(row.get("run_id") or row.get("current_run_id"))
        paper_type = _text(row.get("paper_type")) or "arxiv_draft"
        if project_id and run_id:
            return f"paper_identity:{project_id}:{run_id}:{paper_type}"
        return f"paper:{paper_id}"
    if project_id:
        if bool(row.get("operator_attention")):
            run_id = _text(row.get("run_id") or row.get("current_run_id"))
            status = _text(row.get("status") or row.get("queue_status") or row.get("last_run_state") or row.get("state") or row.get("gate_state"))
            return f"queue_attention:{project_id}:{run_id or status}"
        return f"queue:{project_id}"
    run_id = _text(row.get("run_id") or row.get("current_run_id"))
    if run_id:
        return f"run:{run_id}"
    return ""




def _operator_row_is_active(row: dict[str, Any]) -> bool:
    status = _text(row.get("status") or row.get("queue_status"))
    state = _text(row.get("last_run_state") or row.get("state") or row.get("gate_state"))
    return status in ACTIVE_QUEUE_STATUSES or state in ACTIVE_QUEUE_STATUSES


def _strip_related_paper_projection(row: dict[str, Any]) -> dict[str, Any]:
    stripped = {
        **row,
        "related_paper_id": "",
        "related_paper_status": "",
        "related_review_status": "",
        "related_finalization_package_path": "",
        "related_draft_markdown_path": "",
        "related_evidence_bundle_path": "",
        "related_claim_ledger_path": "",
        "related_manifest_path": "",
        "related_corpus_imported": False,
        "related_corpus_import_id": "",
        "related_artifact_slug": "",
        "related_source_record_fingerprint": "",
    }
    for key in (
        "operator_stage",
        "operator_stage_label",
        "operator_lane",
        "operator_detail_stage",
        "operator_detail_stage_label",
        "operator_tone",
        "operator_attention",
        "operator_next_step",
        "operator_explanation",
    ):
        stripped.pop(key, None)
    return with_operator_stage(stripped)


def _has_related_paper_projection(row: dict[str, Any]) -> bool:
    return any(
        _text(row.get(key))
        for key in (
            "related_paper_id",
            "related_paper_status",
            "related_review_status",
            "related_finalization_package_path",
            "related_draft_markdown_path",
            "related_evidence_bundle_path",
            "related_claim_ledger_path",
            "related_manifest_path",
            "related_corpus_import_id",
            "related_artifact_slug",
            "related_source_record_fingerprint",
        )
    ) or _truthy(row.get("related_corpus_imported"))


def _queue_is_superseded_by_paper(
    row: dict[str, Any],
    paper_run_keys: set[tuple[str, str]],
) -> bool:
    project_id = _text(row.get("project_id"))
    run_id = _text(row.get("run_id") or row.get("current_run_id"))
    if project_id and run_id and (project_id, run_id) in paper_run_keys:
        return True
    return False


def _reconciled_operator_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    staged_rows = [with_operator_stage(row) for row in rows]
    paper_run_keys = {
        (_text(row.get("project_id")), _text(row.get("run_id")))
        for row in staged_rows
        if _text(row.get("paper_id")) and _text(row.get("project_id")) and _text(row.get("run_id"))
    }
    paper_ids = {_text(row.get("paper_id")) for row in staged_rows if _text(row.get("paper_id"))}
    by_key: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    for staged in staged_rows:
        related_paper_id = _text(staged.get("related_paper_id"))
        is_queue_row = not _text(staged.get("paper_id"))
        is_active_row = _operator_row_is_active(staged)
        needs_attention = bool(staged.get("operator_attention"))
        if is_queue_row and _has_related_paper_projection(staged) and (not related_paper_id or related_paper_id not in paper_ids):
            staged = _strip_related_paper_projection(staged)
            related_paper_id = ""
        if is_queue_row and related_paper_id and related_paper_id in paper_ids and not is_active_row and not needs_attention:
            continue
        if is_queue_row and not is_active_row and not needs_attention and _queue_is_superseded_by_paper(staged, paper_run_keys):
            continue
        key = _typed_lifecycle_key(staged)
        if not key:
            anonymous.append(staged)
            continue
        current = by_key.get(key)
        current_is_active = _operator_row_is_active(current or {})
        if current is not None and current_is_active and not is_active_row:
            continue
        if current is not None and is_active_row and not current_is_active:
            by_key[key] = staged
            continue
        detail_stage = _text(staged.get("operator_detail_stage"))
        current_detail_stage = _text((current or {}).get("operator_detail_stage"))
        lane = _text(staged.get("operator_lane") or staged.get("operator_stage"))
        current_lane = _text((current or {}).get("operator_lane") or (current or {}).get("operator_stage"))
        if current is not None and current_lane == OperatorLane.PUBLISHED.value and lane != OperatorLane.NEEDS_OPERATOR.value:
            continue
        if current is not None and lane == OperatorLane.PUBLISHED.value and current_lane != OperatorLane.NEEDS_OPERATOR.value:
            by_key[key] = staged
            continue
        precedence = max(OPERATOR_STAGE_PRECEDENCE.get(detail_stage, 0), OPERATOR_LANE_PRECEDENCE.get(lane, 0))
        current_precedence = max(OPERATOR_STAGE_PRECEDENCE.get(current_detail_stage, 0), OPERATOR_LANE_PRECEDENCE.get(current_lane, 0))
        if current is None or precedence > current_precedence:
            by_key[key] = staged
    return [*by_key.values(), *anonymous]


def operator_detail_counts_from_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in _reconciled_operator_rows(rows):
        detail_stage = _text(row.get("operator_detail_stage")) or operator_stage_for_record(row)["operator_detail_stage"]
        counts[detail_stage] = counts.get(detail_stage, 0) + 1
    return counts


def operator_counts_from_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    reconciled = _reconciled_operator_rows(rows)
    for row in reconciled:
        lane = _text(row.get("operator_lane") or row.get("operator_stage")) or operator_stage_for_record(row)["operator_lane"]
        counts[lane] = counts.get(lane, 0) + 1
    counts["needs_attention"] = sum(1 for row in reconciled if bool(row.get("operator_attention") or operator_stage_for_record(row)["operator_attention"]))
    counts[OperatorLane.READY_TO_PUBLISH.value] = counts.get(OperatorLane.READY_TO_PUBLISH.value, 0)
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


_OVERVIEW_BATCH_KEYS = {
    "counts",
    "paper_counts",
    "active_items",
    "next_candidate",
    "raw_queue_rows",
    "raw_paper_rows",
    "events_page",
}


def _valid_overview_batch(value: Any) -> Mapping[str, Any] | None:
    """Return a usable optimized overview batch or None to use canonical reads.

    The batched overview path is an optimization used by live adapters. It must
    not become a single malformed-response failure point for the operator
    dashboard; canonical read methods remain the source of truth fallback.
    """

    if not isinstance(value, Mapping):
        return None
    if not _OVERVIEW_BATCH_KEYS.issubset(value.keys()):
        return None
    events_page = value.get("events_page")
    if not isinstance(events_page, tuple) or len(events_page) != 3:
        return None
    for rows_key in ("active_items", "raw_queue_rows", "raw_paper_rows"):
        rows = value.get(rows_key)
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            return None
    if not isinstance(value.get("counts"), dict) or not isinstance(value.get("paper_counts"), dict):
        return None
    return value


def overview(store: ControlPlaneStore, *, active_limit: int = 5, event_limit: int = 10) -> dict[str, Any]:
    batched_parts = None
    batched_reader = getattr(store, "overview_read_model_parts", None)
    if callable(batched_reader):
        batched_parts = _valid_overview_batch(batched_reader(active_limit=active_limit, event_limit=event_limit))

    if batched_parts is not None:
        counts = batched_parts["counts"]
        paper_counts = batched_parts["paper_counts"]
        active = [summarize_queue_row(row) for row in batched_parts["active_items"]]
        next_candidate = batched_parts["next_candidate"]
        raw_queue_rows = batched_parts["raw_queue_rows"]
        raw_paper_rows = batched_parts["raw_paper_rows"]
    else:
        counts = store.queue_counts_sql()
        paper_counts = store.paper_counts_sql()
        active = [summarize_queue_row(row) for row in store.active_items_sql(limit=active_limit)]
        next_candidate = store.next_candidate_sql()
        raw_queue_rows = store.operator_queue_rows_sql()
        raw_paper_rows = store.operator_paper_rows_sql()
    queue_rows = [summarize_queue_row(row) for row in raw_queue_rows]
    paper_rows = [summarize_paper_row(row) for row in raw_paper_rows]
    # Supabase batched overview intentionally trims raw_queue_rows to keep the
    # dashboard cheap. Active rows are fetched separately for the running-work
    # card, so include them in reconciled operator counts as well. The
    # reconciler deduplicates when an adapter returns the same active row in
    # both surfaces.
    operator_queue_rows = [*queue_rows, *active]
    operator_counts = operator_counts_from_rows([*operator_queue_rows, *paper_rows])
    operator_detail_counts = operator_detail_counts_from_rows([*operator_queue_rows, *paper_rows])
    raw_write_candidates = eligible_paper_draft_candidates(raw_queue_rows, raw_paper_rows)
    write_candidates: list[dict[str, Any]] = []
    gate_rejected: list[dict[str, Any]] = []
    for candidate in raw_write_candidates:
        gate = _paper_draft_gate_from_row_decision(candidate) or _paper_draft_gate_for_row(candidate)
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
    # Operator counts are the high-level read model used by cards and alerts.
    # `write_paper` must stay decision-gated here too; otherwise completed
    # no-paper rows with missing/negative/unknown decisions leak into the
    # operator-facing lane even though `paper_pipeline.write_needed` is 0.
    operator_counts[OperatorLane.WRITE_PAPER.value] = len(write_candidates)
    if write_candidates:
        operator_detail_counts["run_complete_draft_needed"] = len(write_candidates)
    else:
        operator_detail_counts.pop("run_complete_draft_needed", None)
    reconciled_queue_rows = _reconciled_operator_rows(queue_rows)
    followup_rows = [row for row in reconciled_queue_rows if _text(row.get("operator_detail_stage")) == "followup_candidate"]
    followup_rows.sort(key=lambda row: (1 if _is_useful_signal(row) else 0, _text(row.get("updated_at"))), reverse=True)
    useful_signal_rows = [row for row in reconciled_queue_rows if _text(row.get("operator_lane")) == OperatorLane.USEFUL_SIGNAL.value]
    compute_scale_blocked_rows = [row for row in reconciled_queue_rows if _text(row.get("operator_lane")) == OperatorLane.COMPUTE_SCALE_BLOCKED.value]
    publish_candidates = [row for row in paper_rows if _text(row.get("operator_stage")) == "ready_to_publish"]
    imported_candidates = [row for row in paper_rows if _paper_imported(row)]
    imported_candidates.sort(key=lambda row: _text(row.get("corpus_imported_at") or row.get("updated_at")), reverse=True)
    publication_ready_total = operator_counts.get(OperatorLane.READY_TO_PUBLISH.value, 0) + operator_counts.get(OperatorLane.PUBLISHED.value, 0)
    investigation_pipeline = {
        "followup_needed": len(followup_rows),
        "useful_signals": len(useful_signal_rows),
        "compute_scale_blocked": len(compute_scale_blocked_rows),
        "max_followup_depth": MAX_FOLLOWUP_DEPTH,
        "next_followup_candidate": followup_rows[0] if followup_rows else None,
        "next_useful_signal": useful_signal_rows[0] if useful_signal_rows else None,
        "next_compute_scale_blocked": compute_scale_blocked_rows[0] if compute_scale_blocked_rows else None,
        "definitions": {
            "followup_needed": "completed no-paper rows whose decision artifact recommends a bounded adjacent investigation",
            "useful_signals": "completed runs with bounded local evidence that is useful but not currently paper-positive",
            "compute_scale_blocked": "promising signals whose next evidence would exceed local compute or wall-clock limits",
            "max_followup_depth": "default safety cap for bounded research-campaign follow-up creation",
        },
    }
    paper_pipeline = {
        "write_needed": len(write_candidates),
        "raw_completed_no_paper_candidates": len(raw_write_candidates),
        "not_writable_by_decision_gate": len(gate_rejected),
        "gate_rejected_sample": gate_rejected[:10],
        "next_write_candidate": draft_candidate_payload(write_candidates[0]) if write_candidates else None,
        "finalize_needed": operator_detail_counts.get("finalization_needed", 0),
        "publish_ready": operator_counts.get(OperatorLane.READY_TO_PUBLISH.value, 0),
        "next_publish_candidate": publish_candidates[0] if publish_candidates else None,
        "last_import_result": imported_candidates[0] if imported_candidates else None,
        "missing_from_corpus": operator_counts.get(OperatorLane.READY_TO_PUBLISH.value, 0),
        "published_imported": operator_counts.get(OperatorLane.PUBLISHED.value, 0),
        "publication_ready_total": publication_ready_total,
        "definitions": {
            "write_needed": "completed runs with no live paper row that currently pass the paper-ready gate",
            "raw_completed_no_paper_candidates": "completed no-paper rows before checking local project decision artifacts",
            "not_writable_by_decision_gate": "completed no-paper rows rejected by local project decision artifacts as negative, ambiguous, or otherwise non-positive",
            "finalize_needed": "publication drafts missing automated finalization package",
            "publish_ready": "finalized publication drafts with required evidence paths that are missing a corpus-import ledger row",
            "missing_from_corpus": "same as publish_ready; actionable corpus import work only",
            "published_imported": "papers represented by the corpus-import ledger",
            "publication_ready_total": "finalized publication drafts with required evidence paths, whether already imported or still missing corpus import",
        },
    }
    if batched_parts is not None:
        events, next_cursor, has_more = batched_parts["events_page"]
    else:
        events, next_cursor, has_more = store.event_page(page_size=event_limit, include_payload=False)
    return {
        "counts": {
            **counts,
            "papers": paper_counts.get("all", 0),
        },
        "paper_counts": paper_counts,
        "operator_counts": operator_counts,
        "operator_detail_counts": operator_detail_counts,
        "paper_pipeline": paper_pipeline,
        "investigation_pipeline": investigation_pipeline,
        "operator_model": {
            "source": "control_plane.read_models.operator_stage_for_record",
            "raw_state_note": "wake_ready/session_finished_ready are worker-delivery callbacks; paper polarity comes from decision artifacts and publication automation/finalization state.",
        },
        "active_items": active,
        "next_candidate": summarize_queue_row(next_candidate) if next_candidate else None,
        "recent_events": events,
        "recent_events_page": page_response(rows=events, next_cursor=next_cursor, has_more=has_more, page_size_value=page_size(event_limit), cursor="", filters={}),
    }
