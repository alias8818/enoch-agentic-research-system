from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, NamedTuple, Sequence
from urllib.parse import quote

from enoch_control_plane.enoch_core.logic import (
    draft_candidate_payload,
    eligible_paper_draft_candidates,
    paper_draft_decision_gate,
)
from enoch_control_plane.research_quality.status import (
    DEFAULT_AUTOPILOT_HISTORY_PATH,
    DEFAULT_REPORT_PATHS,
    DEFAULT_WINDOW_REPORT_PATH,
    load_latest_quality_status,
)
from enoch_control_plane.timeutils import parse_utc_datetime

from .models import PaperStatus, QueueStatus
from .promising_signal_priority import (
    COMPUTE_SCALE_BLOCKED,
    FOLLOWUP_RECOMMENDED,
    LIKELY_STALE_LOW_VALUE_ARCHIVE,
    TOP_EXTERNAL_RESEARCHER_CANDIDATES,
    promising_followup_priority_key,
    promising_signal_bucket,
    ranked_followup_readiness,
)
from .llm_harness_telemetry import (
    LLM_HARNESS_COST_OBSERVATION_EVENT,
    LLM_HARNESS_EVENT_TYPES,
)
from .research_quality_freshness import research_quality_report_freshness
from .state_contract import (
    ACTIVE_QUEUE_STATUSES,
    ATTENTION_QUEUE_STATUSES,
    DRAFT_PAPER_STATUSES,
    PAPER_DRAFT_NEXT_ACTION,
    PAPER_READINESS_MATURITY_STATES,
    PUBLICATION_READY_AUTOMATION_STATUSES,
    OperatorLane,
    WAKE_GATE_COMPLETION_STATES,
)

# Centralized reason constant for the top remaining S1192 duplication
# in this file (decision gates and mappings).
MISSING_PROJECT_DECISION_ARTIFACT_REASON = "missing project decision artifact"

ACTION_HASH_OVERVIEW = "#overview"
ACTION_HASH_QUEUE_QUEUED = "#queue:queued"
ACTION_HASH_RESEARCH = "#research"

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


def _first_non_empty(row: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        if text := _text(row.get(key)):
            return text
    return ""


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


PUBLICATION_ARTIFACT_FIELDS = (
    "finalization_package_path",
    "draft_markdown_path",
    "draft_latex_path",
    "evidence_bundle_path",
    "claim_ledger_path",
    "manifest_path",
)
REQUIRED_PUBLICATION_ARTIFACT_FIELDS = (
    "finalization_package_path",
    "draft_markdown_path",
    "evidence_bundle_path",
    "claim_ledger_path",
    "manifest_path",
)


def _artifact_file_is_readable(
    project_dir: Any, raw_path: Any, *, allow_absolute_outside_root: bool = False
) -> bool:
    project_dir_text = _text(project_dir)
    path_text = _text(raw_path)
    if not path_text:
        return False
    try:
        candidate = Path(path_text).expanduser()
        if candidate.is_absolute() and allow_absolute_outside_root:
            return candidate.resolve(strict=False).is_file()
        if not project_dir_text:
            return False
        root = Path(project_dir_text).expanduser().resolve(strict=True)
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
        return resolved.is_file()
    except (OSError, RuntimeError, ValueError):
        return False


def _paper_artifact_flags(row: dict[str, Any]) -> dict[str, bool]:
    existing_flags = row.get("artifact_paths_present")
    if isinstance(existing_flags, dict):
        return {
            name: bool(existing_flags.get(name)) for name in PUBLICATION_ARTIFACT_FIELDS
        }
    project_dir = row.get("project_dir")
    return {
        name: _artifact_file_is_readable(
            project_dir,
            row.get(name),
            allow_absolute_outside_root=(name == "finalization_package_path"),
        )
        for name in PUBLICATION_ARTIFACT_FIELDS
    }


def _related_artifact_paths_present(row: dict[str, Any]) -> dict[str, bool]:
    project_dir = row.get("project_dir")
    return {
        name: _artifact_file_is_readable(
            project_dir,
            row.get(field),
            allow_absolute_outside_root=(name == "finalization_package_path"),
        )
        for name, field in RELATED_PAPER_ARTIFACT_FIELDS.items()
    }


def _drop_related_artifact_paths(summary: dict[str, Any]) -> dict[str, Any]:
    summary["related_artifact_paths_present"] = _related_artifact_paths_present(summary)
    for field in RELATED_PAPER_ARTIFACT_FIELDS.values():
        summary.pop(field, None)
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
        summary.pop(key, None)
    return with_operator_stage(summary)


def _paper_publication_artifacts_present(row: dict[str, Any]) -> bool:
    artifact_flags = row.get("artifact_paths_present")
    if isinstance(artifact_flags, dict):
        return all(
            bool(artifact_flags.get(name))
            for name in REQUIRED_PUBLICATION_ARTIFACT_FIELDS
        )
    related_artifact_flags = row.get("related_artifact_paths_present")
    if isinstance(related_artifact_flags, dict):
        return all(
            bool(related_artifact_flags.get(name))
            for name in REQUIRED_PUBLICATION_ARTIFACT_FIELDS
        )
    return False


def _paper_finalization_package_present(row: dict[str, Any]) -> bool:
    artifact_flags = row.get("artifact_paths_present")
    if isinstance(artifact_flags, dict):
        return bool(artifact_flags.get("finalization_package_path"))
    related_artifact_flags = row.get("related_artifact_paths_present")
    if isinstance(related_artifact_flags, dict):
        return bool(related_artifact_flags.get("finalization_package_path"))
    return False


def _stage(detail_label: str, /, **fields: Any) -> dict[str, Any]:
    lane = fields.pop("lane")
    tone = fields.pop("tone")
    attention = fields.pop("attention")
    next_step = fields.pop("next_step")
    explanation = fields.pop("explanation")
    stage = {
        "operator_stage": lane.value,
        "operator_stage_label": OPERATOR_LANE_LABELS.get(
            lane.value, lane.value.replace("_", " ").title()
        ),
        "operator_lane": lane.value,
        "operator_detail_stage": detail_label,
        "operator_detail_stage_label": OPERATOR_DETAIL_LABELS.get(
            detail_label, detail_label.replace("_", " ").title()
        ),
        "operator_tone": tone,
        "operator_attention": attention,
        "operator_next_step": next_step,
        "operator_explanation": explanation,
    }
    stage.update({key: value for key, value in fields.items() if value is not None})
    return stage


def _configured_project_root() -> str:
    config_path = os.environ.get("ENOCH_CONFIG") or os.environ.get(
        "ENOCH_CONTROL_PLANE_CONFIG", "/etc/enoch/config.json"
    )
    try:
        with open(config_path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return ""
    return _text(payload.get("project_root"))


def _expanduser_or_none(value: str) -> Path | None:
    try:
        return Path(value).expanduser()
    except RuntimeError:
        return None


def _configured_project_root_path() -> Path | None:
    configured_root = _configured_project_root()
    if not configured_root:
        return None
    return _expanduser_or_none(configured_root)


def _project_dir_relative_candidates(raw: Path) -> list[Path]:
    candidates: list[Path] = []
    root = _configured_project_root_path()
    if root is not None:
        candidates.append(root / raw)
    candidates.append(Path("/var/lib/enoch-control-plane/projects") / raw)
    return candidates


def _dedupe_paths(candidates: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            deduped.append(candidate)
    return deduped


def _project_dir_candidates(project_dir: str) -> list[Path]:
    raw = _expanduser_or_none(project_dir)
    if raw is None:
        return []
    candidates = [raw]
    if not raw.is_absolute():
        candidates.extend(_project_dir_relative_candidates(raw))
    return _dedupe_paths(candidates)


def _paper_draft_gate_for_row(row: dict[str, Any]) -> dict[str, Any] | None:
    project_dir = _text(row.get("project_dir"))
    if not project_dir:
        project_dir = _text(row.get("project_id"))
    if not project_dir:
        return {
            "eligible": False,
            "reason": MISSING_PROJECT_DECISION_ARTIFACT_REASON,
            "values": [],
            "project_dir": "",
        }
    last_gate: dict[str, Any] | None = None
    for candidate in _project_dir_candidates(project_dir):
        try:
            gate = paper_draft_decision_gate(candidate)
        except (OSError, ValueError):
            last_gate = {
                "eligible": False,
                "reason": "project decision artifact could not be read",
                "values": [],
                "project_dir": str(candidate),
            }
            continue
        values = gate.get("values")
        if isinstance(values, list):
            gate = {**gate, "values": values[:8]}
        gate = {**gate, "project_dir": str(candidate)}
        if (
            values
            or _text(gate.get("reason")) != MISSING_PROJECT_DECISION_ARTIFACT_REASON
        ):
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
        return [
            item.strip()
            for item in value.replace(";", "\n").splitlines()
            if item.strip()
        ]
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
        "research_outcome": row.get(
            "research_outcome", decision.get("research_outcome", "")
        ),
        "hypothesis_status": row.get(
            "hypothesis_status", decision.get("hypothesis_status", "")
        ),
        "evidence_strength": row.get(
            "evidence_strength", decision.get("evidence_strength", "")
        ),
        "claim_scope": row.get("claim_scope", decision.get("claim_scope", "")),
        "scale_limits": row.get("scale_limits", decision.get("scale_limits", "")),
        "useful_signal_summary": row.get(
            "useful_signal_summary", decision.get("useful_signal_summary", "")
        ),
        "bounded_paper_ready": row.get(
            "bounded_paper_ready", decision.get("bounded_paper_ready", False)
        ),
        "compute_scale_blocked": row.get(
            "compute_scale_blocked", decision.get("compute_scale_blocked", False)
        ),
        "recommended_next_action": row.get(
            "recommended_next_action", decision.get("recommended_next_action", "")
        ),
        "stop_reason": row.get("stop_reason", decision.get("stop_reason", "")),
    }


def _research_outcome(row: dict[str, Any]) -> str:
    if "decision_payload_json" in row and not _text(row.get("research_outcome")):
        row = {**row, **_decision_payload_fields(row)}
    outcome = (
        _text(row.get("research_outcome")).lower().replace("-", "_").replace(" ", "_")
    )
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
    return outcome in {"useful_signal", "promising_if_scaled"} and any(
        marker in haystack for marker in scale_markers
    )


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
        depth = max(
            int(row.get("followup_depth") or 0),
            int(row.get("source_followup_depth") or 0),
        )
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
        depth = max(
            int(row.get("followup_depth") or 0),
            int(row.get("source_followup_depth") or 0),
        )
    except (TypeError, ValueError):
        depth = 0
    required_evidence = _listish(row.get("followup_required_evidence"))
    return bool(
        _truthy(row.get("followup_recommended"))
        and _text(row.get("status") or row.get("queue_status")) == "completed"
        and not _truthy(row.get("manual_review_required"))
        and not _truthy(row.get("followup_launched"))
        and not _compute_scale_blocked(row)
        and depth < MAX_FOLLOWUP_DEPTH
        and _normal(row.get("followup_type")) in {"deepen", "branch", "retry"}
        and _text(row.get("followup_title"))
        and _text(row.get("followup_hypothesis"))
        and len(required_evidence) >= MIN_FOLLOWUP_REQUIRED_EVIDENCE
        and _text(row.get("followup_success_threshold"))
        and _text(row.get("followup_stop_condition"))
    )


def _bounded_followup_fields_present(row: dict[str, Any]) -> bool:
    return bool(
        _truthy(row.get("followup_recommended"))
        and _normal(row.get("followup_type")) in {"deepen", "branch", "retry"}
        and _text(row.get("followup_title"))
        and _listish(row.get("followup_required_evidence"))
        and _text(row.get("followup_success_threshold"))
        and _text(row.get("followup_stop_condition"))
    )


def _supported_signal_requires_bounded_followup(row: dict[str, Any]) -> bool:
    return bool(
        _research_outcome(row) == "useful_signal"
        and not _truthy(row.get("bounded_paper_ready"))
        and _normal(row.get("hypothesis_status")) in {"supported", "mixed"}
        and _normal(row.get("evidence_strength")) in {"moderate", "strong"}
        and _text(row.get("claim_scope"))
        and _bounded_followup_fields_present(row)
    )


def _paper_draft_gate_from_row_decision(row: dict[str, Any]) -> dict[str, Any] | None:
    state = _text(row.get("decision_gate_state"))
    if not state:
        return None
    summary = _text(row.get("decision_summary"))
    if state == "positive":
        reason = (
            "bounded useful signal is paper-scoped"
            if _research_outcome(row) == "useful_signal"
            and _truthy(row.get("bounded_paper_ready"))
            else "project decision is positive"
        )
        return {
            "eligible": True,
            "reason": reason,
            "decision": summary or state,
            "values": [],
            "source": "supabase_project_decisions",
        }
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
    if state == "negative" and _supported_signal_requires_bounded_followup(row):
        return {
            "eligible": False,
            "reason": "bounded follow-up required before paper writing",
            "decision": summary or state,
            "values": _listish(row.get("followup_required_evidence")),
            "source": "supabase_project_decisions",
        }
    reason_by_state = {
        "negative": "project decision is not positive",
        "needs_review": "project decision is not positive",
        "missing": MISSING_PROJECT_DECISION_ARTIFACT_REASON,
        "malformed": "project decision artifact could not be read",
        "unknown": "project decision lacks positive draft signal",
    }
    return {
        "eligible": False,
        "reason": reason_by_state.get(
            state, "project decision lacks positive draft signal"
        ),
        "decision": summary,
        "values": [],
        "source": "supabase_project_decisions",
    }


from .operator_stage import operator_stage_for_record


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


def project_links(row: dict[str, Any]) -> dict[str, str]:
    project_id = _url_path_segment(row.get("project_id"))
    run_id = _url_path_segment(row.get("current_run_id") or row.get("latest_run_id"))
    paper_id = _url_path_segment(
        row.get("related_paper_id") or row.get("latest_paper_id")
    )
    return {
        "project": f"/control/api/v1/projects/{project_id}" if project_id else "",
        "run": f"/control/api/v1/runs/{run_id}" if run_id else "",
        "paper": f"/control/api/v1/papers/{paper_id}" if paper_id else "",
        "legacy_project": f"/control/api/projects/{project_id}" if project_id else "",
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


def research_quality_sample_links(row: Mapping[str, Any]) -> dict[str, str]:
    project_id = _url_path_segment(row.get("project_id"))
    run_id = _url_path_segment(row.get("run_id"))
    return {
        "project": f"/control/api/v1/projects/{project_id}" if project_id else "",
        "run": f"/control/api/v1/runs/{run_id}" if run_id else "",
        "legacy_project": f"/control/api/projects/{project_id}" if project_id else "",
        "legacy_run": f"/control/api/runs/{run_id}" if run_id else "",
    }


def _project_row_stage_source(row: dict[str, Any]) -> dict[str, Any]:
    queue_status = row.get("queue_status") or row.get("status") or ""
    return {
        **row,
        "status": queue_status,
        "current_run_id": row.get("current_run_id") or row.get("latest_run_id") or "",
        "related_paper_id": row.get("related_paper_id")
        or row.get("latest_paper_id")
        or "",
        "related_paper_status": row.get("related_paper_status")
        or row.get("latest_paper_status")
        or "",
        "project_updated_at": row.get("project_updated_at")
        or row.get("updated_at")
        or "",
    }


def summarize_project_row(row: dict[str, Any]) -> dict[str, Any]:
    project_id = str(row.get("project_id") or "")
    stage_source = _project_row_stage_source(row)
    queue_status = stage_source["status"]
    staged = with_operator_stage(stage_source)
    operator_fields = {
        key: value for key, value in staged.items() if key.startswith("operator_")
    }
    return _drop_related_artifact_paths(
        {
            "project_id": project_id,
            "project_name": row.get("project_name", ""),
            "origin_idea_status": row.get("origin_idea_status", ""),
            "queue_status": queue_status,
            "current_run_id": stage_source["current_run_id"],
            "latest_run_id": row.get("latest_run_id", ""),
            "latest_run_state": row.get("latest_run_state", ""),
            "related_paper_id": stage_source["related_paper_id"],
            "related_paper_status": stage_source["related_paper_status"],
            "created_at": row.get("project_created_at") or row.get("created_at", ""),
            "updated_at": stage_source["project_updated_at"],
            "age_seconds": row_age_seconds(
                {
                    "updated_at": stage_source["project_updated_at"],
                    "created_at": row.get("project_created_at")
                    or row.get("created_at", ""),
                }
            ),
            "links": project_links(stage_source),
            **operator_fields,
        }
    )


def summarize_queue_row(row: dict[str, Any]) -> dict[str, Any]:
    decision_fields = _decision_payload_fields(row)
    return _drop_related_artifact_paths(
        with_operator_stage(
            {
                "project_id": _text(row.get("project_id")),
                "project_name": _text(row.get("project_name")),
                "status": _text(row.get("status")),
                "machine_target": _text(row.get("machine_target")),
                "model": _text(row.get("model")),
                "sandbox": _text(row.get("sandbox")),
                "dispatch_priority": row.get("dispatch_priority", 0),
                "selection_rank": row.get("selection_rank", 0),
                "current_run_id": _text(row.get("current_run_id")),
                "current_session_id": _text(row.get("current_session_id")),
                "last_run_state": _text(row.get("last_run_state")),
                "next_action_hint": _text(row.get("next_action_hint")),
                "manual_review_required": _truthy(row.get("manual_review_required")),
                "blocked_reason": _text(row.get("blocked_reason")),
                "decision_gate_state": _text(row.get("decision_gate_state")),
                "decision_summary": _text(row.get("decision_summary")),
                **decision_fields,
                "followup_recommended": row.get("followup_recommended", False),
                "followup_type": _text(row.get("followup_type")),
                "followup_title": _text(row.get("followup_title")),
                "followup_hypothesis": _text(row.get("followup_hypothesis")),
                "followup_required_evidence": row.get("followup_required_evidence", []),
                "followup_success_threshold": _text(
                    row.get("followup_success_threshold")
                ),
                "followup_stop_condition": _text(row.get("followup_stop_condition")),
                "followup_depth": row.get("followup_depth", 0),
                "source_followup_depth": row.get("source_followup_depth", 0),
                "followup_launched": row.get("followup_launched", False),
                "project_dir": _text(row.get("project_dir")),
                "related_paper_id": _text(row.get("related_paper_id")),
                "related_paper_status": _text(row.get("related_paper_status")),
                "related_review_status": _text(row.get("related_review_status")),
                "related_finalization_package_path": _text(
                    row.get("related_finalization_package_path")
                ),
                "related_draft_markdown_path": _text(
                    row.get("related_draft_markdown_path")
                ),
                "related_evidence_bundle_path": _text(
                    row.get("related_evidence_bundle_path")
                ),
                "related_claim_ledger_path": _text(
                    row.get("related_claim_ledger_path")
                ),
                "related_manifest_path": _text(row.get("related_manifest_path")),
                "related_corpus_imported": row.get("related_corpus_imported", False),
                "related_corpus_import_id": _text(row.get("related_corpus_import_id")),
                "related_artifact_slug": _text(row.get("related_artifact_slug")),
                "related_source_record_fingerprint": _text(
                    row.get("related_source_record_fingerprint")
                ),
                "updated_at": _text(row.get("updated_at")),
                "age_seconds": row_age_seconds(row),
                "links": queue_links(row),
            }
        )
    )


def _idea_has_queue_context(row: dict[str, Any]) -> bool:
    if _text(row.get("queue_status") or row.get("status")):
        return True
    if _text(row.get("current_run_id")):
        return True
    return bool(_text(row.get("last_run_state")))


_IDEA_WORKBENCH_FIELD_SOURCES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("project_id", ("project_id", "idea_id")),
    ("project_name", ("title",)),
    ("status", ("queue_status", "status")),
    ("queue_status", ("queue_status",)),
    ("origin_idea_status", ("idea_status",)),
    ("paper_status", ("paper_status",)),
    ("related_paper_status", ("paper_status",)),
    ("paper_id", ("paper_id",)),
    ("related_paper_id", ("paper_id",)),
    ("current_run_id", ("current_run_id",)),
    ("last_run_state", ("last_run_state",)),
    ("next_action_hint", ("next_action_hint",)),
    ("blocked_reason", ("blocked_reason",)),
    ("last_error", ("last_error",)),
    ("machine_target", ("machine_target",)),
    ("updated_at", ("queue_updated_at", "updated_at")),
)


def _idea_workbench_stage_source(row: dict[str, Any]) -> dict[str, Any]:
    staged = dict(row)
    for target, sources in _IDEA_WORKBENCH_FIELD_SOURCES:
        staged[target] = _first_non_empty(row, *sources)
    staged["manual_review_required"] = row.get("manual_review_required", False)
    return staged


def summarize_idea_workbench_row(row: dict[str, Any]) -> dict[str, Any]:
    if not _idea_has_queue_context(row):
        return dict(row)
    staged = with_operator_stage(_idea_workbench_stage_source(row))
    operator_fields = {
        key: value for key, value in staged.items() if key.startswith("operator_")
    }
    return {**row, **operator_fields}


def _count_value(counts: dict[str, int] | None, *keys: str) -> int:
    for key in keys:
        value = int((counts or {}).get(key) or 0)
        if value:
            return value
    return 0


def _intake_sync_status(latest_sync: Any) -> str:
    if latest_sync is None:
        return ""
    if hasattr(latest_sync, "status"):
        return _text(getattr(latest_sync, "status", ""))
    if isinstance(latest_sync, dict):
        return _text(latest_sync.get("status"))
    return ""


def _summarize_intake_empty_projection(
    *, sync_status: str, sync_ok: bool, skipped_total: int
) -> str:
    if sync_status and not sync_ok:
        return (
            f"Intake projection is empty and the latest sync reported {sync_status}; "
            "refresh after fixing intake sync."
        )
    if skipped_total:
        return (
            f"No ideas in the bounded intake projection; {skipped_total} row(s) "
            "were skipped on the last sync."
        )
    return (
        "No ideas in the bounded intake projection; intake may be caught up "
        "or waiting on the next sync."
    )


def _summarize_intake_queued_projection(
    *,
    headline: int,
    skipped_total: int,
    sync_status: str,
    sync_ok: bool,
) -> str:
    if skipped_total and sync_status and not sync_ok:
        return (
            f"{headline} idea(s) queued for review; {skipped_total} row(s) skipped "
            f"and the latest sync reported {sync_status}."
        )
    if skipped_total:
        return (
            f"{headline} idea(s) queued for operator review; {skipped_total} row(s) "
            "skipped on the last sync."
        )
    if sync_status and not sync_ok:
        return (
            f"{headline} idea(s) queued for review, but the latest intake sync "
            f"reported {sync_status}."
        )
    return (
        f"{headline} idea(s) queued for operator review; promote or dispatch "
        "from the table below."
    )


def summarize_intake_workbench(
    *,
    projection_counts: dict[str, int] | None,
    queued_projection: list[dict[str, Any]] | None,
    skipped_reasons: dict[str, int] | None,
    latest_sync: Any = None,
) -> str:
    counts = projection_counts or {}
    visible = len(queued_projection or [])
    queued = _count_value(counts, "queued", "queued_projection")
    if not queued and visible:
        queued = visible
    skipped_total = sum(int(value or 0) for value in (skipped_reasons or {}).values())
    sync_status = _intake_sync_status(latest_sync)
    sync_ok = sync_status in {"", "ok", "success", "succeeded"}

    if visible == 0 and queued == 0:
        return _summarize_intake_empty_projection(
            sync_status=sync_status,
            sync_ok=sync_ok,
            skipped_total=skipped_total,
        )
    return _summarize_intake_queued_projection(
        headline=visible or queued,
        skipped_total=skipped_total,
        sync_status=sync_status,
        sync_ok=sync_ok,
    )


def summarize_research_facility_workbench(
    *, counts: dict[str, int] | None, returned_rows: int = 0
) -> str:
    counts = counts or {}
    admitted = _count_value(counts, "admitted")
    needs_review = _count_value(counts, "needs_review")
    total = sum(int(value or 0) for value in counts.values())
    message = ""
    if total == 0 and returned_rows == 0:
        message = (
            "Research facility ledger is empty; generate candidates or run a "
            "bounded dry-run cycle first."
        )
    else:
        parts: list[str] = []
        if admitted:
            parts.append(f"{admitted} admitted candidate(s) ready to promote")
        if needs_review:
            parts.append(f"{needs_review} need review before promotion")
        if parts:
            message = "; ".join(parts) + "."
        elif returned_rows:
            message = (
                f"{returned_rows} candidate row(s) visible in this slice; select "
                "one to dry-run promotion."
            )
        else:
            message = (
                "Research facility has ledger rows but no admitted or "
                "needs-review candidates in the current counts."
            )
    return message


def _summarize_automation_workbench_message(
    *,
    total: int,
    page_returned: int,
    triage_ready: int,
    queued: int,
    blocked: int,
    filtered: bool,
) -> str:
    message = ""
    if page_returned == 0 and total == 0:
        message = (
            "No publication automation rows in the ledger; backfill or wait "
            "for publication drafts."
        )
    elif filtered and page_returned == 0:
        message = (
            "No publication automation rows match the current filters; widen "
            "review status or clear search."
        )
    elif triage_ready:
        if total:
            message = (
                f"{total} publication draft(s) in automation; {triage_ready} "
                "triage-ready for rewrite or finalization."
            )
        else:
            message = (
                f"{triage_ready} publication draft(s) triage-ready for rewrite or "
                "finalization in the current slice."
            )
    else:
        headline = total or page_returned
        if blocked:
            message = (
                f"{headline} publication draft(s) tracked; {blocked} blocked and "
                "need checklist or rewrite attention."
            )
        elif queued:
            message = (
                f"{headline} publication draft(s) in automation; {queued} queued "
                "for the next operator pass."
            )
        else:
            visible = page_returned or total
            message = (
                f"{visible} publication draft(s) in this slice; select a row to "
                "dry-run rewrite or finalization."
            )
    return message


def summarize_automation_workbench(
    *,
    counts: dict[str, int] | None,
    page_total: int = 0,
    page_returned: int = 0,
    review_status: str = "",
    search: str = "",
) -> str:
    counts = counts or {}
    total = _count_value(counts, "all") or page_total
    return _summarize_automation_workbench_message(
        total=total,
        page_returned=page_returned,
        triage_ready=_count_value(counts, "triage_ready"),
        queued=_count_value(counts, "queued"),
        blocked=_count_value(counts, "blocked"),
        filtered=bool(_text(review_status) or _text(search)),
    )


def summarize_paper_row(row: dict[str, Any]) -> dict[str, Any]:
    summary = with_operator_stage(
        {
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
            "artifact_paths_present": _paper_artifact_flags(row),
            "links": paper_links(row),
        }
    )
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
    return _drop_related_artifact_paths(
        with_operator_stage(
            {
                "run_id": run_id,
                "project_id": project_id,
                "project_name": row.get("project_name", ""),
                "project_dir": row.get("project_dir", ""),
                "session_id": row.get("session_id", ""),
                "related_paper_id": row.get("related_paper_id", ""),
                "related_paper_status": row.get("related_paper_status", ""),
                "related_review_status": row.get("related_review_status", ""),
                "related_finalization_package_path": row.get(
                    "related_finalization_package_path", ""
                ),
                "related_draft_markdown_path": row.get(
                    "related_draft_markdown_path", ""
                ),
                "related_evidence_bundle_path": row.get(
                    "related_evidence_bundle_path", ""
                ),
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
                    "project": f"/control/api/v1/projects/{project_id}"
                    if project_id
                    else "",
                    "legacy_run": f"/control/api/runs/{run_id}" if run_id else "",
                },
            }
        )
    )


def _list_projection(
    row: dict[str, Any],
    *,
    drop_keys: frozenset[str] = frozenset(),
    drop_prefixes: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key not in drop_keys
        and not any(key.startswith(prefix) for prefix in drop_prefixes)
    }


_QUEUE_LIST_DROP_KEYS = frozenset(
    {
        "project_dir",
        "current_session_id",
        "last_run_state",
        "related_paper_id",
        "related_paper_status",
        "related_review_status",
        "related_finalization_package_path",
        "related_draft_markdown_path",
        "related_evidence_bundle_path",
        "related_claim_ledger_path",
        "related_manifest_path",
        "related_corpus_imported",
        "related_corpus_import_id",
        "related_artifact_slug",
        "related_source_record_fingerprint",
    }
)
_PROJECT_LIST_DROP_KEYS = frozenset(
    {
        "origin_idea_status",
        "related_paper_id",
        "related_paper_status",
    }
)
_RUN_LIST_DROP_KEYS = frozenset(
    {
        "project_dir",
        "session_id",
        "related_paper_id",
        "related_paper_status",
        "related_review_status",
        "related_finalization_package_path",
        "related_draft_markdown_path",
        "related_evidence_bundle_path",
        "related_claim_ledger_path",
        "related_manifest_path",
    }
)


def summarize_queue_list_row(row: dict[str, Any]) -> dict[str, Any]:
    return _list_projection(
        summarize_queue_row(row),
        drop_keys=_QUEUE_LIST_DROP_KEYS,
        drop_prefixes=("followup_",),
    )


def summarize_project_list_row(row: dict[str, Any]) -> dict[str, Any]:
    return _list_projection(
        summarize_project_row(row), drop_keys=_PROJECT_LIST_DROP_KEYS
    )


def summarize_run_list_row(row: dict[str, Any]) -> dict[str, Any]:
    return _list_projection(summarize_run_row(row), drop_keys=_RUN_LIST_DROP_KEYS)


def summarize_paper_list_row(row: dict[str, Any]) -> dict[str, Any]:
    return summarize_paper_row(row)


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


def _paper_typed_lifecycle_key(row: dict[str, Any], paper_id: str) -> str:
    run_id = _text(row.get("run_id") or row.get("current_run_id"))
    paper_type = _text(row.get("paper_type")) or "arxiv_draft"
    project_id = _text(row.get("project_id"))
    if project_id and run_id:
        return f"paper_identity:{project_id}:{run_id}:{paper_type}"
    return f"paper:{paper_id}"


def _queue_typed_lifecycle_key(row: dict[str, Any], project_id: str) -> str:
    if not bool(row.get("operator_attention")):
        return f"queue:{project_id}"
    run_id = _text(row.get("run_id") or row.get("current_run_id"))
    status = _text(
        row.get("status")
        or row.get("queue_status")
        or row.get("last_run_state")
        or row.get("state")
        or row.get("gate_state")
    )
    return f"queue_attention:{project_id}:{run_id or status}"


def _typed_lifecycle_key(row: dict[str, Any]) -> str:
    paper_id = _text(row.get("paper_id"))
    if paper_id:
        return _paper_typed_lifecycle_key(row, paper_id)
    project_id = _text(row.get("project_id"))
    if project_id:
        return _queue_typed_lifecycle_key(row, project_id)
    run_id = _text(row.get("run_id") or row.get("current_run_id"))
    return f"run:{run_id}" if run_id else ""


def _operator_row_is_active(row: dict[str, Any]) -> bool:
    status = _text(row.get("status") or row.get("queue_status"))
    state = _text(
        row.get("last_run_state") or row.get("state") or row.get("gate_state")
    )
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


def _paper_run_keys_from_staged(
    staged_rows: Sequence[dict[str, Any]],
) -> set[tuple[str, str]]:
    return {
        (_text(row.get("project_id")), _text(row.get("run_id")))
        for row in staged_rows
        if _text(row.get("paper_id"))
        and _text(row.get("project_id"))
        and _text(row.get("run_id"))
    }


def _paper_ids_from_staged(staged_rows: Sequence[dict[str, Any]]) -> set[str]:
    return {
        _text(row.get("paper_id")) for row in staged_rows if _text(row.get("paper_id"))
    }


def _staged_queue_row_for_reconcile(
    staged: dict[str, Any],
    *,
    paper_ids: set[str],
) -> tuple[dict[str, Any], str]:
    related_paper_id = _text(staged.get("related_paper_id"))
    is_queue_row = not _text(staged.get("paper_id"))
    if (
        is_queue_row
        and _has_related_paper_projection(staged)
        and (not related_paper_id or related_paper_id not in paper_ids)
    ):
        staged = _strip_related_paper_projection(staged)
        related_paper_id = ""
    return staged, related_paper_id


class _QueueReconcileFlags(NamedTuple):
    related_paper_id: str
    paper_ids: set[str]
    paper_run_keys: set[tuple[str, str]]
    is_queue_row: bool
    is_active_row: bool
    needs_attention: bool


def _reconciled_queue_row_should_drop(
    staged: dict[str, Any], flags: _QueueReconcileFlags
) -> bool:
    if (
        flags.is_queue_row
        and flags.related_paper_id
        and flags.related_paper_id in flags.paper_ids
        and not flags.is_active_row
        and not flags.needs_attention
    ):
        return True
    return bool(
        flags.is_queue_row
        and not flags.is_active_row
        and not flags.needs_attention
        and _queue_is_superseded_by_paper(staged, flags.paper_run_keys)
    )


def _operator_row_precedence(row: dict[str, Any]) -> int:
    detail_stage = _text(row.get("operator_detail_stage"))
    lane = _text(row.get("operator_lane") or row.get("operator_stage"))
    return max(
        OPERATOR_STAGE_PRECEDENCE.get(detail_stage, 0),
        OPERATOR_LANE_PRECEDENCE.get(lane, 0),
    )


def _reconciled_published_lane_merge(
    current: dict[str, Any] | None,
    staged: dict[str, Any],
) -> str | None:
    lane = _text(staged.get("operator_lane") or staged.get("operator_stage"))
    current_lane = _text(
        (current or {}).get("operator_lane") or (current or {}).get("operator_stage")
    )
    if (
        current is not None
        and current_lane == OperatorLane.PUBLISHED.value
        and lane != OperatorLane.NEEDS_OPERATOR.value
    ):
        return "skip"
    if (
        current is not None
        and lane == OperatorLane.PUBLISHED.value
        and current_lane != OperatorLane.NEEDS_OPERATOR.value
    ):
        return "replace"
    return None


def _merge_reconciled_operator_key(
    by_key: dict[str, dict[str, Any]],
    key: str,
    staged: dict[str, Any],
) -> None:
    current = by_key.get(key)
    is_active_row = _operator_row_is_active(staged)
    current_is_active = _operator_row_is_active(current or {})
    if current is not None and current_is_active and not is_active_row:
        return
    if current is not None and is_active_row and not current_is_active:
        by_key[key] = staged
        return
    published_merge = _reconciled_published_lane_merge(current, staged)
    if published_merge == "skip":
        return
    if published_merge == "replace":
        by_key[key] = staged
        return
    if current is None or _operator_row_precedence(staged) > _operator_row_precedence(
        current or {}
    ):
        by_key[key] = staged


def _reconciled_operator_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    staged_rows = [with_operator_stage(row) for row in rows]
    paper_run_keys = _paper_run_keys_from_staged(staged_rows)
    paper_ids = _paper_ids_from_staged(staged_rows)
    by_key: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    for staged in staged_rows:
        staged, related_paper_id = _staged_queue_row_for_reconcile(
            staged, paper_ids=paper_ids
        )
        is_queue_row = not _text(staged.get("paper_id"))
        is_active_row = _operator_row_is_active(staged)
        needs_attention = bool(staged.get("operator_attention"))
        if _reconciled_queue_row_should_drop(
            staged,
            _QueueReconcileFlags(
                related_paper_id=related_paper_id,
                paper_ids=paper_ids,
                paper_run_keys=paper_run_keys,
                is_queue_row=is_queue_row,
                is_active_row=is_active_row,
                needs_attention=needs_attention,
            ),
        ):
            continue
        key = _typed_lifecycle_key(staged)
        if not key:
            anonymous.append(staged)
            continue
        _merge_reconciled_operator_key(by_key, key, staged)
    return [*by_key.values(), *anonymous]


def operator_detail_counts_from_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in _reconciled_operator_rows(rows):
        detail_stage = (
            _text(row.get("operator_detail_stage"))
            or operator_stage_for_record(row)["operator_detail_stage"]
        )
        counts[detail_stage] = counts.get(detail_stage, 0) + 1
    return counts


def operator_counts_from_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    reconciled = _reconciled_operator_rows(rows)
    for row in reconciled:
        lane = (
            _text(row.get("operator_lane") or row.get("operator_stage"))
            or operator_stage_for_record(row)["operator_lane"]
        )
        counts[lane] = counts.get(lane, 0) + 1
    counts["needs_attention"] = sum(
        1
        for row in reconciled
        if bool(
            row.get("operator_attention")
            or operator_stage_for_record(row)["operator_attention"]
        )
    )
    counts[OperatorLane.READY_TO_PUBLISH.value] = counts.get(
        OperatorLane.READY_TO_PUBLISH.value, 0
    )
    counts["total_operator_items"] = len(reconciled)
    return counts


def blocked_attention_samples_from_rows(
    rows: list[dict[str, Any]], *, limit: int = 3
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for row in _reconciled_operator_rows(rows):
        stage = operator_stage_for_record(row)
        if not bool(row.get("operator_attention") or stage["operator_attention"]):
            continue
        samples.append(
            {
                "project_id": _text(row.get("project_id")),
                "project_name": _text(row.get("project_name") or row.get("title")),
                "status": _text(row.get("status")),
                "next_action_hint": _text(row.get("next_action_hint")),
                "current_run_id": _text(row.get("current_run_id") or row.get("run_id")),
                "operator_lane": _text(
                    row.get("operator_lane") or stage["operator_lane"]
                ),
                "operator_detail_stage": _text(
                    row.get("operator_detail_stage") or stage["operator_detail_stage"]
                ),
            }
        )
        if len(samples) >= limit:
            break
    return samples


def page_response(
    *,
    rows: list[dict[str, Any]],
    next_cursor: str | None,
    has_more: bool,
    page_size_value: int,
    cursor: str,
    filters: dict[str, Any],
) -> dict[str, Any]:
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


def _overview_batch_row_lists_valid(value: Mapping[str, Any]) -> bool:
    for rows_key in ("active_items", "raw_queue_rows", "raw_paper_rows"):
        rows = value.get(rows_key)
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            return False
    return True


def _valid_overview_batch(value: Any) -> Mapping[str, Any] | None:
    """Return a usable optimized overview batch or None to use canonical reads.

    The batched overview path is an optimization used by live adapters. It must
    not become a single malformed-response failure point for the operator
    dashboard; canonical read methods remain the source of truth fallback.
    """

    events_page = value.get("events_page") if isinstance(value, Mapping) else None
    if (
        isinstance(value, Mapping)
        and _OVERVIEW_BATCH_KEYS.issubset(value.keys())
        and isinstance(events_page, tuple)
        and len(events_page) == 3
        and _overview_batch_row_lists_valid(value)
        and isinstance(value.get("counts"), dict)
        and isinstance(value.get("paper_counts"), dict)
    ):
        return value
    return None


def _candidate_label(candidate: Mapping[str, Any] | None) -> str:
    if not candidate:
        return ""
    if not isinstance(candidate, Mapping):
        return ""
    for key in (
        "project_name",
        "paper_title",
        "followup_title",
        "title",
        "project_id",
        "paper_id",
    ):
        value = candidate.get(key)
        if value:
            return str(value)
    return ""


def _candidate_target(candidate: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(candidate, Mapping):
        return {}
    target: dict[str, str] = {}
    for key in ("project_id", "paper_id", "current_run_id", "run_id"):
        value = candidate.get(key)
        if value:
            target[key] = str(value)
    name = _candidate_label(candidate)
    if name:
        target["name"] = name
    return target


def _normalize_safe_count_default(default: Any) -> int:
    if isinstance(default, bool):
        parsed = 0
    elif isinstance(default, int):
        parsed = default
    else:
        try:
            parsed = int(default)
        except (TypeError, ValueError):
            parsed = 0
    if parsed < 0:
        return 0
    return parsed


def _clamp_non_negative_count(value: int) -> int:
    return value if value >= 0 else 0


def _parse_count_string(stripped: str) -> int | None:
    try:
        return int(stripped)
    except ValueError:
        try:
            return int(float(stripped))
        except (TypeError, ValueError):
            return None


def _coerce_safe_count_from_float(value: float) -> int | None:
    if math.isnan(value) or value in (float("inf"), float("-inf")):
        return None
    return int(value)


def _coerce_safe_count_from_string(value: str) -> int | None:
    stripped = value.strip()
    if not stripped:
        return None
    return _parse_count_string(stripped)


def _coerce_safe_count(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return _coerce_safe_count_from_float(value)
    if isinstance(value, str):
        return _coerce_safe_count_from_string(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_count(value: Any, default: int = 0) -> int:
    """Defensively coerce an arbitrary value into a non-negative count.

    The /control/dashboard overview is an operator surface and must fail closed
    on malformed projection inputs rather than crashing. This helper:

    - Returns ``default`` for ``None`` or empty/whitespace strings.
    - Rejects booleans explicitly. ``True`` and ``False`` are NOT counts even
      though Python treats ``bool`` as a subclass of ``int``.
    - Accepts real ints and numeric strings (including signed and whitespace
      padded decimals).
    - Returns ``default`` on any ``TypeError`` or ``ValueError`` raised during
      coercion (e.g. ``"bad"``, dicts, lists, NaN-like floats).
    - Clamps negative values to ``0`` so the projection never emits a card
      that says "-3 items waiting".

    The default itself is normalized to a non-negative int via the same rules
    so callers cannot accidentally smuggle a negative or non-numeric default
    into the projection.
    """

    default_int = _normalize_safe_count_default(default)
    parsed = _coerce_safe_count(value)
    if parsed is None:
        return default_int
    return _clamp_non_negative_count(parsed)


def _lane_label(lane: Mapping[str, Any]) -> str:
    machine = str(lane.get("machine_target") or "").strip()
    role = str(lane.get("worker_role") or "").strip().lower()
    lower_machine = machine.lower()
    if "cpu" in lower_machine or "cpu" in role:
        return "CPU lane"
    if "gb10" in lower_machine or "gpu" in role:
        return "GB10 lane"
    if machine:
        return f"{machine} lane"
    return "default lane"


def _open_lane_labels(worker_lanes: Sequence[Mapping[str, Any]] | None) -> list[str]:
    """Return human-readable labels for worker lanes that can dispatch right now.

    Used by ``top_operator_actions`` to make ``dispatch_next`` lane-aware.
    Returns an empty list when ``worker_lanes`` is ``None`` or no lane is open,
    which is the signal to suppress the dispatch_next card entirely.
    """

    if not worker_lanes:
        return []
    return [
        _lane_label(lane)
        for lane in worker_lanes
        if isinstance(lane, Mapping) and bool(lane.get("dispatch_available"))
    ]


def _flags_payload(flags: Mapping[str, Any] | Any | None) -> dict[str, Any]:
    if flags is None:
        return {}
    if isinstance(flags, Mapping):
        return dict(flags)
    dump = getattr(flags, "model_dump", None)
    if callable(dump):
        payload = dump(mode="json")
        return dict(payload) if isinstance(payload, Mapping) else {}
    return {}


_MOVEMENT_HARD_BLOCKER_KINDS = frozenset(
    {
        "maintenance_mode",
        "queue_paused",
        "no_matching_machine_target",
        "lane_queue_empty",
        "no_admitted_candidates",
        "lane_blocked",
        "lane_conflict_active",
        "evidence_missing",
        "paper_write_blocked",
    }
)
_MOVEMENT_ACTIONABLE_KINDS = frozenset({"dispatch_available", "followup_ready"})


def _movement_flag_blockers(flags: Mapping[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if flags.get("maintenance_mode"):
        blockers.append(
            {
                "kind": "maintenance_mode",
                "tone": "warn",
                "title": "Maintenance mode is on",
                "summary": "Automation is intentionally held until maintenance mode is cleared.",
                "action_label": "Resume queue",
                "action_hash": ACTION_HASH_OVERVIEW,
            }
        )
    if flags.get("queue_paused"):
        blockers.append(
            {
                "kind": "queue_paused",
                "tone": "warn",
                "title": "Queue is paused",
                "summary": "Queued work will not dispatch until the queue is resumed.",
                "action_label": "Resume queue",
                "action_hash": ACTION_HASH_OVERVIEW,
            }
        )
    return blockers


def _movement_lane_blocker_active(
    lane: Mapping[str, Any],
    *,
    label: str,
    active: Mapping[str, Any],
) -> dict[str, Any]:
    active_count = _safe_count(lane.get("active_count"))
    if active_count > 1:
        return {
            "kind": "lane_conflict_active",
            "lane": label,
            "tone": "warn",
            "title": f"{label} has duplicate active work",
            "summary": f"{label} reports {active_count} active runs, which violates the single-active-run lane invariant.",
            "action_label": "Open active work",
            "action_hash": "#queue:active",
        }
    return {
        "kind": "lane_active",
        "lane": label,
        "tone": "info",
        "title": f"{label} is running",
        "summary": f"{label} is occupied by {active.get('project_name') or active.get('project_id') or 'active work'}.",
        "action_label": "Open active work",
        "action_hash": "#queue:active",
    }


def _movement_lane_blocker_idle(
    lane: Mapping[str, Any],
    *,
    label: str,
    feed: Mapping[str, Any],
    feed_action: str,
    queued_count: int,
) -> dict[str, Any] | None:
    if queued_count and not bool(lane.get("configured", True)):
        return {
            "kind": "no_matching_machine_target",
            "lane": label,
            "tone": "warn",
            "title": f"{label} is not configured",
            "summary": "Queued work targets a worker lane that is not in the configured worker-target set.",
            "action_label": "Open queue",
            "action_hash": ACTION_HASH_QUEUE_QUEUED,
        }
    if feed_action == "promote_candidate":
        return {
            "kind": "lane_queue_empty",
            "lane": label,
            "tone": "warn",
            "title": f"{label} needs a queued candidate",
            "summary": str(
                feed.get("operator_summary")
                or f"{label} has admitted candidates that should be promoted."
            ),
            "action_label": "Feed idle lane",
            "action_hash": ACTION_HASH_RESEARCH,
        }
    if feed_action == "generate_candidate":
        return {
            "kind": "no_admitted_candidates",
            "lane": label,
            "tone": "warn",
            "title": f"{label} has no admitted candidate",
            "summary": str(
                feed.get("operator_summary")
                or f"{label} needs generated/admitted work before dispatch can happen."
            ),
            "action_label": "Open research facility",
            "action_hash": ACTION_HASH_RESEARCH,
        }
    if str(lane.get("dispatch_blocker") or ""):
        return {
            "kind": "lane_blocked",
            "lane": label,
            "tone": "warn",
            "title": f"{label} cannot dispatch",
            "summary": str(lane.get("dispatch_blocker")),
            "action_label": "Open queue",
            "action_hash": ACTION_HASH_QUEUE_QUEUED,
        }
    return None


def _movement_lane_blocker(
    lane: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, Any] | None:
    if bool(lane.get("dispatch_available")):
        return {
            "kind": "dispatch_available",
            "lane": label,
            "tone": "good",
            "title": f"{label} can dispatch",
            "summary": f"{label} can dispatch queued work.",
            "action_label": "Dispatch this lane",
            "action_hash": ACTION_HASH_QUEUE_QUEUED,
        }
    if str(lane.get("status") or "") == "active":
        active = lane.get("active_item") or {}
        return _movement_lane_blocker_active(
            lane, label=label, active=active if isinstance(active, Mapping) else {}
        )
    feed = lane.get("feed_pressure") or {}
    feed_mapping = feed if isinstance(feed, Mapping) else {}
    return _movement_lane_blocker_idle(
        lane,
        label=label,
        feed=feed_mapping,
        feed_action=str(feed_mapping.get("next_autopilot_action") or ""),
        queued_count=_safe_count(lane.get("queued_count")),
    )


def _movement_pipeline_blockers(
    *,
    paper_pipeline: Mapping[str, Any],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    gate_attention = _safe_count(paper_pipeline.get("paper_write_blocked"))
    if gate_attention:
        blockers.append(
            {
                "kind": "paper_write_blocked",
                "tone": "warn",
                "title": "Paper writing needs attention",
                "summary": f"{gate_attention} positive paper candidate{'s' if gate_attention != 1 else ''} could not be surfaced for writing.",
                "action_label": "Open paper details",
                "action_hash": "#papers",
            }
        )
    finalize_needed = _safe_count(paper_pipeline.get("finalize_needed"))
    if finalize_needed:
        blockers.append(
            {
                "kind": "evidence_missing",
                "tone": "warn",
                "title": "Publication evidence/package is incomplete",
                "summary": f"{finalize_needed} publication draft{'s' if finalize_needed != 1 else ''} still need automated finalization/evidence packaging.",
                "action_label": "Open automation",
                "action_hash": "#automation",
            }
        )
    return blockers


def _movement_status_from_blockers(
    blockers: Sequence[Mapping[str, Any]],
) -> tuple[str, str]:
    primary = blockers[0] if blockers else None
    actionable = next(
        (item for item in blockers if item["kind"] in _MOVEMENT_ACTIONABLE_KINDS),
        None,
    )
    hard_blocker = next(
        (item for item in blockers if item["kind"] in _MOVEMENT_HARD_BLOCKER_KINDS),
        None,
    )
    active_lanes = [item for item in blockers if item["kind"] == "lane_active"]
    if actionable:
        return "actionable", str(actionable["summary"])
    if hard_blocker:
        return "blocked", str(hard_blocker["summary"])
    if active_lanes:
        if len(active_lanes) > 1:
            reason = "Configured worker lanes are occupied by active runs; this is normal while queued backlog waits."
        else:
            reason = (
                str(active_lanes[0]["summary"])
                + " This is normal active work, not a health blocker."
            )
        return "ready", reason
    reason = (
        "No dispatch or automation health blocker is preventing unattended operation."
        if primary
        else "No deterministic blocker is preventing movement."
    )
    return "ready", reason


def _movement_status_and_reason(
    *,
    flags: Mapping[str, Any],
    blockers: Sequence[Mapping[str, Any]],
) -> tuple[str, str]:
    if flags.get("maintenance_mode"):
        return "blocked", "Maintenance mode is on."
    if flags.get("queue_paused"):
        return "blocked", "Queue is paused."
    return _movement_status_from_blockers(blockers)


def movement_diagnosis(
    *,
    flags: Mapping[str, Any] | None,
    worker_lanes: Sequence[Mapping[str, Any]] | None,
    paper_pipeline: Mapping[str, Any],
) -> dict[str, Any]:
    """Explain, deterministically, why work is or is not moving.

    This is an operator read model. The frontend renders it; it does not infer
    truth from loose queue counts.
    """

    flags = _flags_payload(flags)
    lanes = [lane for lane in (worker_lanes or []) if isinstance(lane, Mapping)]
    blockers = _movement_flag_blockers(flags)
    global_dispatch_blocked = bool(
        flags.get("maintenance_mode") or flags.get("queue_paused")
    )
    for lane in lanes:
        lane_blocker = _movement_lane_blocker(lane, label=_lane_label(lane))
        if lane_blocker is None:
            continue
        if (
            global_dispatch_blocked
            and lane_blocker.get("kind") in _MOVEMENT_ACTIONABLE_KINDS
        ):
            continue
        blockers.append(lane_blocker)
    blockers.extend(_movement_pipeline_blockers(paper_pipeline=paper_pipeline))
    status, primary_reason = _movement_status_and_reason(flags=flags, blockers=blockers)
    return {
        "status": status,
        "primary_reason": primary_reason,
        "blockers": blockers[:8],
    }


def _top_action_needs_attention(
    *,
    operator_counts: Mapping[str, Any],
    counts: Mapping[str, Any],
) -> dict[str, Any] | None:
    needs_attention_value = operator_counts.get("needs_attention")
    needs_attention = _safe_count(needs_attention_value)
    if needs_attention == 0 and needs_attention_value in (None, ""):
        needs_attention = _safe_count(counts.get("blocked"))
    if needs_attention <= 0:
        return None
    return {
        "kind": "needs_attention",
        "tone": "warn",
        "title": "Resolve operator attention items",
        "summary": (
            f"{needs_attention} item{'s' if needs_attention != 1 else ''} flagged for operator action."
        ),
        "count": needs_attention,
        "action_label": "Open attention queue",
        "action_hash": "#queue:blocked",
    }


def _top_action_write_paper(
    paper_pipeline: Mapping[str, Any],
) -> dict[str, Any] | None:
    write_needed = _safe_count(paper_pipeline.get("write_needed"))
    if write_needed <= 0:
        return None
    next_write = paper_pipeline.get("next_write_candidate") or {}
    next_label = _candidate_label(next_write) or "next paper-ready run"
    return {
        "kind": "write_paper",
        "tone": "warn",
        "title": "Draft the next paper",
        "summary": (
            f"{write_needed} paper-ready run{'s' if write_needed != 1 else ''} need a first draft. "
            f"Next: {next_label}."
        ),
        "count": write_needed,
        "action_label": "Open draft lane",
        "action_hash": "#papers?status=publication_draft",
        "target": _candidate_target(next_write) or None,
    }


def _top_action_finalize_paper(
    paper_pipeline: Mapping[str, Any],
) -> dict[str, Any] | None:
    finalize_needed = _safe_count(paper_pipeline.get("finalize_needed"))
    if finalize_needed <= 0:
        return None
    return {
        "kind": "finalize_paper",
        "tone": "warn",
        "title": "Finalize publication drafts",
        "summary": (
            f"{finalize_needed} publication draft{'s' if finalize_needed != 1 else ''} "
            "missing automated finalization package."
        ),
        "count": finalize_needed,
        "action_label": "Open automation queue",
        "action_hash": "#automation",
    }


def _top_action_publish_paper(
    paper_pipeline: Mapping[str, Any],
) -> dict[str, Any] | None:
    publish_ready = _safe_count(paper_pipeline.get("publish_ready"))
    if publish_ready <= 0:
        return None
    next_publish = paper_pipeline.get("next_publish_candidate") or {}
    next_label = _candidate_label(next_publish) or "the next finalized draft"
    return {
        "kind": "publish_paper",
        "tone": "warn",
        "title": "Import finalized drafts",
        "summary": (
            f"{publish_ready} finalized draft{'s' if publish_ready != 1 else ''} missing a "
            f"corpus-import ledger row. Next: {next_label}."
        ),
        "count": publish_ready,
        "action_label": "Open corpus import",
        "action_hash": "#corpus",
        "target": _candidate_target(next_publish) or None,
    }


def _top_action_investigate_followup(
    investigation_pipeline: Mapping[str, Any],
) -> dict[str, Any] | None:
    followup_ready = _safe_count(investigation_pipeline.get("ranked_followup_ready"))
    if followup_ready <= 0:
        return None
    next_followup = (
        investigation_pipeline.get("next_ranked_followup_candidate")
        or investigation_pipeline.get("next_followup_candidate")
        or {}
    )
    next_label = _candidate_label(next_followup) or "the top ranked candidate"
    return {
        "kind": "investigate_followup",
        "tone": "info",
        "title": "Queue a follow-up investigation",
        "summary": (
            f"{followup_ready} ranked follow-up{'s' if followup_ready != 1 else ''} ready for a bounded "
            f"adjacent investigation. Next: {next_label}."
        ),
        "count": followup_ready,
        "action_label": "Queue follow-up",
        "action_hash": ACTION_HASH_RESEARCH,
        "target": _candidate_target(next_followup) or None,
    }


def _top_action_dispatch_next(
    *,
    worker_lanes: Sequence[Mapping[str, Any]] | None,
    candidates: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    open_lanes = _open_lane_labels(worker_lanes) if not candidates else []
    if not open_lanes:
        return None
    lane_summary = ", ".join(open_lanes)
    queued_for_lanes = 0
    for lane in worker_lanes or ():
        if isinstance(lane, Mapping) and bool(lane.get("dispatch_available")):
            queued_for_lanes += _safe_count(lane.get("queued_count"))
    return {
        "kind": "dispatch_next",
        "tone": "info",
        "title": "Dispatch the next queued item",
        "summary": (
            f"{lane_summary} {'is' if len(open_lanes) == 1 else 'are'} idle with "
            f"{queued_for_lanes} queued candidate{'s' if queued_for_lanes != 1 else ''} "
            "ready to dispatch."
        ),
        "count": queued_for_lanes,
        "action_label": "Open ready queue",
        "action_hash": ACTION_HASH_QUEUE_QUEUED,
    }


def top_operator_actions(
    *,
    operator_counts: Mapping[str, Any],
    paper_pipeline: Mapping[str, Any],
    investigation_pipeline: Mapping[str, Any],
    counts: Mapping[str, Any],
    worker_lanes: Sequence[Mapping[str, Any]] | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Bounded ranked list of the top operator actions.

    The list is intentionally small. Each item is a deterministic projection of
    fields already present in the overview response; no extra store reads.
    The returned list is empty when nothing actionable is pending so callers
    can render a clean "all clear" state.

    Counts are coerced through ``_safe_count`` so malformed upstream values
    (booleans, junk strings, negatives) degrade to "no ranked action" instead
    of crashing the overview projection.

    The ``dispatch_next`` action is lane-aware: it is only emitted when
    ``worker_lanes`` is provided AND at least one lane reports
    ``dispatch_available`` truthy. Aggregate ``counts.active`` /
    ``counts.queued`` are NEVER used to imply lane dispatch truth, so the CPU
    lane being busy does not suppress dispatch on an idle GB10 lane and vice
    versa.
    """

    safe_limit = _safe_count(limit, default=3)
    if safe_limit > 5:
        safe_limit = 5
    candidates: list[dict[str, Any]] = []
    for action in (
        _top_action_needs_attention(operator_counts=operator_counts, counts=counts),
        _top_action_write_paper(paper_pipeline),
        _top_action_finalize_paper(paper_pipeline),
        _top_action_publish_paper(paper_pipeline),
        _top_action_investigate_followup(investigation_pipeline),
        _top_action_dispatch_next(worker_lanes=worker_lanes, candidates=candidates),
    ):
        if action is not None:
            candidates.append(action)

    ranked = candidates[:safe_limit]
    for index, item in enumerate(ranked, start=1):
        item["priority"] = index
    return ranked


_FEED_ACTIONS = frozenset({"generate_candidate", "promote_candidate"})


def _primary_action_for_blocked_movement(
    movement: Mapping[str, Any],
) -> dict[str, Any] | None:
    blockers = movement.get("blockers") or []
    if not blockers:
        return None
    primary = blockers[0] if isinstance(blockers[0], Mapping) else {}
    return {
        "kind": "open_blocker",
        "tone": primary.get("tone", "warn"),
        "title": str(primary.get("title") or "Resolve blocker"),
        "summary": str(primary.get("summary") or movement.get("primary_reason") or ""),
        "action_label": str(primary.get("action_label") or "Open details"),
        "action_hash": str(primary.get("action_hash") or ACTION_HASH_OVERVIEW),
        "blocker_kind": primary.get("kind"),
        "lane": primary.get("lane"),
    }


def _primary_action_for_dispatch_lane(
    lane: Mapping[str, Any],
) -> dict[str, Any]:
    label = _lane_label(lane)
    next_candidate = lane.get("next_candidate") or {}
    next_label = _candidate_label(next_candidate) or "queued work"
    project_id = str(next_candidate.get("project_id") or "").strip()
    payload: dict[str, Any] = {
        "kind": "dispatch_next",
        "tone": "info",
        "title": f"Dispatch {label}",
        "summary": f"{label} is idle with queued work ready to dispatch. Next: {next_label}.",
        "action_label": "Check dispatch",
        "action_hash": ACTION_HASH_QUEUE_QUEUED,
        "lane": label,
        "machine_target": lane.get("machine_target"),
    }
    if project_id:
        payload["project_id"] = project_id
        payload["target"] = _candidate_target(next_candidate) or {
            "project_id": project_id
        }
    return payload


def _primary_action_for_feed_lane(lane: Mapping[str, Any]) -> dict[str, Any]:
    feed = lane.get("feed_pressure") or {}
    feed_action = str(feed.get("next_autopilot_action") or "")
    label = _lane_label(lane)
    return {
        "kind": "feed_lanes",
        "tone": "warn",
        "title": f"Feed {label}",
        "summary": str(
            feed.get("operator_summary")
            or f"{label} needs backlog before dispatch can happen."
        ),
        "action_label": "Feed idle lanes",
        "action_hash": ACTION_HASH_RESEARCH,
        "lane": label,
        "machine_target": lane.get("machine_target"),
        "feed_action": feed_action,
    }


def _primary_action_for_open_dispatch(
    lanes: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    for lane in lanes:
        if bool(lane.get("dispatch_available")):
            return _primary_action_for_dispatch_lane(lane)
    return None


def _primary_action_for_feed_lanes(
    lanes: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    for lane in lanes:
        feed_action = str(
            (lane.get("feed_pressure") or {}).get("next_autopilot_action") or ""
        )
        if feed_action in _FEED_ACTIONS:
            return _primary_action_for_feed_lane(lane)
    return None


def primary_operator_action(
    *,
    worker_lanes: Sequence[Mapping[str, Any]] | None,
    movement: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Single decisive operator CTA for the command center.

    Priority (after frontend readiness gating):
    1. open the primary movement blocker when status is blocked;
    2. dispatch the first lane that can dispatch;
    3. feed the first lane that needs backlog.

    Blocked movement can coexist with per-lane ``dispatch_available`` because lane
    capacity ignores global pause flags; the primary CTA must still honor pause/
    maintenance blockers before suggesting dispatch.
    """

    lanes = [lane for lane in (worker_lanes or []) if isinstance(lane, Mapping)]
    if str(movement.get("status") or "") == "blocked":
        blocked = _primary_action_for_blocked_movement(movement)
        if blocked is not None:
            return blocked
    dispatch = _primary_action_for_open_dispatch(lanes)
    if dispatch is not None:
        return dispatch
    return _primary_action_for_feed_lanes(lanes)


def _try_overview_batch(
    store: ControlPlaneStore,
    *,
    active_limit: int,
    event_limit: int,
) -> Mapping[str, Any] | None:
    batched_reader = getattr(store, "overview_read_model_parts", None)
    if not callable(batched_reader):
        return None
    return _valid_overview_batch(
        batched_reader(active_limit=active_limit, event_limit=event_limit)
    )


def _overview_row_sources_from_batch(
    batched_parts: Mapping[str, Any],
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    Any,
    list[Any],
    list[Any],
    Mapping[str, Any],
]:
    return (
        batched_parts["counts"],
        batched_parts["paper_counts"],
        [summarize_queue_row(row) for row in batched_parts["active_items"]],
        batched_parts["next_candidate"],
        batched_parts["raw_queue_rows"],
        batched_parts["raw_paper_rows"],
        batched_parts,
    )


def _overview_row_sources_canonical(
    store: ControlPlaneStore,
    *,
    active_limit: int,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    Any,
    list[Any],
    list[Any],
    None,
]:
    return (
        store.queue_counts_sql(),
        store.paper_counts_sql(),
        [
            summarize_queue_row(row)
            for row in store.active_items_sql(limit=active_limit)
        ],
        store.next_candidate_sql(),
        store.operator_queue_rows_sql(),
        store.operator_paper_rows_sql(),
        None,
    )


def _overview_row_sources(
    store: ControlPlaneStore,
    *,
    active_limit: int,
    event_limit: int,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    Any,
    list[Any],
    list[Any],
    Mapping[str, Any] | None,
]:
    batched_parts = _try_overview_batch(
        store, active_limit=active_limit, event_limit=event_limit
    )
    if batched_parts is not None:
        return _overview_row_sources_from_batch(batched_parts)
    return _overview_row_sources_canonical(store, active_limit=active_limit)


def _paper_gate_missing_evidence_reason(
    candidate: Mapping[str, Any], *, gate_reason: str
) -> str:
    required_evidence = _listish(candidate.get("followup_required_evidence"))
    if required_evidence:
        return required_evidence[0]
    if _text(candidate.get("recommended_next_action")):
        return _text(candidate.get("recommended_next_action"))
    return gate_reason


def _paper_gate_archive_class(
    candidate: Mapping[str, Any], gate: Mapping[str, Any] | None
) -> str:
    reason = _text((gate or {}).get("reason"))
    if reason == "bounded follow-up required before paper writing":
        return "bounded_followup_required"
    state = _text(candidate.get("decision_gate_state"))
    if state in {"missing", "malformed", "unknown"}:
        return f"decision_{state}"
    if state == "negative" and _research_outcome(dict(candidate)) == "useful_signal":
        return "strict_gate_useful_signal_archive"
    if state:
        return f"decision_{state}"
    return "decision_missing"


def _gated_write_candidates(
    raw_write_candidates: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    write_candidates: list[dict[str, Any]] = []
    gate_rejected: list[dict[str, Any]] = []
    for candidate in raw_write_candidates:
        candidate_dict = dict(candidate)
        artifact_gate = _paper_draft_gate_for_row(candidate)
        row_gate = _paper_draft_gate_from_row_decision(candidate_dict)
        gate = (
            artifact_gate
            if artifact_gate
            and _text(artifact_gate.get("reason"))
            != MISSING_PROJECT_DECISION_ARTIFACT_REASON
            else row_gate or artifact_gate
        )
        if gate is None or not bool(gate.get("eligible")):
            gate_reason = _text(
                (gate or {}).get("reason", MISSING_PROJECT_DECISION_ARTIFACT_REASON)
            )
            gate_rejected.append(
                {
                    "project_id": candidate.get("project_id", ""),
                    "project_name": candidate.get("project_name", ""),
                    "run_id": candidate.get("current_run_id")
                    or candidate.get("run_id")
                    or "",
                    "decision_summary": _decision_summary_from_gate(gate),
                    "decision_gate_state": candidate.get("decision_gate_state", ""),
                    "gate_reason": gate_reason,
                    "archive_class": _paper_gate_archive_class(candidate, gate),
                    "hypothesis_status": _text(candidate.get("hypothesis_status")),
                    "evidence_strength": _text(candidate.get("evidence_strength")),
                    "research_outcome": _research_outcome(candidate_dict),
                    "bounded_paper_ready": _truthy(
                        candidate.get("bounded_paper_ready")
                    ),
                    "missing_evidence_reason": _paper_gate_missing_evidence_reason(
                        candidate, gate_reason=gate_reason
                    ),
                    "followup_required_evidence": _listish(
                        candidate.get("followup_required_evidence")
                    ),
                    "recommended_next_action": _text(
                        candidate.get("recommended_next_action")
                    ),
                }
            )
            continue
        write_candidates.append(candidate_dict)
    return write_candidates, gate_rejected


def _sync_write_paper_operator_counts(
    operator_counts: dict[str, int],
    operator_detail_counts: dict[str, int],
    write_candidates: Sequence[Mapping[str, Any]],
) -> None:
    # Operator counts are the high-level read model used by cards and alerts.
    # `write_paper` must stay decision-gated here too; otherwise completed
    # no-paper rows with missing/negative/unknown decisions leak into the
    # operator-facing lane even though `paper_pipeline.write_needed` is 0.
    operator_counts[OperatorLane.WRITE_PAPER.value] = len(write_candidates)
    if write_candidates:
        operator_detail_counts["run_complete_draft_needed"] = len(write_candidates)
    else:
        operator_detail_counts.pop("run_complete_draft_needed", None)


def _build_investigation_pipeline(
    reconciled_queue_rows: Sequence[Mapping[str, Any]],
    raw_reconciled_queue_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    followup_rows = [
        row
        for row in reconciled_queue_rows
        if _text(row.get("operator_detail_stage")) == "followup_candidate"
    ]
    followup_rows.sort(key=promising_followup_priority_key)
    ranked_ready_rows = [
        row
        for row in raw_reconciled_queue_rows
        if ranked_followup_readiness(row)["ready"]
    ]
    ranked_ready_rows.sort(key=promising_followup_priority_key)
    ranked_stale_rows = [
        row
        for row in raw_reconciled_queue_rows
        if promising_signal_bucket(row) == LIKELY_STALE_LOW_VALUE_ARCHIVE
        and _truthy(row.get("followup_recommended"))
        and not ranked_followup_readiness(row)["ready"]
    ]
    useful_signal_rows = [
        row
        for row in reconciled_queue_rows
        if _text(row.get("operator_lane")) == OperatorLane.USEFUL_SIGNAL.value
    ]
    compute_scale_blocked_rows = [
        row
        for row in reconciled_queue_rows
        if _text(row.get("operator_lane")) == OperatorLane.COMPUTE_SCALE_BLOCKED.value
    ]
    return {
        "followup_needed": len(followup_rows),
        "useful_signals": len(useful_signal_rows),
        "compute_scale_blocked": len(compute_scale_blocked_rows),
        "ranked_followup_ready": len(ranked_ready_rows),
        "ranked_top_external_researcher_candidates": sum(
            1
            for row in ranked_ready_rows
            if promising_signal_bucket(row) == TOP_EXTERNAL_RESEARCHER_CANDIDATES
        ),
        "ranked_compute_scale_blocked_ready": sum(
            1
            for row in ranked_ready_rows
            if promising_signal_bucket(row) == COMPUTE_SCALE_BLOCKED
        ),
        "ranked_followup_recommended_ready": sum(
            1
            for row in ranked_ready_rows
            if promising_signal_bucket(row) == FOLLOWUP_RECOMMENDED
        ),
        "ranked_likely_stale_low_value_archive": len(ranked_stale_rows),
        "max_followup_depth": MAX_FOLLOWUP_DEPTH,
        "next_followup_candidate": followup_rows[0] if followup_rows else None,
        "next_ranked_followup_candidate": ranked_ready_rows[0]
        if ranked_ready_rows
        else None,
        "next_useful_signal": useful_signal_rows[0] if useful_signal_rows else None,
        "next_compute_scale_blocked": compute_scale_blocked_rows[0]
        if compute_scale_blocked_rows
        else None,
        "definitions": {
            "followup_needed": "completed no-paper rows whose decision artifact recommends a bounded adjacent investigation",
            "ranked_followup_ready": "deterministically ranked promising signals with concrete bounded follow-up evidence eligible for automatic selection",
            "ranked_likely_stale_low_value_archive": "low-value or unsupported promising signals excluded from automatic follow-up unless explicitly selected",
            "useful_signals": "preserved completed runs with bounded local evidence; this is not an actionable queue and rows disappear from followup_needed after launch",
            "compute_scale_blocked": "preserved promising signals whose next evidence would exceed local compute or wall-clock limits",
            "max_followup_depth": "default safety cap for bounded research-campaign follow-up creation",
        },
    }


def _build_paper_pipeline(
    *,
    write_candidates: Sequence[Mapping[str, Any]],
    gate_rejected: Sequence[Mapping[str, Any]],
    raw_write_candidates: Sequence[Mapping[str, Any]],
    operator_counts: Mapping[str, int],
    operator_detail_counts: Mapping[str, int],
    paper_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    publish_candidates = [
        row
        for row in paper_rows
        if _text(row.get("operator_stage")) == "ready_to_publish"
    ]
    imported_candidates = [row for row in paper_rows if _paper_imported(row)]
    imported_candidates.sort(
        key=lambda row: _text(row.get("corpus_imported_at") or row.get("updated_at")),
        reverse=True,
    )
    publication_ready_total = operator_counts.get(
        OperatorLane.READY_TO_PUBLISH.value, 0
    ) + operator_counts.get(OperatorLane.PUBLISHED.value, 0)
    positive_rejected = sum(
        1
        for row in gate_rejected
        if _text(row.get("decision_gate_state")) == "positive"
    )
    gate_archive_count = len(gate_rejected)
    gate_archive_noun = "run" if gate_archive_count == 1 else "runs"
    gate_archive_verb = "is" if gate_archive_count == 1 else "are"
    archive_class_counts: dict[str, int] = {}
    missing_evidence_reason_counts: dict[str, int] = {}
    for row in gate_rejected:
        archive_class = _text(row.get("archive_class")) or "unknown"
        archive_class_counts[archive_class] = (
            archive_class_counts.get(archive_class, 0) + 1
        )
        reason = _text(row.get("missing_evidence_reason"))
        if reason:
            missing_evidence_reason_counts[reason] = (
                missing_evidence_reason_counts.get(reason, 0) + 1
            )
    top_missing_evidence_reason_counts = dict(
        sorted(
            missing_evidence_reason_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:20]
    )
    return {
        "write_needed": len(write_candidates),
        "raw_completed_no_paper_candidates": len(raw_write_candidates),
        "not_writable_by_decision_gate": gate_archive_count,
        "paper_gate_archive_count": gate_archive_count,
        "paper_gate_archive_summary": (
            f"{gate_archive_count} completed {gate_archive_noun} "
            f"{gate_archive_verb} intentionally not paper-writable."
        ),
        "paper_gate_archive_class_counts": archive_class_counts,
        "paper_gate_missing_evidence_reason_counts": top_missing_evidence_reason_counts,
        "paper_write_blocked": positive_rejected,
        "positive_rejected_by_decision_gate": positive_rejected,
        "gate_rejected_sample": gate_rejected[:10],
        "next_write_candidate": draft_candidate_payload(write_candidates[0])
        if write_candidates
        else None,
        "finalize_needed": operator_detail_counts.get("finalization_needed", 0),
        "publish_ready": operator_counts.get(OperatorLane.READY_TO_PUBLISH.value, 0),
        "next_publish_candidate": publish_candidates[0] if publish_candidates else None,
        "last_import_result": imported_candidates[0] if imported_candidates else None,
        "missing_from_corpus": operator_counts.get(
            OperatorLane.READY_TO_PUBLISH.value, 0
        ),
        "published_imported": operator_counts.get(OperatorLane.PUBLISHED.value, 0),
        "publication_ready_total": publication_ready_total,
        "definitions": {
            "write_needed": "completed runs with no live paper row that currently pass the paper-ready gate",
            "raw_completed_no_paper_candidates": "completed no-paper rows before checking local project decision artifacts",
            "not_writable_by_decision_gate": "completed no-paper rows rejected by local project decision artifacts as negative, ambiguous, or otherwise non-positive",
            "paper_gate_archive_count": "completed no-paper rows intentionally kept out of paper writing by the deterministic gate; this is an archive metric, not actionable paper work",
            "paper_write_blocked": "positive completed no-paper candidates that could not be surfaced as write_needed; non-zero requires investigation",
            "positive_rejected_by_decision_gate": "same as paper_write_blocked; explicit anomaly count for CLCA checks",
            "paper_gate_archive_class_counts": "strict gate classes for completed runs kept out of paper writing, e.g. bounded follow-up required versus generic negative archive",
            "paper_gate_missing_evidence_reason_counts": "dominant deterministic gate reasons that explain what evidence is missing before a no-paper run can become writable",
            "finalize_needed": "publication drafts missing automated finalization package",
            "publish_ready": "finalized publication drafts with required evidence paths that are missing a corpus-import ledger row",
            "missing_from_corpus": "same as publish_ready; actionable corpus import work only",
            "published_imported": "papers represented by the corpus-import ledger",
            "publication_ready_total": "finalized publication drafts with required evidence paths, whether already imported or still missing corpus import",
        },
    }


def _maturity_state_for_row(row: Mapping[str, Any]) -> str:
    state = _text(row.get("maturity_state"))
    if state in PAPER_READINESS_MATURITY_STATES:
        return state
    gate = _text(row.get("decision_gate_state"))
    if gate in {"missing", "malformed", "unknown"}:
        return "execution_complete"
    if gate == "negative":
        if _text(row.get("research_outcome")) == "useful_signal":
            return "pilot_signal"
        return "archive_no_paper"
    if gate == "positive":
        return "paper_candidate"
    return "execution_complete"


def _missing_evidence_reason(row: Mapping[str, Any]) -> str:
    for key in (
        "missing_evidence_reason",
        "dominant_missing_evidence_reason",
        "gate_reason",
        "blocked_reason",
    ):
        if value := _text(row.get(key)):
            return value
    required = row.get("followup_required_evidence")
    if isinstance(required, list) and required:
        return _text(required[0])
    return ""


def _latest_paper_age_days(paper_rows: Sequence[Mapping[str, Any]]) -> int | None:
    ages = [
        row_age_seconds(dict(row)) // 86400
        for row in paper_rows
        if row_age_seconds(dict(row)) is not None
    ]
    return min(ages) if ages else None


def _build_research_yield_panel(
    *,
    queue_rows: Sequence[Mapping[str, Any]],
    paper_rows: Sequence[Mapping[str, Any]],
    paper_pipeline: Mapping[str, Any] | None = None,
    investigation_pipeline: Mapping[str, Any] | None = None,
    paper_drought_days: int = 9,
) -> dict[str, Any]:
    maturity_counts = dict.fromkeys(sorted(PAPER_READINESS_MATURITY_STATES), 0)
    completed_rows = [
        row
        for row in queue_rows
        if _text(row.get("status")) == QueueStatus.COMPLETED.value
    ]
    for row in completed_rows:
        maturity_counts[_maturity_state_for_row(row)] += 1

    deepen_rows = [
        row
        for row in completed_rows
        if _maturity_state_for_row(row) == "deepen_required"
    ]
    deepen_rows.sort(
        key=lambda row: _text(row.get("updated_at") or row.get("updatedAt")),
        reverse=True,
    )
    reason_counts: dict[str, int] = {}
    for row in completed_rows:
        reason = _missing_evidence_reason(row)
        if reason:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    latest_age = _latest_paper_age_days(paper_rows)
    drought_warning = latest_age is None or latest_age >= paper_drought_days
    paper_recovery = _paper_drought_recovery_action(
        drought_warning=drought_warning,
        paper_pipeline=paper_pipeline or {},
        investigation_pipeline=investigation_pipeline or {},
        top_deepen_candidate=deepen_rows[0] if deepen_rows else None,
    )
    return {
        "latest_paper_age_days": latest_age,
        "paper_drought": {
            "warning": drought_warning,
            "threshold_days": paper_drought_days,
            "explanation": "Paper drought is a visibility warning, not an operational-readiness blocker.",
        },
        "paper_recovery": paper_recovery,
        "maturity_counts": maturity_counts,
        "top_deepen_required_candidate": (
            draft_candidate_payload(dict(deepen_rows[0])) if deepen_rows else None
        ),
        "dominant_missing_evidence_reason": max(
            reason_counts.items(), key=lambda item: item[1]
        )[0]
        if reason_counts
        else "",
        "definitions": {
            "maturity_counts": "completed runs grouped by paper-readiness evidence maturity",
            "top_deepen_required_candidate": "highest-priority completed run with a concrete evidence gap",
            "paper_drought": "visibility condition only; unattended automation readiness is evaluated separately",
            "paper_recovery": "deterministic next action when a paper drought is visible",
        },
    }


def _quality_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _quality_count(mapping: Mapping[str, Any], key: str) -> int:
    return _safe_count(mapping.get(key))


def _quality_value(mapping: Mapping[str, Any], key: str, default: Any = "") -> Any:
    return mapping.get(key, default)


def _quality_problem_action(detail: Mapping[str, Any]) -> str:
    target = _text(detail.get("title")) or _text(detail.get("project_id"))
    if target:
        return f"inspect {target} before resuming unattended automation"
    return "inspect this quality finding before resuming unattended automation"


def _quality_problem_detail(detail: Any) -> dict[str, Any] | None:
    if not isinstance(detail, Mapping):
        return None
    problem = _text(detail.get("problem"))
    severity = _text(detail.get("severity"))
    if not problem:
        return None
    return {
        "section": _text(detail.get("section")),
        "severity": severity,
        "problem": problem,
        "project_id": _text(detail.get("project_id")),
        "candidate_id": _text(detail.get("candidate_id")),
        "run_id": _text(detail.get("run_id")),
        "title": _text(detail.get("title")),
        "decision": _text(detail.get("decision")),
        "hypothesis_status": _text(detail.get("hypothesis_status")),
        "operator_action": _quality_problem_action(detail),
    }


def _quality_problem_details(
    quality: Mapping[str, Any], *, limit: int = 3
) -> list[dict[str, Any]]:
    details = []
    for detail in quality.get("problem_details") or []:
        normalized = _quality_problem_detail(detail)
        if normalized is not None and normalized["severity"] in {"blocked", "warning"}:
            details.append(normalized)
        if len(details) >= limit:
            break
    return details


def _quality_recommendations(
    quality: Mapping[str, Any], *, limit: int = 3
) -> list[str]:
    recommendations: list[str] = []
    for item in quality.get("recommendations") or []:
        text = _text(item)
        if text:
            recommendations.append(text)
        if len(recommendations) >= limit:
            break
    return recommendations


def _quality_recommendation_is_benign_for_review(text: str) -> bool:
    normalized = text.lower()
    return (
        "no critical quality-layer warnings" in normalized
        or "no quality-layer warnings" in normalized
    )


def _append_unique_text(items: list[str], value: Any, *, limit: int) -> None:
    text = _text(value)
    if text and text not in items and len(items) < limit:
        items.append(text)


def _operator_quality_recommendations(
    *,
    signal: Mapping[str, Any],
    post_prompt_warnings: Sequence[Mapping[str, Any]],
    raw_recommendations: Sequence[str],
    limit: int = 5,
) -> list[str]:
    recommendations: list[str] = []
    verdict = _text(signal.get("signal_verdict"))
    _append_unique_text(
        recommendations, signal.get("signal_operator_action"), limit=limit
    )
    for reason in signal.get("signal_reasons") or []:
        if isinstance(reason, Mapping):
            _append_unique_text(
                recommendations, reason.get("operator_action"), limit=limit
            )
    for detail in post_prompt_warnings:
        _append_unique_text(recommendations, detail.get("operator_action"), limit=limit)
    for item in raw_recommendations:
        if verdict != "defensible" and _quality_recommendation_is_benign_for_review(
            item
        ):
            continue
        _append_unique_text(recommendations, item, limit=limit)
    return recommendations


PROVIDER_RECOVERED_CLEAN_TICK_THRESHOLD = 3


def _quality_recent_malformed_provider_response(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    count = _safe_count(row.get("malformed_provider_response_count"))
    checked_at = _text(row.get("checked_at"))
    if count <= 0 or not checked_at:
        return None
    normalized = {
        "checked_at": checked_at,
        "recorded_at": _text(row.get("recorded_at")),
        "provider_model": _text(row.get("provider_model")),
        "malformed_provider_response_count": count,
        "generated_count": _safe_count(row.get("generated_count")),
        "promoted_count": _safe_count(row.get("promoted_count")),
        "dispatched_count": _safe_count(row.get("dispatched_count")),
        "operator_action": _text(row.get("operator_action"))
        or (
            "inspect provider-generation output for this tick before trusting "
            "new idea volume"
        ),
    }
    for key in ("trace_id", "run_cycle_id"):
        value = _text(row.get(key))
        if value:
            normalized[key] = value
    return normalized


def _quality_recent_malformed_provider_responses(
    monitor: Mapping[str, Any], *, limit: int = 3
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in monitor.get("recent_malformed_provider_responses") or []:
        normalized = _quality_recent_malformed_provider_response(row)
        if normalized is not None:
            rows.append(normalized)
        if len(rows) >= limit:
            break
    return rows


def _quality_provider_generation_tick(value: Any) -> dict[str, Any]:
    row = _quality_mapping(value)
    if not row:
        return {}
    normalized = {
        "checked_at": _text(row.get("checked_at")),
        "recorded_at": _text(row.get("recorded_at")),
        "provider_model": _text(row.get("provider_model")),
        "malformed_provider_response_count": _safe_count(
            row.get("malformed_provider_response_count")
        ),
        "generated_count": _safe_count(row.get("generated_count")),
        "promoted_count": _safe_count(row.get("promoted_count")),
        "dispatched_count": _safe_count(row.get("dispatched_count")),
        "status": _text(row.get("status")),
        "operator_action": _text(row.get("operator_action")),
    }
    if "initial_promotable_count" in row:
        normalized["initial_promotable_count"] = _safe_count(
            row.get("initial_promotable_count")
        )
    if "reason" in row:
        normalized["reason"] = _text(row.get("reason"))
    for key in ("trace_id", "run_cycle_id"):
        text_value = _text(row.get(key))
        if text_value:
            normalized[key] = text_value
    return normalized


def _quality_provider_generation_health(value: Any) -> dict[str, Any]:
    health = _quality_mapping(value)
    if not health:
        return {}
    malformed_count = _safe_count(health.get("malformed_provider_response_count"))
    consecutive_clean_ticks = _safe_count(health.get("consecutive_clean_ticks"))
    latest_tick = _quality_provider_generation_tick(health.get("latest_tick"))
    latest_status = _text(latest_tick.get("status"))
    latest_malformed_count = _safe_count(
        latest_tick.get("malformed_provider_response_count")
    )
    if malformed_count <= 0:
        malformed_status = "clean"
        active_malformed_warning = False
    elif (
        latest_status == "clean"
        and latest_malformed_count == 0
        and consecutive_clean_ticks >= PROVIDER_RECOVERED_CLEAN_TICK_THRESHOLD
    ):
        malformed_status = "recovered"
        active_malformed_warning = False
    else:
        malformed_status = "active"
        active_malformed_warning = True
    normalized = {
        "available": bool(health.get("available")),
        "rows_checked": _safe_count(health.get("rows_checked")),
        "malformed_provider_response_count": malformed_count,
        "malformed_provider_response_ticks": _safe_count(
            health.get("malformed_provider_response_ticks")
        ),
        "clean_tick_count": _safe_count(health.get("clean_tick_count")),
        "consecutive_clean_ticks": consecutive_clean_ticks,
        "malformed_history_status": malformed_status,
        "active_malformed_warning": active_malformed_warning,
        "last_checked_at": _text(health.get("last_checked_at")),
        "last_malformed_at": _text(health.get("last_malformed_at")),
        "malformed_provider_model_counts": _quality_model_counts(
            health.get("malformed_provider_model_counts")
        ),
        "latest_tick": latest_tick,
        "last_malformed_tick": _quality_provider_generation_tick(
            health.get("last_malformed_tick")
        ),
        "operator_action": _text(health.get("operator_action")),
    }
    for key in (
        "consecutive_zero_generated_ticks",
        "consecutive_zero_promoted_ticks",
    ):
        if key in health:
            normalized[key] = _safe_count(health.get(key))
    for key in ("latest_yield_status", "yield_operator_action"):
        if key in health:
            normalized[key] = _text(health.get(key))
    return normalized


def _quality_followup_evidence_row(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    return {
        "case_id": _text(row.get("case_id")),
        "case_type": _text(row.get("case_type")),
        "severity": _text(row.get("severity")),
        "title": _text(row.get("title")),
        "project_id": _text(row.get("project_id")),
        "project_name": _text(row.get("project_name")),
        "run_id": _text(row.get("run_id")),
        "followup_title": _text(row.get("followup_title")),
        "followup_depth": _safe_count(row.get("followup_depth")),
        "expected_behavior": _text(row.get("expected_behavior")),
    }


def _quality_followup_evidence_rows(
    value: Any, *, limit: int = 3
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in value or []:
        normalized = _quality_followup_evidence_row(row)
        if normalized is not None:
            rows.append(normalized)
        if len(rows) >= limit:
            break
    return rows


def _quality_followup_evidence(monitor: Mapping[str, Any]) -> dict[str, Any]:
    evidence = monitor.get("useful_adjacent_followup_evidence")
    if not isinstance(evidence, Mapping):
        return {"current": [], "previous": [], "delta": 0.0}
    return {
        "current": _quality_followup_evidence_rows(evidence.get("current")),
        "previous": _quality_followup_evidence_rows(evidence.get("previous")),
        "delta": _quality_value(evidence, "delta", 0.0),
    }


def _quality_model_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    counts: dict[str, int] = {}
    for key, count in value.items():
        model = _text(key)
        if model:
            counts[model] = _safe_count(count)
    return counts


def _quality_window_deltas(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    deltas: dict[str, float] = {}
    for key, delta in value.items():
        label = _text(key)
        if not label:
            continue
        try:
            deltas[label] = float(delta)
        except (TypeError, ValueError):
            deltas[label] = 0.0
    return deltas


def _quality_window_side(value: Any) -> dict[str, Any]:
    side = _quality_mapping(value)
    return {
        "candidate_count": _safe_count(side.get("candidate_count")),
        "decision_count": _safe_count(side.get("decision_count")),
        "admitted_rate": _quality_value(side, "admitted_rate", 0.0),
        "avg_total_score": _quality_value(side, "avg_total_score", 0.0),
        "status_counts": _quality_model_counts(side.get("status_counts")),
        "category_counts": _quality_model_counts(side.get("category_counts")),
        "generation_mode_counts": _quality_model_counts(
            side.get("generation_mode_counts")
        ),
        "eval_case_counts": _quality_model_counts(side.get("eval_case_counts")),
        "high_similarity_pair_count": _safe_count(
            side.get("high_similarity_pair_count")
        ),
    }


def _quality_window_comparison(value: Any) -> dict[str, Any]:
    comparison = _quality_mapping(value)
    if not comparison:
        return {}
    return {
        "cutoff": _text(comparison.get("cutoff")),
        "limit": _safe_count(comparison.get("limit")),
        "delta": _quality_window_deltas(comparison.get("delta")),
        "current": _quality_window_side(comparison.get("current")),
        "previous": _quality_window_side(comparison.get("previous")),
    }


def _quality_count_rows(
    value: Any, *, required_label: str, optional_label: str = "", limit: int = 10
) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    rows: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        label = _text(raw.get(required_label))
        if not label:
            continue
        row: dict[str, Any] = {
            required_label: label,
            "count": _safe_count(raw.get("count")),
        }
        if optional_label:
            row[optional_label] = _text(raw.get(optional_label))
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def _quality_problem_names(value: Any, *, limit: int = 5) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [_text(item) for item in value if _text(item)][:limit]


def _quality_candidate_sample(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": _text(row.get("candidate_id")),
        "title": _text(row.get("title")),
        "status": _text(row.get("status")),
        "deterministic_total_score": _quality_value(
            row, "deterministic_total_score", 0.0
        ),
        "contract_quality_score": _quality_value(row, "contract_quality_score", 0.0),
        "problems": _quality_problem_names(row.get("problems")),
    }


def _quality_candidate_samples(value: Any, *, limit: int = 3) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    samples: list[dict[str, Any]] = []
    for row in value:
        if isinstance(row, Mapping):
            sample = _quality_candidate_sample(row)
            if sample["candidate_id"]:
                samples.append(sample)
        if len(samples) >= limit:
            break
    return samples


def _quality_candidate_status_samples(value: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(value, Mapping):
        return {}
    samples: dict[str, list[dict[str, Any]]] = {}
    for status, rows in value.items():
        status_label = _text(status)
        if not status_label:
            continue
        status_samples = _quality_candidate_samples(rows)
        if status_samples:
            samples[status_label] = status_samples
    return samples


def _quality_decision_sample(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "project_id": _text(row.get("project_id")),
        "project_name": _text(row.get("project_name")),
        "run_id": _text(row.get("run_id")),
        "decision": _text(row.get("decision")),
        "hypothesis_status": _text(row.get("hypothesis_status")),
        "evidence_strength": _text(row.get("evidence_strength")),
        "research_outcome": _text(row.get("research_outcome")),
        "followup_title": _text(row.get("followup_title")),
        "problems": _quality_problem_names(row.get("problems")),
    }


def _quality_decision_samples(value: Any, *, limit: int = 3) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    samples: list[dict[str, Any]] = []
    for row in value:
        if isinstance(row, Mapping):
            sample = _quality_decision_sample(row)
            if sample["project_id"] or sample["run_id"]:
                samples.append(sample)
        if len(samples) >= limit:
            break
    return samples


def _quality_decision_outcome_sample(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    samples = _quality_decision_samples(raw.get("samples"))
    if not samples:
        return None
    return {
        "decision": _text(raw.get("decision")),
        "hypothesis_status": _text(raw.get("hypothesis_status")),
        "samples": samples,
    }


def _quality_decision_outcome_samples(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    outcomes: list[dict[str, Any]] = []
    for raw in value:
        if isinstance(raw, Mapping):
            outcome = _quality_decision_outcome_sample(raw)
            if outcome:
                outcomes.append(outcome)
    return outcomes


def _quality_floor_candidate_sample(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    candidate_id = _text(row.get("candidate_id"))
    title = _text(row.get("title"))
    if not candidate_id and not title:
        return None
    return {
        "candidate_id": candidate_id,
        "title": title,
        "status": _text(row.get("status")),
        "score": _quality_value(row, "score", 0.0),
        "problems": _quality_problem_names(row.get("problems")),
    }


def _quality_floor_decision_sample(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    project_id = _text(row.get("project_id"))
    run_id = _text(row.get("run_id"))
    title = _text(row.get("project_name"))
    if not project_id and not run_id and not title:
        return None
    return {
        "project_id": project_id,
        "project_name": title,
        "run_id": run_id,
        "decision": _text(row.get("decision")),
        "hypothesis_status": _text(row.get("hypothesis_status")),
        "score": _quality_value(row, "score", 0.0),
        "problems": _quality_problem_names(row.get("problems")),
    }


def _quality_floor_candidate_samples(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    rows: list[dict[str, Any]] = []
    for raw in value:
        sample = _quality_floor_candidate_sample(raw)
        if sample is not None:
            rows.append(sample)
        if len(rows) >= 3:
            break
    return rows


def _quality_floor_decision_samples(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    rows: list[dict[str, Any]] = []
    for raw in value:
        sample = _quality_floor_decision_sample(raw)
        if sample is not None:
            rows.append(sample)
        if len(rows) >= 3:
            break
    return rows


def _quality_floor(value: Any) -> dict[str, Any]:
    floor = _quality_mapping(value)
    if not floor:
        return {}
    return {
        "available": bool(floor.get("available")),
        "threshold": _quality_value(floor, "threshold", 0.0),
        "posture": _text(floor.get("posture")),
        "candidates_checked": _safe_count(floor.get("candidates_checked")),
        "decisions_checked": _safe_count(floor.get("decisions_checked")),
        "candidate_below_floor_count": _safe_count(
            floor.get("candidate_below_floor_count")
        ),
        "decision_below_floor_count": _safe_count(
            floor.get("decision_below_floor_count")
        ),
        "below_floor_count": _safe_count(floor.get("below_floor_count")),
        "candidate_samples": _quality_floor_candidate_samples(
            floor.get("candidate_samples")
        ),
        "decision_samples": _quality_floor_decision_samples(
            floor.get("decision_samples")
        ),
        "operator_action": _text(floor.get("operator_action")),
    }


def _quality_floor_summary(floor: Mapping[str, Any]) -> str:
    if not floor:
        return ""
    threshold = _quality_value(floor, "threshold", 0.0)
    below_floor_count = _safe_count(floor.get("below_floor_count"))
    if _text(floor.get("posture")) == "review_required" or below_floor_count > 0:
        return f"quality floor=review {below_floor_count} below {threshold:.2f}"
    checked = _safe_count(floor.get("candidates_checked")) + _safe_count(
        floor.get("decisions_checked")
    )
    return f"quality floor=satisfied ({checked} checked; threshold {threshold:.2f})"


def _quality_publication_posture_label(value: Any) -> str:
    return (_text(value) or "unknown").replace("_", " ")


def _quality_decision_posture_summary(posture: Mapping[str, Any]) -> str:
    if not posture or not bool(posture.get("available")):
        return ""
    label = _quality_publication_posture_label(posture.get("publication_posture"))
    useful = _safe_count(posture.get("useful_signal_count"))
    paper_ready = _safe_count(posture.get("bounded_paper_ready_count"))
    return (
        f"quality-window posture={label} ({useful} useful; {paper_ready} paper-ready)"
    )


def _quality_followup_readiness_summary(readiness: Mapping[str, Any]) -> str:
    if not readiness or not bool(readiness.get("available")):
        return ""
    ready = _safe_count(readiness.get("bounded_ready_count"))
    recommended = _safe_count(readiness.get("recommended_count"))
    return f"quality-window follow-ups={ready} ready / {recommended} recommended"


def _quality_bool(value: Any) -> bool:
    if value is True or value == 1:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _quality_decision_posture_sample(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    project_id = _text(row.get("project_id"))
    run_id = _text(row.get("run_id"))
    if not project_id and not run_id:
        return None
    return {
        "project_id": project_id,
        "project_name": _text(row.get("project_name")),
        "run_id": run_id,
        "links": research_quality_sample_links(row),
        "decision": _text(row.get("decision")),
        "hypothesis_status": _text(row.get("hypothesis_status")),
        "evidence_strength": _text(row.get("evidence_strength")),
        "research_outcome": _text(row.get("research_outcome")),
        "bounded_paper_ready": _quality_bool(row.get("bounded_paper_ready")),
        "followup_recommended": _quality_bool(row.get("followup_recommended")),
        "followup_title": _text(row.get("followup_title")),
        "recommended_next_action": _text(row.get("recommended_next_action")),
    }


def _quality_decision_posture_samples(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    rows: list[dict[str, Any]] = []
    for raw in value:
        sample = _quality_decision_posture_sample(raw)
        if sample is not None:
            rows.append(sample)
        if len(rows) >= 3:
            break
    return rows


def _quality_paper_readiness_blocker_sample(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    project_id = _text(row.get("project_id"))
    run_id = _text(row.get("run_id"))
    if not project_id and not run_id:
        return None
    reasons = [_text(item) for item in row.get("blocker_reasons") or [] if _text(item)]
    return {
        "project_id": project_id,
        "project_name": _text(row.get("project_name")),
        "run_id": run_id,
        "links": research_quality_sample_links(row),
        "hypothesis_status": _text(row.get("hypothesis_status")),
        "evidence_strength": _text(row.get("evidence_strength")),
        "research_outcome": _text(row.get("research_outcome")),
        "bounded_paper_ready": _quality_bool(row.get("bounded_paper_ready")),
        "followup_recommended": _quality_bool(row.get("followup_recommended")),
        "followup_title": _text(row.get("followup_title")),
        "recommended_next_action": _text(row.get("recommended_next_action")),
        "blocker_reasons": reasons,
    }


def _quality_paper_readiness_blocker_samples(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    rows: list[dict[str, Any]] = []
    for raw in value:
        sample = _quality_paper_readiness_blocker_sample(raw)
        if sample is not None:
            rows.append(sample)
        if len(rows) >= 3:
            break
    return rows


def _quality_paper_readiness_blockers(value: Any) -> dict[str, Any]:
    blockers = _quality_mapping(value)
    if not blockers:
        return {}
    return {
        "available": bool(blockers.get("available")),
        "decisions_checked": _safe_count(blockers.get("decisions_checked")),
        "paper_ready_count": _safe_count(blockers.get("paper_ready_count")),
        "blocker_counts": _quality_model_counts(blockers.get("blocker_counts")),
        "samples": _quality_paper_readiness_blocker_samples(blockers.get("samples")),
        "operator_action": _text(blockers.get("operator_action")),
    }


def _quality_decision_posture(value: Any) -> dict[str, Any]:
    posture = _quality_mapping(value)
    if not posture:
        return {}
    normalized = {
        "available": bool(posture.get("available")),
        "decisions_checked": _safe_count(posture.get("decisions_checked")),
        "useful_signal_count": _safe_count(posture.get("useful_signal_count")),
        "negative_count": _safe_count(posture.get("negative_count")),
        "bounded_paper_ready_count": _safe_count(
            posture.get("bounded_paper_ready_count")
        ),
        "followup_recommended_count": _safe_count(
            posture.get("followup_recommended_count")
        ),
        "compute_scale_blocked_count": _safe_count(
            posture.get("compute_scale_blocked_count")
        ),
        "publication_posture": _text(posture.get("publication_posture")),
        "research_outcome_counts": _quality_model_counts(
            posture.get("research_outcome_counts")
        ),
        "hypothesis_status_counts": _quality_model_counts(
            posture.get("hypothesis_status_counts")
        ),
        "evidence_strength_counts": _quality_model_counts(
            posture.get("evidence_strength_counts")
        ),
        "decision_counts": _quality_model_counts(posture.get("decision_counts")),
        "representative_useful_signals": _quality_decision_posture_samples(
            posture.get("representative_useful_signals")
        ),
        "operator_action": _text(posture.get("operator_action")),
    }
    blockers = _quality_paper_readiness_blockers(
        posture.get("paper_readiness_blockers")
    )
    if blockers:
        normalized["paper_readiness_blockers"] = blockers
    return normalized


def _quality_followup_readiness_sample(
    row: Any, *, include_missing_fields: bool = False, include_priority: bool = False
) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    project_id = _text(row.get("project_id"))
    run_id = _text(row.get("run_id"))
    title = _text(row.get("followup_title"))
    if not project_id and not run_id and not title:
        return None
    sample: dict[str, Any] = {
        "project_id": project_id,
        "project_name": _text(row.get("project_name")),
        "run_id": run_id,
        "links": research_quality_sample_links(row),
        "followup_type": _text(row.get("followup_type")),
        "followup_title": title,
        "followup_required_evidence_count": _safe_count(
            row.get("followup_required_evidence_count")
        ),
        "followup_success_threshold": _text(row.get("followup_success_threshold")),
        "followup_stop_condition": _text(row.get("followup_stop_condition")),
        "recommended_next_action": _text(row.get("recommended_next_action")),
    }
    if include_missing_fields:
        sample["missing_fields"] = [
            _text(item) for item in row.get("missing_fields") or [] if _text(item)
        ]
    if include_priority:
        sample.update(
            {
                "hypothesis_status": _text(row.get("hypothesis_status")),
                "evidence_strength": _text(row.get("evidence_strength")),
                "priority_score": _safe_count(row.get("priority_score")),
                "priority_reasons": [
                    _text(item)
                    for item in row.get("priority_reasons") or []
                    if _text(item)
                ],
            }
        )
    return sample


def _quality_followup_readiness_samples(
    value: Any,
    *,
    include_missing_fields: bool = False,
    include_priority: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    rows: list[dict[str, Any]] = []
    for raw in value:
        sample = _quality_followup_readiness_sample(
            raw,
            include_missing_fields=include_missing_fields,
            include_priority=include_priority,
        )
        if sample is not None:
            rows.append(sample)
        if len(rows) >= 3:
            break
    return rows


def _quality_followup_readiness(value: Any) -> dict[str, Any]:
    readiness = _quality_mapping(value)
    if not readiness:
        return {}
    return {
        "available": bool(readiness.get("available")),
        "recommended_count": _safe_count(readiness.get("recommended_count")),
        "bounded_ready_count": _safe_count(readiness.get("bounded_ready_count")),
        "underspecified_count": _safe_count(readiness.get("underspecified_count")),
        "missing_title_count": _safe_count(readiness.get("missing_title_count")),
        "missing_success_threshold_count": _safe_count(
            readiness.get("missing_success_threshold_count")
        ),
        "missing_stop_condition_count": _safe_count(
            readiness.get("missing_stop_condition_count")
        ),
        "thin_required_evidence_count": _safe_count(
            readiness.get("thin_required_evidence_count")
        ),
        "followup_type_counts": _quality_model_counts(
            readiness.get("followup_type_counts")
        ),
        "ready_followups": _quality_followup_readiness_samples(
            readiness.get("ready_followups")
        ),
        "prioritized_followups": _quality_followup_readiness_samples(
            readiness.get("prioritized_followups"),
            include_priority=True,
        ),
        "underspecified_followups": _quality_followup_readiness_samples(
            readiness.get("underspecified_followups"),
            include_missing_fields=True,
        ),
        "operator_action": _text(readiness.get("operator_action")),
    }


def _post_prompt_warning_details(
    *,
    malformed_count: int,
    malformed_ticks: int,
    useful_delta: float,
    provider_generation_health: Mapping[str, Any],
) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    provider_recovered = (
        _text(provider_generation_health.get("malformed_history_status")) == "recovered"
    )
    if malformed_count > 0 and provider_recovered:
        details.append(
            {
                "code": "provider_generation_recovered",
                "severity": "info",
                "message": (
                    f"{malformed_count} malformed provider responses recovered "
                    f"after {provider_generation_health.get('consecutive_clean_ticks')} "
                    "clean ticks"
                ),
                "operator_action": _text(
                    provider_generation_health.get("operator_action")
                ),
            }
        )
    elif malformed_count > 0:
        tick_label = "recent tick" if malformed_ticks == 1 else "recent ticks"
        details.append(
            {
                "code": "malformed_provider_responses",
                "severity": "warning",
                "message": (
                    f"{malformed_count} malformed provider responses across "
                    f"{malformed_ticks} {tick_label}"
                ),
                "operator_action": (
                    "inspect provider-generation output for the listed ticks "
                    "before trusting new idea volume"
                ),
            }
        )
    if useful_delta < 0:
        details.append(
            {
                "code": "useful_followup_decline",
                "severity": "warning",
                "message": (
                    f"useful adjacent follow-up signal declined by "
                    f"{abs(useful_delta):.1f}"
                ),
                "operator_action": (
                    "review recent follow-up quality before increasing throughput"
                ),
            }
        )
    return details


def _quality_provider_summary(
    *,
    malformed_count: int,
    malformed_ticks: int,
    provider_generation_health: Mapping[str, Any],
) -> str:
    status = _text(provider_generation_health.get("malformed_history_status"))
    clean_ticks = _safe_count(provider_generation_health.get("consecutive_clean_ticks"))
    if malformed_count <= 0:
        return "provider malformed=clean"
    if status == "recovered":
        return (
            f"provider malformed=recovered ({malformed_count} responses; "
            f"{clean_ticks} clean ticks)"
        )
    tick_label = "recent tick" if malformed_ticks == 1 else "recent ticks"
    return (
        f"provider malformed=active ({malformed_count} responses across "
        f"{malformed_ticks} {tick_label})"
    )


def _quality_provider_yield_summary(
    provider_generation_health: Mapping[str, Any],
) -> str:
    latest_tick = _quality_mapping(provider_generation_health.get("latest_tick"))
    latest_yield_status = _text(provider_generation_health.get("latest_yield_status"))
    if not latest_yield_status:
        return ""
    generated = _safe_count(latest_tick.get("generated_count"))
    promoted = _safe_count(latest_tick.get("promoted_count"))
    initial_promotable = _safe_count(latest_tick.get("initial_promotable_count"))
    zero_generated = _safe_count(
        provider_generation_health.get("consecutive_zero_generated_ticks")
    )
    if latest_yield_status == "yielding":
        return f"provider yield=yielding ({generated} generated; {promoted} promoted)"
    if latest_yield_status == "backlog_satisfied":
        return (
            "provider yield=backlog satisfied "
            f"({generated} generated; {initial_promotable} promotable; "
            f"{zero_generated} zero-generation ticks)"
        )
    return (
        "provider yield=zero "
        f"({generated} generated; {promoted} promoted; "
        f"{zero_generated} zero-generation ticks)"
    )


def _quality_useful_followup_window_counts(
    window_comparison: Mapping[str, Any],
) -> tuple[int, int] | None:
    current_counts = _quality_mapping(
        _quality_mapping(window_comparison.get("current")).get("eval_case_counts")
    )
    previous_counts = _quality_mapping(
        _quality_mapping(window_comparison.get("previous")).get("eval_case_counts")
    )
    key = "useful_adjacent_followup"
    if key not in current_counts or key not in previous_counts:
        return None
    return _safe_count(current_counts.get(key)), _safe_count(previous_counts.get(key))


def _quality_useful_followup_summary(
    useful_delta: float, window_comparison: Mapping[str, Any]
) -> str:
    counts = _quality_useful_followup_window_counts(window_comparison)
    count_summary = (
        f" ({counts[0]} current vs {counts[1]} previous)" if counts is not None else ""
    )
    if useful_delta < 0:
        return f"useful follow-up=active decline {useful_delta:.1f}{count_summary}"
    if useful_delta > 0:
        return f"useful follow-up=improving +{useful_delta:.1f}{count_summary}"
    return f"useful follow-up=stable 0.0{count_summary}"


def _quality_refresh_operator_action(refresh: Mapping[str, Any]) -> str:
    reason = _text(refresh.get("reason"))
    if bool(refresh.get("ok")):
        return ""
    if reason == "missing database URL":
        return (
            "configure the Research Quality database URL so the read-only refresh "
            "can update the report"
        )
    if reason in {"missing_refresh_status", "not_configured"}:
        return (
            "run the Research Quality refresh-only sidecar so refresh health is "
            "recorded"
        )
    return "inspect the Research Quality refresh sidecar before relying on unattended automation"


def _signal_reason(
    code: str,
    severity: str,
    message: str,
    operator_action: str,
    *,
    status: str = "active",
    active: bool = True,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "operator_action": operator_action,
        "status": status,
        "active": active,
    }


def _quality_signal_base_reasons(
    *,
    quality_ok: bool,
    status: str,
    blocked_count: int,
    warning_count: int,
    freshness: Mapping[str, Any],
    refresh: Mapping[str, Any],
) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    if bool(freshness.get("report_is_stale")):
        reasons.append(
            _signal_reason(
                "quality_report_stale",
                "blocked",
                "quality report is stale",
                "refresh the Research Quality report before relying on unattended automation",
            )
        )
    if refresh and not bool(refresh.get("ok")):
        reasons.append(
            _signal_reason(
                "quality_refresh_unhealthy",
                "blocked",
                "quality refresh source is unhealthy",
                _quality_refresh_operator_action(refresh),
            )
        )
    if status == "blocked" or blocked_count > 0 or not quality_ok:
        reasons.append(
            _signal_reason(
                "quality_blocked",
                "blocked",
                "quality report contains blocked findings",
                "resolve blocked Research Quality findings before relying on unattended automation",
            )
        )
    if warning_count > 0:
        reasons.append(
            _signal_reason(
                "quality_warnings",
                "warning",
                "quality report contains warning findings",
                "inspect warning findings before widening automation",
            )
        )
    return reasons


def _provider_generation_signal_reason(
    malformed_count: int, provider_generation_health: Mapping[str, Any]
) -> dict[str, Any] | None:
    if malformed_count <= 0:
        return None
    if _text(provider_generation_health.get("malformed_history_status")) == "recovered":
        return _signal_reason(
            "provider_generation_recovered",
            "info",
            "provider generation recovered after malformed responses",
            _text(provider_generation_health.get("operator_action")),
            status="recovered",
            active=False,
        )
    return _signal_reason(
        "malformed_provider_responses",
        "warning",
        "provider generation produced malformed responses",
        "inspect provider-generation failures before trusting new idea volume",
    )


def _quality_signal_verdict_from_reasons(
    active_reasons: Sequence[Mapping[str, Any]],
) -> str:
    if any(
        item["code"] in {"quality_report_stale", "quality_refresh_unhealthy"}
        for item in active_reasons
    ):
        return "stale"
    if any(item["severity"] == "blocked" for item in active_reasons):
        return "blocked"
    if any(item["severity"] == "warning" for item in active_reasons):
        return "review_required"
    return "defensible"


def _quality_signal_verdict(
    *,
    quality_ok: bool,
    status: str,
    blocked_count: int,
    warning_count: int,
    malformed_count: int,
    useful_delta: float,
    provider_generation_health: Mapping[str, Any],
    freshness: Mapping[str, Any],
    refresh: Mapping[str, Any],
) -> dict[str, Any]:
    reasons = _quality_signal_base_reasons(
        quality_ok=quality_ok,
        status=status,
        blocked_count=blocked_count,
        warning_count=warning_count,
        freshness=freshness,
        refresh=refresh,
    )
    provider_reason = _provider_generation_signal_reason(
        malformed_count, provider_generation_health
    )
    if provider_reason:
        reasons.append(provider_reason)
    if useful_delta < 0:
        reasons.append(
            _signal_reason(
                "useful_followup_decline",
                "warning",
                "useful adjacent follow-up signal declined",
                "review recent follow-up quality before increasing throughput",
            )
        )

    active_reasons = [item for item in reasons if bool(item.get("active", True))]
    verdict = _quality_signal_verdict_from_reasons(active_reasons)
    if verdict == "defensible" and not reasons:
        reasons.append(
            _signal_reason(
                "clean_current_quality_report",
                "info",
                "current quality report is clean and refresh source is healthy",
                "continue monitoring Research Quality alongside operational readiness",
                active=False,
                status="clean",
            )
        )

    labels = {
        "stale": "Research signal: stale",
        "blocked": "Research signal: blocked",
        "review_required": "Research signal: review required",
        "defensible": "Research signal: defensible",
    }
    primary_reason = active_reasons[0] if active_reasons else reasons[0]
    return {
        "signal_verdict": verdict,
        "signal_label": labels[verdict],
        "signal_reasons": reasons,
        "signal_operator_action": primary_reason["operator_action"],
    }


def _quality_window_eval_count(
    quality_snapshot: Mapping[str, Any], window: str, key: str
) -> int:
    comparison = _quality_mapping(quality_snapshot.get("window_comparison"))
    row = _quality_mapping(comparison.get(window))
    eval_counts = _quality_mapping(row.get("eval_case_counts"))
    return _safe_count(eval_counts.get(key))


def _research_output_next_action(
    top_actions: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    for action in top_actions or []:
        if _text(action.get("kind")) != "investigate_followup":
            continue
        target = _quality_mapping(action.get("target"))
        run_id = _text(target.get("run_id") or target.get("current_run_id"))
        return {
            "kind": _text(action.get("kind")),
            "title": _text(action.get("title")),
            "summary": _text(action.get("summary")),
            "action_label": _text(action.get("action_label")),
            "action_hash": _text(action.get("action_hash")),
            "target": {
                "project_id": _text(target.get("project_id")),
                "run_id": run_id,
                "name": _text(
                    target.get("name")
                    or target.get("project_name")
                    or target.get("followup_title")
                ),
            },
        }
    return {}


def _research_output_artifact(row: Mapping[str, Any], *, source: str) -> dict[str, Any]:
    return {
        "source": source,
        "project_id": _text(row.get("project_id")),
        "project_name": _text(row.get("project_name")),
        "run_id": _text(row.get("run_id") or row.get("current_run_id")),
        "title": _text(
            row.get("followup_title") or row.get("title") or row.get("project_name")
        ),
        "case_id": _text(row.get("case_id")),
    }


def _research_output_affected_artifacts(
    quality_snapshot: Mapping[str, Any],
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    followup_evidence = _quality_mapping(
        quality_snapshot.get("useful_adjacent_followup_evidence")
    )
    for source, rows in (
        ("useful_adjacent_followup_evidence.current", followup_evidence.get("current")),
        (
            "decision_posture.representative_useful_signals",
            _quality_mapping(quality_snapshot.get("decision_posture")).get(
                "representative_useful_signals"
            ),
        ),
    ):
        for row in rows or []:
            if not isinstance(row, Mapping):
                continue
            artifact = _research_output_artifact(row, source=source)
            if any(artifact.get(key) for key in ("project_id", "run_id", "title")):
                artifacts.append(artifact)
            if len(artifacts) >= 5:
                return artifacts
    return artifacts


def _research_output_failed_invariants(
    quality_snapshot: Mapping[str, Any],
) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    useful_delta = _quality_value(quality_snapshot, "useful_adjacent_followup_delta", 0)
    current_followups = _quality_window_eval_count(
        quality_snapshot, "current", "useful_adjacent_followup"
    )
    previous_followups = _quality_window_eval_count(
        quality_snapshot, "previous", "useful_adjacent_followup"
    )
    if float(useful_delta) < 0:
        failed.append(
            {
                "code": "useful_followup_decline",
                "label": "Useful follow-up signal must not decline",
                "current": current_followups,
                "required": f">= {previous_followups}",
                "previous": previous_followups,
                "delta": float(useful_delta),
            }
        )
    decision_posture = _quality_mapping(quality_snapshot.get("decision_posture"))
    bounded_ready = _safe_count(decision_posture.get("bounded_paper_ready_count"))
    useful_signals = _safe_count(decision_posture.get("useful_signal_count"))
    if decision_posture.get("available") and useful_signals > 0 and bounded_ready < 1:
        failed.append(
            {
                "code": "no_paper_ready_outputs",
                "label": "At least one bounded paper-ready output is required",
                "current": bounded_ready,
                "required": ">= 1",
                "useful_signal_count": useful_signals,
                "publication_posture": _text(
                    decision_posture.get("publication_posture")
                ),
            }
        )
    verdict = _text(quality_snapshot.get("signal_verdict"))
    if verdict and verdict not in {"defensible", "review_required"} and not failed:
        failed.append(
            {
                "code": "signal_verdict_not_defensible",
                "label": "Research signal verdict must be defensible",
                "current": verdict,
                "required": "defensible",
            }
        )
    return failed


def _research_output_state(
    *,
    failed_invariants: Sequence[Mapping[str, Any]],
    signal_verdict: str,
    maintenance_hold: bool,
) -> str:
    failed_codes = {str(item.get("code") or "") for item in failed_invariants}
    if "useful_followup_decline" in failed_codes:
        return "blocked_by_quality_decline"
    if "no_paper_ready_outputs" in failed_codes:
        return "blocked_by_no_paper_ready_outputs"
    if signal_verdict and signal_verdict != "defensible":
        return "review_required"
    if maintenance_hold:
        return "maintenance_hold_ready"
    return "ready"


def _research_output_label(state: str) -> str:
    labels = {
        "ready": "Research output readiness: ready",
        "review_required": "Research output readiness: review required",
        "blocked_by_quality_decline": (
            "Research output readiness: blocked by quality decline"
        ),
        "blocked_by_no_paper_ready_outputs": (
            "Research output readiness: blocked by no paper-ready outputs"
        ),
        "maintenance_hold_ready": "Research output readiness: maintenance hold ready",
    }
    return labels.get(state, "Research output readiness: review required")


def _research_output_operator_action(
    *,
    failed_invariants: Sequence[Mapping[str, Any]],
    next_action: Mapping[str, Any],
    hold_state: str,
    fallback_action: str,
) -> str:
    parts: list[str] = []
    by_code = {str(item.get("code") or ""): item for item in failed_invariants}
    followup = by_code.get("useful_followup_decline")
    if followup:
        parts.append(
            "Useful follow-up signal declined from "
            f"{_safe_count(followup.get('previous'))} to "
            f"{_safe_count(followup.get('current'))}"
        )
    if "no_paper_ready_outputs" in by_code:
        parts.append("no bounded paper-ready outputs are available")
    action_title = _text(next_action.get("title"))
    if action_title:
        parts.append(f"queue bounded follow-up investigation: {action_title}")
    elif fallback_action and parts:
        parts.append(fallback_action)
    if not parts and fallback_action:
        parts.append(fallback_action)
    action = "; ".join(parts) if parts else "Research output readiness is clear"
    if hold_state == "maintenance_hold":
        action = (
            f"{action}. "
            "Maintenance mode is holding automation; clear it only after the "
            "research-quality blockers are resolved."
        )
    elif not action.endswith("."):
        action = f"{action}."
    return action


def research_output_readiness_contract(
    quality_snapshot: Mapping[str, Any],
    *,
    flags: Mapping[str, Any] | None = None,
    top_actions: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    flag_row = _quality_mapping(flags)
    maintenance_hold = bool(
        flag_row.get("maintenance_mode") or flag_row.get("queue_paused")
    )
    hold_state = "maintenance_hold" if maintenance_hold else "none"
    failed = _research_output_failed_invariants(quality_snapshot)
    signal_verdict = _text(quality_snapshot.get("signal_verdict"))
    state = _research_output_state(
        failed_invariants=failed,
        signal_verdict=signal_verdict,
        maintenance_hold=maintenance_hold,
    )
    next_action = _research_output_next_action(top_actions)
    fallback_action = _text(quality_snapshot.get("signal_operator_action"))
    return {
        "state": state,
        "label": _research_output_label(state),
        "blocked_by": "research_quality"
        if failed or state == "review_required"
        else "",
        "hold_state": hold_state,
        "failed_invariants": list(failed),
        "affected_artifacts": _research_output_affected_artifacts(quality_snapshot),
        "next_bounded_action": next_action,
        "operator_action": _research_output_operator_action(
            failed_invariants=failed,
            next_action=next_action,
            hold_state=hold_state,
            fallback_action=fallback_action,
        ),
        "signal_verdict": signal_verdict,
    }


def research_signal_quality_snapshot(
    quality: Mapping[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    problem_counts = _quality_mapping(quality.get("problem_counts"))
    severity_counts = _quality_mapping(quality.get("severity_counts"))
    monitor = _quality_mapping(quality.get("post_prompt_monitor"))
    weak_evidence_count = _quality_count(
        problem_counts, "weak_or_missing_evidence_strength"
    )
    warning_count = _quality_count(severity_counts, "warning")
    blocked_count = _quality_count(severity_counts, "blocked")
    malformed_count = _quality_count(monitor, "malformed_provider_response_count")
    malformed_ticks = _safe_count(
        _quality_value(monitor, "malformed_provider_response_ticks", 0)
    )
    recent_malformed = _quality_recent_malformed_provider_responses(monitor)
    followup_evidence = _quality_followup_evidence(monitor)
    if malformed_count > 0 and malformed_ticks == 0:
        malformed_ticks = len(recent_malformed)
    useful_delta = _quality_value(monitor, "useful_adjacent_followup_delta", 0.0)
    status = _text(quality.get("status")) or "unknown"
    refresh = _quality_mapping(quality.get("refresh_status"))
    report_mtime = quality.get("report_mtime") or ""
    freshness = research_quality_report_freshness(report_mtime, now=now)
    quality_ok = bool(quality.get("ok"))
    provider_generation_health = _quality_provider_generation_health(
        monitor.get("provider_generation_health")
    )
    signal = _quality_signal_verdict(
        quality_ok=quality_ok,
        status=status,
        blocked_count=blocked_count,
        warning_count=warning_count,
        malformed_count=malformed_count,
        useful_delta=useful_delta,
        provider_generation_health=provider_generation_health,
        freshness=freshness,
        refresh=refresh,
    )
    post_prompt_warning_details = _post_prompt_warning_details(
        malformed_count=malformed_count,
        malformed_ticks=malformed_ticks,
        useful_delta=float(useful_delta),
        provider_generation_health=provider_generation_health,
    )
    window_comparison = _quality_window_comparison(monitor.get("window_comparison"))
    quality_floor = _quality_floor(quality.get("quality_floor"))
    decision_posture = _quality_decision_posture(quality.get("decision_posture"))
    followup_readiness = _quality_followup_readiness(quality.get("followup_readiness"))
    decision_posture_summary = _quality_decision_posture_summary(decision_posture)
    followup_readiness_summary = _quality_followup_readiness_summary(followup_readiness)
    parts = [
        f"quality={status}",
        *([_quality_floor_summary(quality_floor)] if quality_floor else []),
        *([decision_posture_summary] if decision_posture_summary else []),
        *([followup_readiness_summary] if followup_readiness_summary else []),
        f"weak evidence={weak_evidence_count}",
        _quality_provider_summary(
            malformed_count=malformed_count,
            malformed_ticks=malformed_ticks,
            provider_generation_health=provider_generation_health,
        ),
        _quality_provider_yield_summary(provider_generation_health),
        _quality_useful_followup_summary(float(useful_delta), window_comparison),
    ]
    parts = [part for part in parts if part]
    raw_recommendations = _quality_recommendations(quality)
    return {
        "status": status,
        "ok": quality_ok,
        "label": quality.get("label") or "",
        "decisions_checked": _safe_count(quality.get("decisions_checked")),
        "candidates_checked": _safe_count(quality.get("candidates_checked")),
        "candidate_status_counts": _quality_model_counts(
            quality.get("candidate_status_counts")
        ),
        "decision_outcome_counts": _quality_count_rows(
            quality.get("decision_outcome_counts"),
            required_label="decision",
            optional_label="hypothesis_status",
        ),
        "top_candidate_categories": _quality_count_rows(
            quality.get("top_candidate_categories"),
            required_label="category",
        ),
        "candidate_status_samples": _quality_candidate_status_samples(
            quality.get("candidate_status_samples")
        ),
        "decision_outcome_samples": _quality_decision_outcome_samples(
            quality.get("decision_outcome_samples")
        ),
        "quality_floor": quality_floor,
        "decision_posture": decision_posture,
        "followup_readiness": followup_readiness,
        "weak_evidence_count": weak_evidence_count,
        "warning_problem_count": warning_count,
        "blocked_problem_count": blocked_count,
        "problem_counts": dict(problem_counts),
        "report_path": quality.get("report_path") or "",
        "report_mtime": report_mtime,
        **freshness,
        **signal,
        "refresh_ok": bool(refresh.get("ok")),
        "refresh_action": _text(refresh.get("action")),
        "refresh_reason": _text(refresh.get("reason")),
        "refresh_recorded_at": _text(refresh.get("recorded_at")),
        "refresh_status_path": _text(refresh.get("path")),
        "refresh_operator_action": _quality_refresh_operator_action(refresh),
        "post_prompt_available": bool(_quality_value(monitor, "available", False)),
        "decision_coverage": _quality_value(monitor, "decision_coverage", 0.0),
        "proxy_only_positive": _quality_count(monitor, "proxy_only_positive"),
        "proxy_only_positive_delta": _quality_value(
            monitor, "proxy_only_positive_delta", 0.0
        ),
        "useful_adjacent_followup": _quality_count(monitor, "useful_adjacent_followup"),
        "useful_adjacent_followup_delta": useful_delta,
        "moonshot_avg_score_delta": _quality_value(
            monitor, "moonshot_avg_score_delta", 0.0
        ),
        "malformed_provider_response_count": malformed_count,
        "malformed_provider_response_ticks": malformed_ticks,
        "malformed_provider_model_counts": _quality_model_counts(
            monitor.get("malformed_provider_model_counts")
        ),
        "provider_generation_health": provider_generation_health,
        "window_comparison": window_comparison,
        "recent_malformed_provider_responses": recent_malformed,
        "useful_adjacent_followup_evidence": followup_evidence,
        "post_prompt_warning_details": post_prompt_warning_details,
        "last_malformed_at": _quality_value(monitor, "last_malformed_at", ""),
        "last_checked_at": _quality_value(monitor, "last_checked_at", ""),
        "top_problem_details": _quality_problem_details(quality),
        "recommendations": raw_recommendations,
        "operator_recommendations": _operator_quality_recommendations(
            signal=signal,
            post_prompt_warnings=post_prompt_warning_details,
            raw_recommendations=raw_recommendations,
        ),
        "operator_summary": "; ".join(parts),
    }


def _followup_alignment_candidate(
    row: Any, *, run_keys: tuple[str, ...] = ("run_id", "current_run_id")
) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        return {}
    run_id = ""
    for key in run_keys:
        run_id = _text(row.get(key))
        if run_id:
            break
    candidate = {
        "project_id": _text(row.get("project_id")),
        "project_name": _text(row.get("project_name")),
        "run_id": run_id,
        "followup_title": _text(row.get("followup_title")),
        "recommended_next_action": _text(row.get("recommended_next_action")),
    }
    return (
        candidate
        if any(candidate.get(key) for key in ("project_id", "run_id", "followup_title"))
        else {}
    )


def _followup_scope_alignment(
    *,
    investigation_pipeline: Mapping[str, Any],
    quality_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    global_candidate = _followup_alignment_candidate(
        investigation_pipeline.get("next_ranked_followup_candidate"),
        run_keys=("current_run_id", "run_id"),
    )
    readiness = quality_snapshot.get("followup_readiness")
    quality_candidate: dict[str, Any] = {}
    if isinstance(readiness, Mapping):
        prioritized = readiness.get("prioritized_followups") or []
        if isinstance(prioritized, Sequence) and prioritized:
            quality_candidate = _followup_alignment_candidate(prioritized[0])
    global_count = _safe_count(investigation_pipeline.get("ranked_followup_ready"))
    available = bool(global_candidate or quality_candidate or global_count)
    if not available:
        return {}
    same_project = bool(
        global_candidate
        and quality_candidate
        and global_candidate.get("project_id")
        and global_candidate.get("project_id") == quality_candidate.get("project_id")
    )
    same_run = bool(
        global_candidate
        and quality_candidate
        and global_candidate.get("run_id")
        and global_candidate.get("run_id") == quality_candidate.get("run_id")
    )
    operator_action = (
        "Global ranked follow-up and Research Quality window priority select the same project; use it as the current bounded follow-up candidate."
        if same_project
        else "Global ranked follow-up and Research Quality window priority are different scopes; use the global action for queue selection and the quality-window sample for quality review."
    )
    return {
        "available": True,
        "global_ready_count": global_count,
        "same_project": same_project,
        "same_run": same_run,
        "global_candidate": global_candidate,
        "quality_window_candidate": quality_candidate,
        "operator_action": operator_action,
    }


def _latest_research_quality_for_overview() -> dict[str, Any]:
    configured = os.environ.get("ENOCH_RESEARCH_QUALITY_REPORT_PATH", "").strip()
    paths = (configured, *DEFAULT_REPORT_PATHS) if configured else DEFAULT_REPORT_PATHS
    try:
        return load_latest_quality_status(
            paths,
            window_report_path=os.environ.get(
                "ENOCH_RESEARCH_QUALITY_WINDOW_REPORT_PATH",
                DEFAULT_WINDOW_REPORT_PATH,
            ),
            autopilot_history_path=os.environ.get(
                "ENOCH_RESEARCH_AUTOPILOT_HISTORY_PATH",
                DEFAULT_AUTOPILOT_HISTORY_PATH,
            ),
        )
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "status": "blocked",
            "label": "Research quality: BLOCKED",
            "decisions_checked": 0,
            "candidates_checked": 0,
            "problem_counts": {"unreadable_quality_report": 1},
            "severity_counts": {"blocked": 1},
            "report_path": paths[0] if paths else "",
            "report_mtime": "",
            "post_prompt_monitor": {},
            "problem_details": [
                {
                    "section": "report",
                    "severity": "blocked",
                    "problem": "unreadable_quality_report",
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            ],
        }


def _paper_drought_recovery_action(
    *,
    drought_warning: bool,
    paper_pipeline: Mapping[str, Any],
    investigation_pipeline: Mapping[str, Any],
    top_deepen_candidate: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not drought_warning:
        return {
            "status": "recent_paper",
            "next_action": "monitor",
            "count": 0,
            "target": None,
            "reason": "latest paper is inside the drought threshold",
        }
    write_needed = _safe_count(paper_pipeline.get("write_needed"))
    if write_needed:
        target = paper_pipeline.get("next_write_candidate") or {}
        return {
            "status": "write_needed",
            "next_action": "draft_paper",
            "count": write_needed,
            "target": _candidate_target(target)
            or draft_candidate_payload(dict(target)),
            "reason": "paper-ready completed runs are waiting for first draft",
        }
    followup_ready = _safe_count(investigation_pipeline.get("ranked_followup_ready"))
    if followup_ready:
        target = (
            investigation_pipeline.get("next_ranked_followup_candidate")
            or investigation_pipeline.get("next_followup_candidate")
            or {}
        )
        return {
            "status": "ranked_followup_ready",
            "next_action": "queue_followup",
            "count": followup_ready,
            "target": _candidate_target(target)
            or draft_candidate_payload(dict(target)),
            "reason": "recent useful signals need bounded follow-up evidence before paper drafting",
        }
    if top_deepen_candidate:
        return {
            "status": "deepen_required",
            "next_action": "deepen_evidence",
            "count": 1,
            "target": draft_candidate_payload(dict(top_deepen_candidate)),
            "reason": "top completed run has a concrete evidence gap before paper readiness",
        }
    return {
        "status": "no_recovery_candidate",
        "next_action": "generate_better_candidate",
        "count": 0,
        "target": None,
        "reason": "no paper-ready or ranked follow-up candidate is currently visible",
    }


def _overview_events_page(
    store: ControlPlaneStore,
    batched_parts: Mapping[str, Any] | None,
    *,
    event_limit: int,
) -> tuple[list[Any], str, bool]:
    if batched_parts is not None:
        return batched_parts["events_page"]
    return store.event_page(page_size=event_limit, include_payload=False)


def _overview_next_candidate(next_candidate: Any) -> dict[str, Any] | None:
    if not next_candidate:
        return None
    return summarize_queue_row(next_candidate)


PROVIDER_GENERATION_ATTEMPT_EVENT = "research.provider_generation.attempt"
LLM_MODEL_TEST_EVENT = "settings.llm.model_test"


def _llm_harness_event_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    if not isinstance(payload, Mapping):
        payload = {}
    return {
        "event_id": row.get("event_id") or row.get("id"),
        "event_type": _text(row.get("event_type")),
        "created_at": row.get("created_at") or row.get("updated_at") or "",
        "workflow_id": _text(payload.get("workflow_id")),
        "run_id": _text(payload.get("run_id")),
        "trace_id": _text(payload.get("trace_id")),
        "provider_id": _text(payload.get("provider_id")),
        "model_id": _text(payload.get("model_id")),
        "tool_name": _text(payload.get("tool_name")),
        "policy_id": _text(payload.get("policy_id")),
        "source": _text(payload.get("source")),
        "started_at": _text(payload.get("started_at")),
        "completed_at": _text(payload.get("completed_at")),
        "status": _text(payload.get("status")),
        "failure_kind": _text(payload.get("failure_kind")),
        "estimated_cost_usd": float(payload.get("estimated_cost_usd") or 0),
        "input_token_count": int(payload.get("input_token_count") or 0),
        "output_token_count": int(payload.get("output_token_count") or 0),
        "selected_provider_id": _text(payload.get("selected_provider_id")),
        "selected_model_id": _text(payload.get("selected_model_id")),
        "selection_reason": _text(payload.get("selection_reason"))[:300],
        "budget_gate_status": _text(payload.get("budget_gate_status")),
        "health_gate_status": _text(payload.get("health_gate_status")),
        "result_count": int(payload.get("result_count") or 0),
        "source_urls": list(payload.get("source_urls") or [])[:10]
        if isinstance(payload.get("source_urls"), list)
        else [],
        "source_titles": list(payload.get("source_titles") or [])[:10]
        if isinstance(payload.get("source_titles"), list)
        else [],
        "retrieval_timestamp": _text(payload.get("retrieval_timestamp")),
    }


def _llm_harness_status_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        status = _text(event.get("status")) or "unknown"
        counts[status] = counts.get(status, 0) + 1
    return counts


def _llm_harness_type_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        event_type = _text(event.get("event_type")) or "unknown"
        counts[event_type] = counts.get(event_type, 0) + 1
    return counts


def llm_harness_telemetry_summary(
    store: ControlPlaneStore, *, limit: int = 100
) -> dict[str, Any]:
    rows: list[Mapping[str, Any]] = []
    per_type_limit = max(1, min(limit, 200))
    for event_type in sorted(LLM_HARNESS_EVENT_TYPES):
        rows.extend(
            _event_rows_for_type(store, event_type=event_type, limit=per_type_limit)
        )
    events = [_llm_harness_event_payload(row) for row in rows]
    events.sort(key=lambda row: int(row.get("event_id") or 0), reverse=True)
    events = events[: max(1, min(limit, 200))]
    failure_count = sum(1 for event in events if _text(event.get("status")) != "ok")
    total_cost = round(
        sum(
            float(event.get("estimated_cost_usd") or 0)
            for event in events
            if event.get("event_type") == LLM_HARNESS_COST_OBSERVATION_EVENT
        ),
        6,
    )
    return {
        "ok": failure_count == 0,
        "status": "healthy" if failure_count == 0 else "needs_attention",
        "event_count": len(events),
        "failure_count": failure_count,
        "estimated_cost_usd": total_cost,
        "status_counts": _llm_harness_status_counts(events),
        "event_type_counts": _llm_harness_type_counts(events),
        "recent_events": events,
        "taxonomy": {
            "llm_harness.route_decision": "provider/model selection before output is accepted",
            "llm_harness.tool_call": "bounded tool invocation metadata without raw payloads",
            "llm_harness.tool_result": "redacted retrieval result metadata and hashes",
            "llm_harness.output_contract": "structured-output acceptance or rejection evidence",
            "llm_harness.cost_observation": "bounded cost and token accounting evidence",
        },
    }


def _provider_generation_attempt_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    return payload if isinstance(payload, dict) else {}


def _provider_generation_attempt_record(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = _provider_generation_attempt_payload(row)
    return {
        "event_id": row.get("event_id") or row.get("id"),
        "created_at": row.get("created_at") or row.get("updated_at") or "",
        "recorded_at": payload.get("recorded_at") or row.get("created_at") or "",
        "status": _text(payload.get("status")) or "unknown",
        "failure_kind": _text(payload.get("failure_kind")),
        "reason": _text(payload.get("reason")),
        "provider": _text(payload.get("provider")),
        "provider_id": _text(payload.get("provider_id")),
        "provider_model": _text(payload.get("provider_model")),
        "machine_target": _text(payload.get("machine_target")),
        "lane_key": _text(payload.get("lane_key")),
        "run_cycle_id": _text(payload.get("run_cycle_id")),
        "candidate_count": int(payload.get("candidate_count") or 0),
        "planned_count": int(payload.get("planned_count") or 0),
        "latency_ms": int(payload.get("latency_ms") or 0),
    }


def provider_generation_attempt_summary(
    store: ControlPlaneStore, *, limit: int = 20
) -> dict[str, Any]:
    try:
        page_reader = object.__getattribute__(store, "event_page")
    except AttributeError:
        page_reader = None
    try:
        row_reader = object.__getattribute__(store, "event_rows")
    except AttributeError:
        row_reader = None
    if callable(page_reader):
        rows, _next_cursor, _has_more = page_reader(
            page_size=limit,
            event_type=PROVIDER_GENERATION_ATTEMPT_EVENT,
            include_payload=True,
        )
    elif callable(row_reader):
        rows = row_reader(limit=limit, event_type=PROVIDER_GENERATION_ATTEMPT_EVENT)
    else:
        return {
            "ok": True,
            "status": "unavailable",
            "attempt_count": 0,
            "recent_failed_count": 0,
            "latest": None,
            "reason": "event read model unavailable",
        }
    attempts = [_provider_generation_attempt_record(row) for row in rows]
    latest = attempts[0] if attempts else None
    latest_status = _text((latest or {}).get("status")) or "none"
    failed_count = sum(1 for attempt in attempts if attempt.get("status") == "failed")
    ok = latest_status not in {"failed"}
    status = "ok"
    if latest is None:
        status = "no_attempts"
    elif not ok:
        status = "blocked"
    return {
        "ok": ok,
        "status": status,
        "attempt_count": len(attempts),
        "recent_failed_count": failed_count,
        "latest_status": latest_status,
        "latest_failure_kind": _text((latest or {}).get("failure_kind")),
        "latest_reason": _text((latest or {}).get("reason")),
        "latest": latest,
    }


def _event_rows_for_type(
    store: ControlPlaneStore, *, event_type: str, limit: int
) -> list[Mapping[str, Any]]:
    try:
        page_reader = object.__getattribute__(store, "event_page")
    except AttributeError:
        page_reader = None
    try:
        row_reader = object.__getattribute__(store, "event_rows")
    except AttributeError:
        row_reader = None
    if callable(page_reader):
        rows, _next_cursor, _has_more = page_reader(
            page_size=limit,
            event_type=event_type,
            include_payload=True,
        )
        return list(rows)
    if callable(row_reader):
        return list(row_reader(limit=limit, event_type=event_type))
    return []


def _llm_model_health_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    if not isinstance(payload, Mapping):
        return {}
    out = _base_llm_model_health_payload(row, payload)
    _copy_optional_bool_flags(out, payload)
    return out


def _base_llm_model_health_payload(
    row: Mapping[str, Any], payload: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "event_id": row.get("event_id") or row.get("id"),
        "created_at": row.get("created_at") or row.get("updated_at") or "",
        "checked_at": _text(payload.get("checked_at") or row.get("created_at")),
        "provider_id": _text(payload.get("provider_id")),
        "model_id": _text(payload.get("model_id")),
        "ok": bool(payload.get("ok")),
        "status_code": int(payload.get("status_code") or 0),
        "failure_kind": _text(payload.get("failure_kind")),
        "error": _text(payload.get("error"))[:500],
        "latency_ms": int(payload.get("latency_ms") or 0),
        "source": _text(payload.get("source")) or "unknown",
        "finish_reason": _text(payload.get("finish_reason")),
        "visible_chars": int(payload.get("visible_chars") or 0),
        "response_preview_redacted": _text(payload.get("response_preview_redacted"))[
            :240
        ],
        "workflow_id": _text(payload.get("workflow_id")),
        "prompt_contract": _text(payload.get("prompt_contract")),
        "structured_output_mode": _text(payload.get("structured_output_mode"))
        or "prompt_only",
        "response_format_type": _text(payload.get("response_format_type"))
        or "prompt_only",
        "reasoning_effort": _text(payload.get("reasoning_effort")),
        "reasoning_excluded": bool(payload.get("reasoning_excluded")),
        "malformed_kind": _text(payload.get("malformed_kind")),
        "input_tokens": int(payload.get("input_tokens") or 0),
        "output_tokens": int(payload.get("output_tokens") or 0),
        "reasoning_tokens": int(payload.get("reasoning_tokens") or 0),
    }


def _copy_optional_bool_flags(out: dict[str, Any], payload: Mapping[str, Any]) -> None:
    for key in (
        "valid_json",
        "schema_ok",
        "recoverable_json_shape",
        "sanitized_or_refusal_detected",
    ):
        if key in payload:
            out[key] = bool(payload.get(key))


def _llm_model_health_events_by_model(
    events: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    events_by_model: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for event in events:
        key = (_text(event.get("provider_id")), _text(event.get("model_id")))
        if key[0] and key[1]:
            events_by_model.setdefault(key, []).append(event)
    return events_by_model


def _consecutive_llm_health_failures(attempts: list[dict[str, Any]]) -> int:
    count = 0
    for attempt in attempts:
        if attempt.get("ok"):
            break
        count += 1
    return count


def _llm_model_health_status(latest: dict[str, Any] | None) -> str:
    if latest is None:
        return "stale"
    if latest.get("ok"):
        return "healthy"
    return "unhealthy"


def _llm_model_format_events(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        attempt
        for attempt in attempts
        if (
            "valid_json" in attempt
            or "schema_ok" in attempt
            or attempt.get("malformed_kind")
            or attempt.get("prompt_contract")
            or str(attempt.get("source") or "").startswith("format")
        )
    ]


def _llm_model_format_health(format_events: list[dict[str, Any]]) -> str:
    if not format_events:
        return "unmeasured"
    latest = format_events[0]
    if latest.get("recoverable_json_shape"):
        return "recoverable_mismatch"
    if latest.get("malformed_kind"):
        return "degraded"
    if latest.get("valid_json") is False or latest.get("schema_ok") is False:
        return "degraded"
    return "healthy"


def _llm_model_visible_output_health(latest: dict[str, Any] | None) -> str:
    if latest is None:
        return "unknown"
    if latest.get("ok") and int(latest.get("visible_chars") or 0) <= 0:
        return "empty"
    if int(latest.get("visible_chars") or 0) > 0:
        return "healthy"
    return "unknown"


def _llm_model_reasoning_budget_health(latest: dict[str, Any] | None) -> str:
    if latest is None:
        return "unknown"
    finish_reason = _text(latest.get("finish_reason")).lower()
    if finish_reason == "length":
        return "length_limited"
    if finish_reason:
        return "ok"
    return "unknown"


def _llm_model_workflow_health(format_events: list[dict[str, Any]]) -> str:
    workflow_events = [
        event for event in format_events if _text(event.get("workflow_id"))
    ]
    if not workflow_events:
        return "unmeasured"
    latest = workflow_events[0]
    if latest.get("recoverable_json_shape"):
        return "recoverable_mismatch"
    if (
        latest.get("valid_json") is False
        or latest.get("schema_ok") is False
        or latest.get("malformed_kind")
    ):
        return "degraded"
    return "healthy"


def _llm_model_operator_action(
    *,
    endpoint_health: str,
    format_health: str,
    visible_output_health: str,
    reasoning_budget_health: str,
    latest_failure_kind: str,
) -> str:
    if endpoint_health == "stale":
        return (
            "run a bounded model health check before trusting this model for automation"
        )
    if endpoint_health == "unhealthy":
        return f"fix provider endpoint health ({latest_failure_kind or 'unavailable'}) before using this model"
    if visible_output_health == "empty":
        return "increase output budget or disable this model for workflows that require visible structured output"
    if reasoning_budget_health == "length_limited":
        return "increase max_tokens or move strict-output workflows away from this length-limited model"
    if format_health == "recoverable_mismatch":
        return "keep endpoint health separate from strict contract health; add prompt/schema parser recovery or retest before widening automation"
    if format_health == "degraded":
        return "keep endpoint health separate from automation usefulness; review format failures before widening automation"
    if format_health == "unmeasured":
        return "run format-adherence probes before trusting this endpoint-healthy model for structured automation"
    return "model is currently usable for measured structured automation"


_LLM_STRUCTURED_OUTPUT_MODE_PREFERENCE: tuple[str, ...] = (
    "json_schema",
    "json_object",
    "prompt_only",
)


def _llm_contract_schema_name(contract: str) -> str:
    return f"{contract or 'strict_json'}/v1"


def _llm_event_mode(event: Mapping[str, Any]) -> str:
    return (
        _text(event.get("response_format_type") or event.get("structured_output_mode"))
        or "prompt_only"
    )


def _llm_format_event_unsupported_mode(event: Mapping[str, Any]) -> bool:
    failure = _text(event.get("failure_kind")).lower()
    error = _text(event.get("error")).lower()
    return (
        "unsupported_response_format" in failure
        or "unsupported" in failure
        and "response_format" in failure
        or "unsupported" in error
        and "response_format" in error
    )


def _llm_format_mode_status(*, success_count: int, unsupported_count: int) -> str:
    if success_count > 0:
        return "supported"
    if unsupported_count > 0:
        return "unsupported"
    return "failing"


def _llm_mode_evidence(events: list[dict[str, Any]]) -> dict[str, Any]:
    attempts = len(events)
    success_count = sum(1 for event in events if _llm_format_contract_passed(event))
    unsupported_count = sum(
        1 for event in events if _llm_format_event_unsupported_mode(event)
    )
    latest = events[0] if events else {}
    return {
        "status": _llm_format_mode_status(
            success_count=success_count, unsupported_count=unsupported_count
        ),
        "attempt_count": attempts,
        "success_count": success_count,
        "schema_ok_count": sum(1 for event in events if event.get("schema_ok") is True),
        "valid_json_count": sum(
            1 for event in events if event.get("valid_json") is True
        ),
        "unsupported_mode_errors": unsupported_count,
        "schema_ok_rate": _llm_attempt_rate(
            sum(1 for event in events if event.get("schema_ok") is True), attempts
        ),
        "success_rate": _llm_attempt_rate(success_count, attempts),
        "latest_checked_at": _text(latest.get("checked_at")),
        "latest_malformed_kind": _text(latest.get("malformed_kind")),
        "latest_failure_kind": _text(latest.get("failure_kind")),
        "latest_finish_reason": _text(latest.get("finish_reason")).lower(),
    }


def _llm_recommended_response_format_type(
    modes: Mapping[str, Mapping[str, Any]],
) -> str:
    for mode in _LLM_STRUCTURED_OUTPUT_MODE_PREFERENCE:
        if str((modes.get(mode) or {}).get("status") or "") == "supported":
            return mode
    return ""


def _llm_contract_capability_evidence(
    contract: str, events: list[dict[str, Any]]
) -> dict[str, Any]:
    by_mode: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_mode.setdefault(_llm_event_mode(event), []).append(event)
    modes = {
        mode: _llm_mode_evidence(mode_events) for mode, mode_events in by_mode.items()
    }
    return {
        "schema_contract_name": _llm_contract_schema_name(contract),
        "prompt_contract": contract,
        "attempt_count": len(events),
        "last_tested_at": _text((events[0] if events else {}).get("checked_at")),
        "recommended_response_format_type": _llm_recommended_response_format_type(
            modes
        ),
        "modes": modes,
    }


def _llm_model_structured_output_capabilities(
    events_by_model: Mapping[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for (provider_id, model_id), attempts in events_by_model.items():
        contract_events: dict[str, list[dict[str, Any]]] = {}
        for event in _llm_model_format_events(attempts):
            contract = _text(event.get("prompt_contract"))
            if not contract:
                continue
            contract_events.setdefault(contract, []).append(event)
        if not contract_events:
            continue
        key = f"{provider_id}:{model_id}"
        out[key] = {
            contract: _llm_contract_capability_evidence(contract, events)
            for contract, events in contract_events.items()
        }
    return out


_LLM_WORKFLOW_REQUIRED_CONTRACTS: dict[str, list[str]] = {
    "research_generation": ["candidate_json"],
    "paper_writing": ["markdown_fenced_json"],
    "research_review": ["strict_json"],
    "general_agent": ["strict_json"],
}


def _llm_workflow_required_contracts(workflow: Any) -> list[str]:
    workflow_id = _text(getattr(workflow, "workflow_id", ""))
    return list(_LLM_WORKFLOW_REQUIRED_CONTRACTS.get(workflow_id, ["strict_json"]))


def _latest_llm_format_event_for_contract(
    attempts: list[dict[str, Any]], contract: str
) -> dict[str, Any] | None:
    matching = [
        attempt
        for attempt in attempts
        if _text(attempt.get("prompt_contract")) == contract
    ]
    if not matching:
        return None
    for mode in _LLM_STRUCTURED_OUTPUT_MODE_PREFERENCE:
        for attempt in matching:
            if _llm_event_mode(attempt) == mode and _llm_format_contract_passed(
                attempt
            ):
                return attempt
    return matching[0]


def _llm_format_contract_passed(event: dict[str, Any] | None) -> bool:
    if not event:
        return False
    return (
        event.get("valid_json") is not False
        and event.get("schema_ok") is not False
        and not _text(event.get("malformed_kind"))
        and int(event.get("visible_chars") or 0) > 0
        and _text(event.get("finish_reason")).lower() != "length"
    )


def _unmeasured_llm_contract_result(contract: str) -> dict[str, Any]:
    return {
        "prompt_contract": contract,
        "status": "unmeasured",
        "malformed_kind": "",
        "finish_reason": "",
        "visible_chars": 0,
        "structured_output_mode": "",
        "response_format_type": "",
        "reasoning_effort": "",
        "reasoning_excluded": False,
    }


def _llm_contract_result_from_event(
    contract: str, event: dict[str, Any], *, passed: bool
) -> dict[str, Any]:
    return {
        "prompt_contract": contract,
        "status": "pass" if passed else "fail",
        "malformed_kind": _text(event.get("malformed_kind")),
        "finish_reason": _text(event.get("finish_reason")).lower(),
        "visible_chars": int(event.get("visible_chars") or 0),
        "checked_at": _text(event.get("checked_at")),
        "structured_output_mode": _text(event.get("structured_output_mode")),
        "response_format_type": _text(event.get("response_format_type")),
        "recoverable_json_shape": bool(event.get("recoverable_json_shape")),
        "reasoning_effort": _text(event.get("reasoning_effort")),
        "reasoning_excluded": bool(event.get("reasoning_excluded")),
    }


def _llm_contract_needs_token_budget(event: dict[str, Any]) -> bool:
    malformed_kind = _text(event.get("malformed_kind"))
    finish_reason = _text(event.get("finish_reason")).lower()
    visible_chars = int(event.get("visible_chars") or 0)
    return malformed_kind == "empty_visible_output" or (
        finish_reason == "length" and visible_chars <= 0
    )


def _llm_workflow_model_operator_recommendation(
    *,
    model_id: str,
    label: str,
    endpoint_health: str,
    recoverable_shape_failures: list[str],
    format_failures: list[str],
    token_budget_failures: list[str],
    missing_contracts: list[str],
) -> tuple[str, str]:
    name = label or model_id
    if endpoint_health != "healthy":
        return (
            "fix_endpoint",
            f"fix endpoint health before using {name} in this workflow",
        )
    if recoverable_shape_failures:
        contracts = ", ".join(recoverable_shape_failures)
        return (
            "repair_recoverable_shape",
            f"repair prompt/schema parser recovery for {name} on {contracts}; JSON was valid but not strict contract shape",
        )
    if format_failures:
        contracts = ", ".join(format_failures)
        return (
            "remove_for_contract",
            f"remove {name} from workflows requiring {contracts}; latest evidence is structurally unreliable",
        )
    if token_budget_failures:
        contracts = ", ".join(token_budget_failures)
        return (
            "increase_max_tokens_or_remove",
            f"increase max_tokens or remove {name} for {contracts} until visible structured output passes",
        )
    if missing_contracts:
        contracts = ", ".join(missing_contracts)
        return (
            "probe_required",
            f"run format probes for {contracts} before trusting {name} in this workflow",
        )
    return "usable", f"{name} passed required contract evidence for this workflow"


def _missing_llm_workflow_model_recommendation(
    model_id: str, required_contracts: list[str]
) -> dict[str, Any]:
    return {
        "model_id": model_id,
        "label": model_id,
        "recommendation": "missing_model",
        "operator_action": f"remove missing model {model_id} from this workflow pool",
        "required_contracts": required_contracts,
        "passed_contracts": [],
        "missing_contracts": required_contracts,
        "token_budget_failures": [],
        "recoverable_shape_failures": [],
        "format_failures": [],
        "contract_results": [],
    }


def _llm_workflow_model_recommendation(
    *,
    model_id: str,
    label: str,
    endpoint_health: str,
    required_contracts: list[str],
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    contract_results: list[dict[str, Any]] = []
    missing_contracts: list[str] = []
    token_budget_failures: list[str] = []
    recoverable_shape_failures: list[str] = []
    format_failures: list[str] = []
    passed_contracts: list[str] = []
    for contract in required_contracts:
        event = _latest_llm_format_event_for_contract(attempts, contract)
        if event is None:
            missing_contracts.append(contract)
            contract_results.append(_unmeasured_llm_contract_result(contract))
            continue
        passed = _llm_format_contract_passed(event)
        if passed:
            passed_contracts.append(contract)
        elif event.get("recoverable_json_shape"):
            recoverable_shape_failures.append(contract)
        elif _llm_contract_needs_token_budget(event):
            token_budget_failures.append(contract)
        else:
            format_failures.append(contract)
        contract_results.append(
            _llm_contract_result_from_event(contract, event, passed=passed)
        )
    recommendation, operator_action = _llm_workflow_model_operator_recommendation(
        model_id=model_id,
        label=label,
        endpoint_health=endpoint_health,
        recoverable_shape_failures=recoverable_shape_failures,
        format_failures=format_failures,
        token_budget_failures=token_budget_failures,
        missing_contracts=missing_contracts,
    )
    return {
        "model_id": model_id,
        "label": label or model_id,
        "recommendation": recommendation,
        "operator_action": operator_action,
        "required_contracts": required_contracts,
        "passed_contracts": passed_contracts,
        "missing_contracts": missing_contracts,
        "token_budget_failures": token_budget_failures,
        "recoverable_shape_failures": recoverable_shape_failures,
        "format_failures": format_failures,
        "contract_results": contract_results,
    }


def _llm_workflow_status_and_action(
    *,
    label: str,
    model_pool: list[str],
    usable_models: list[str],
    required_contracts: list[str],
) -> tuple[str, str]:
    if not model_pool:
        return "blocked", f"{label} has no configured model pool"
    if not usable_models:
        contracts = ", ".join(required_contracts)
        return (
            "blocked",
            f"no model in {label} has passed {contracts}; tune max_tokens, remove degraded models, or run missing probes",
        )
    if len(usable_models) == len(model_pool):
        return "healthy", f"{label} model pool has measured contract-compatible models"
    return (
        "needs_attention",
        f"prefer {usable_models[0]} for {label}; remove or tune degraded pool entries",
    )


def _recommended_llm_workflow_default(
    default_model: str, usable_models: list[str]
) -> str:
    if default_model in usable_models:
        return default_model
    if usable_models:
        return usable_models[0]
    return ""


def _llm_workflow_route_policy(
    *,
    usable_models: list[str],
    recommendations: list[dict[str, Any]],
    required_contracts: list[str],
) -> dict[str, Any]:
    if not usable_models:
        return {
            "mode": "observe_only",
            "production_route_mutation": False,
            "recommended_response_format_type": "",
            "status": "blocked",
            "reason": "no model has green persisted contract evidence",
        }
    preferred_model = usable_models[0]
    preferred = next(
        (
            item
            for item in recommendations
            if _text(item.get("model_id")) == preferred_model
        ),
        {},
    )
    contract_modes = {
        _text(result.get("prompt_contract")): _text(result.get("response_format_type"))
        for result in preferred.get("contract_results", [])
        if _text(result.get("prompt_contract")) in required_contracts
    }
    modes = [mode for mode in contract_modes.values() if mode]
    recommended_mode = (
        modes[0] if modes and all(mode == modes[0] for mode in modes) else ""
    )
    return {
        "mode": "observe_only",
        "production_route_mutation": False,
        "recommended_model": preferred_model,
        "recommended_response_format_type": recommended_mode,
        "required_contracts": required_contracts,
        "schema_contract_names": [
            _llm_contract_schema_name(contract) for contract in required_contracts
        ],
        "status": "evidence_ready" if recommended_mode else "needs_attention",
        "reason": (
            "persisted green evidence exists; production route remains unchanged until explicitly promoted"
            if recommended_mode
            else "usable model lacks explicit structured-output mode evidence"
        ),
    }


def _llm_workflow_recommendation(
    workflow: Any,
    *,
    model_rows: Mapping[str, dict[str, Any]],
    events_by_model: Mapping[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    workflow_id = _text(getattr(workflow, "workflow_id", ""))
    label = _text(getattr(workflow, "label", "")) or workflow_id
    model_pool = [
        _text(model_id)
        for model_id in getattr(workflow, "model_pool", [])
        if _text(model_id)
    ]
    required_contracts = _llm_workflow_required_contracts(workflow)
    recommendations: list[dict[str, Any]] = []
    usable_models: list[str] = []
    for model_id in model_pool:
        row = model_rows.get(model_id)
        if row is None:
            recommendations.append(
                _missing_llm_workflow_model_recommendation(model_id, required_contracts)
            )
            continue
        attempts = events_by_model.get((row["provider_id"], model_id), [])
        item = _llm_workflow_model_recommendation(
            model_id=model_id,
            label=_text(row.get("label")),
            endpoint_health=_text(row.get("endpoint_health")),
            required_contracts=required_contracts,
            attempts=attempts,
        )
        recommendations.append(item)
        if item["recommendation"] == "usable":
            usable_models.append(model_id)
    default_model = _text(getattr(workflow, "default_model", ""))
    status, operator_action = _llm_workflow_status_and_action(
        label=label,
        model_pool=model_pool,
        usable_models=usable_models,
        required_contracts=required_contracts,
    )
    return {
        "workflow_id": workflow_id,
        "label": label,
        "enabled": bool(getattr(workflow, "enabled", True)),
        "status": status,
        "required_contracts": required_contracts,
        "current_model_pool": model_pool,
        "current_default_model": default_model,
        "recommended_model_pool": usable_models,
        "recommended_default_model": _recommended_llm_workflow_default(
            default_model, usable_models
        ),
        "route_policy": _llm_workflow_route_policy(
            usable_models=usable_models,
            recommendations=recommendations,
            required_contracts=required_contracts,
        ),
        "operator_action": operator_action,
        "models": recommendations,
    }


def _llm_workflow_recommendations(
    settings: Any,
    *,
    models: list[dict[str, Any]],
    events_by_model: Mapping[tuple[str, str], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    model_rows = {_text(row.get("model_id")): row for row in models}
    return [
        _llm_workflow_recommendation(
            workflow, model_rows=model_rows, events_by_model=events_by_model
        )
        for workflow in getattr(settings, "workflows", [])
        if bool(getattr(workflow, "enabled", True))
    ]


def _llm_model_format_success_count(format_events: list[dict[str, Any]]) -> int:
    return sum(
        1
        for attempt in format_events
        if (
            attempt.get("valid_json") is not False
            and attempt.get("schema_ok") is not False
            and not attempt.get("malformed_kind")
        )
    )


def _llm_attempt_rate(success_count: int, attempt_count: int) -> float:
    if attempt_count <= 0:
        return 0.0
    return round(success_count / attempt_count, 3)


def _llm_model_health_counts(
    attempts: list[dict[str, Any]], format_events: list[dict[str, Any]]
) -> dict[str, Any]:
    success_count = sum(1 for attempt in attempts if attempt.get("ok"))
    format_success_count = _llm_model_format_success_count(format_events)
    return {
        "attempt_count": len(attempts),
        "success_count": success_count,
        "failure_count": len(attempts) - success_count,
        "format_attempt_count": len(format_events),
        "format_success_count": format_success_count,
        "consecutive_failures": _consecutive_llm_health_failures(attempts),
        "success_rate": _llm_attempt_rate(success_count, len(attempts)),
        "format_success_rate": _llm_attempt_rate(
            format_success_count, len(format_events)
        ),
        "empty_visible_output_count": sum(
            1
            for attempt in attempts
            if attempt.get("ok") and int(attempt.get("visible_chars") or 0) <= 0
        ),
        "length_finish_count": sum(
            1
            for attempt in attempts
            if _text(attempt.get("finish_reason")).lower() == "length"
        ),
        "recoverable_json_shape_count": sum(
            1 for attempt in format_events if attempt.get("recoverable_json_shape")
        ),
        "rate_limited_count": sum(
            1 for attempt in attempts if attempt.get("failure_kind") == "rate_limited"
        ),
        "timeout_count": sum(
            1 for attempt in attempts if attempt.get("failure_kind") == "timeout"
        ),
    }


def _llm_latest_model_health_fields(
    latest: dict[str, Any] | None, latest_format: dict[str, Any] | None
) -> dict[str, Any]:
    latest_payload = latest or {}
    latest_format_payload = latest_format or {}
    return {
        "latest": latest,
        "latest_checked_at": _text(latest_payload.get("checked_at")),
        "latest_failure_kind": _text(latest_payload.get("failure_kind")),
        "latest_latency_ms": int(latest_payload.get("latency_ms") or 0),
        "latest_status_code": int(latest_payload.get("status_code") or 0),
        "latest_finish_reason": _text(latest_payload.get("finish_reason")),
        "latest_visible_chars": int(latest_payload.get("visible_chars") or 0),
        "latest_preview": _text(latest_payload.get("response_preview_redacted"))[:240],
        "latest_prompt_contract": _text(latest_payload.get("prompt_contract")),
        "latest_structured_output_mode": _text(
            latest_payload.get("structured_output_mode")
        ),
        "latest_response_format_type": _text(
            latest_payload.get("response_format_type")
        ),
        "latest_reasoning_effort": _text(latest_payload.get("reasoning_effort")),
        "latest_reasoning_excluded": bool(latest_payload.get("reasoning_excluded")),
        "latest_format_checked_at": _text(latest_format_payload.get("checked_at")),
        "latest_recoverable_json_shape": bool(
            latest_format_payload.get("recoverable_json_shape")
        ),
        "latest_workflow_id": _text(latest_payload.get("workflow_id")),
        "latest_malformed_kind": _text(latest_payload.get("malformed_kind")),
    }


def _llm_model_health_row(
    model: Any,
    *,
    provider_labels: Mapping[str, str],
    events_by_model: Mapping[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    provider_id = _text(getattr(model, "provider_id", ""))
    model_id = _text(getattr(model, "model_id", ""))
    attempts = events_by_model.get((provider_id, model_id), [])
    latest = attempts[0] if attempts else None
    format_events = _llm_model_format_events(attempts)
    endpoint_health = _llm_model_health_status(latest)
    format_health = _llm_model_format_health(format_events)
    visible_output_health = _llm_model_visible_output_health(latest)
    reasoning_budget_health = _llm_model_reasoning_budget_health(latest)
    workflow_health = _llm_model_workflow_health(format_events)
    latest_failure_kind = _text((latest or {}).get("failure_kind"))
    latest_format = format_events[0] if format_events else None
    row = {
        "provider_id": provider_id,
        "provider_label": provider_labels.get(provider_id, provider_id),
        "model_id": model_id,
        "label": _text(getattr(model, "label", "")) or model_id,
        "enabled": True,
        "status": endpoint_health,
        "endpoint_health": endpoint_health,
        "format_health": format_health,
        "visible_output_health": visible_output_health,
        "reasoning_budget_health": reasoning_budget_health,
        "workflow_health": workflow_health,
        "operator_action": _llm_model_operator_action(
            endpoint_health=endpoint_health,
            format_health=format_health,
            visible_output_health=visible_output_health,
            reasoning_budget_health=reasoning_budget_health,
            latest_failure_kind=latest_failure_kind,
        ),
    }
    row.update(_llm_model_health_counts(attempts, format_events))
    row.update(_llm_latest_model_health_fields(latest, latest_format))
    return row


def llm_model_health_summary(
    store: ControlPlaneStore, settings: Any, *, limit: int = 250
) -> dict[str, Any]:
    rows = _event_rows_for_type(store, event_type=LLM_MODEL_TEST_EVENT, limit=limit)
    events = [_llm_model_health_payload(row) for row in rows]
    events_by_model = _llm_model_health_events_by_model(events)
    provider_labels = {
        provider.provider_id: provider.label
        for provider in getattr(settings, "providers", [])
    }
    models: list[dict[str, Any]] = []
    for model in getattr(settings, "models", []):
        if not bool(getattr(model, "enabled", True)):
            continue
        models.append(
            _llm_model_health_row(
                model,
                provider_labels=provider_labels,
                events_by_model=events_by_model,
            )
        )
    unhealthy_count = sum(1 for row in models if row["endpoint_health"] != "healthy")
    structurally_unhealthy_count = sum(
        1
        for row in models
        if row["format_health"] in {"degraded", "recoverable_mismatch"}
        or row["visible_output_health"] == "empty"
        or row["reasoning_budget_health"] == "length_limited"
    )
    workflow_recommendations = _llm_workflow_recommendations(
        settings, models=models, events_by_model=events_by_model
    )
    structured_output_capabilities = _llm_model_structured_output_capabilities(
        events_by_model
    )
    return {
        "ok": unhealthy_count == 0 and structurally_unhealthy_count == 0,
        "status": "healthy"
        if unhealthy_count == 0 and structurally_unhealthy_count == 0
        else "needs_attention",
        "model_count": len(models),
        "unhealthy_count": unhealthy_count,
        "structurally_unhealthy_count": structurally_unhealthy_count,
        "taxonomy": {
            "endpoint_health": "provider/model can return a response",
            "format_health": "model output satisfies measured structured-output contracts; recoverable_mismatch means valid JSON with a known repairable legacy shape",
            "workflow_health": "model satisfies measured workflow-specific prompt contracts; recoverable_mismatch means valid JSON with a known repairable legacy shape",
            "visible_output_health": "model returns non-empty visible content",
            "reasoning_budget_health": "model does not exhaust output budget before visible content",
            "structured_output_capabilities": "persisted per-provider/model/contract/mode evidence from bounded LLM format probes; unsupported modes are distinct from semantic/schema failures",
            "route_policy": "observe-only workflow recommendation; production routing is not mutated by this read model",
        },
        "models": models,
        "structured_output_capabilities": structured_output_capabilities,
        "workflow_recommendations": workflow_recommendations,
    }


def overview(
    store: ControlPlaneStore,
    *,
    active_limit: int = 5,
    event_limit: int = 10,
    worker_lanes: Sequence[Mapping[str, Any]] | None = None,
    flags: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    (
        counts,
        paper_counts,
        active,
        next_candidate,
        raw_queue_rows,
        raw_paper_rows,
        batched_parts,
    ) = _overview_row_sources(store, active_limit=active_limit, event_limit=event_limit)
    queue_rows = [summarize_queue_row(row) for row in raw_queue_rows]
    paper_rows = [summarize_paper_row(row) for row in raw_paper_rows]
    # Supabase batched overview intentionally trims raw_queue_rows to keep the
    # dashboard cheap. Active rows are fetched separately for the running-work
    # card, so include them in reconciled operator counts as well. The
    # reconciler deduplicates when an adapter returns the same active row in
    # both surfaces.
    operator_queue_rows = [*queue_rows, *active]
    operator_counts = operator_counts_from_rows([*operator_queue_rows, *paper_rows])
    operator_detail_counts = operator_detail_counts_from_rows(
        [*operator_queue_rows, *paper_rows]
    )
    blocked_attention_samples = blocked_attention_samples_from_rows(
        [*operator_queue_rows, *paper_rows]
    )
    raw_write_candidates = eligible_paper_draft_candidates(
        raw_queue_rows, raw_paper_rows
    )
    write_candidates, gate_rejected = _gated_write_candidates(raw_write_candidates)
    _sync_write_paper_operator_counts(
        operator_counts, operator_detail_counts, write_candidates
    )
    reconciled_queue_rows = _reconciled_operator_rows(queue_rows)
    raw_reconciled_queue_rows = _reconciled_operator_rows(raw_queue_rows)
    investigation_pipeline = _build_investigation_pipeline(
        reconciled_queue_rows, raw_reconciled_queue_rows
    )
    paper_pipeline = _build_paper_pipeline(
        write_candidates=write_candidates,
        gate_rejected=gate_rejected,
        raw_write_candidates=raw_write_candidates,
        operator_counts=operator_counts,
        operator_detail_counts=operator_detail_counts,
        paper_rows=paper_rows,
    )
    research_yield = _build_research_yield_panel(
        queue_rows=raw_queue_rows,
        paper_rows=paper_rows,
        paper_pipeline=paper_pipeline,
        investigation_pipeline=investigation_pipeline,
    )
    research_quality = _latest_research_quality_for_overview()
    events, next_cursor, has_more = _overview_events_page(
        store, batched_parts, event_limit=event_limit
    )
    top_actions = top_operator_actions(
        operator_counts=operator_counts,
        paper_pipeline=paper_pipeline,
        investigation_pipeline=investigation_pipeline,
        counts=counts,
        worker_lanes=worker_lanes,
        limit=3,
    )
    movement = movement_diagnosis(
        flags=flags,
        worker_lanes=worker_lanes,
        paper_pipeline=paper_pipeline,
    )
    primary_action = primary_operator_action(
        worker_lanes=worker_lanes, movement=movement
    )
    research_signal_quality = research_signal_quality_snapshot(research_quality)
    followup_alignment = _followup_scope_alignment(
        investigation_pipeline=investigation_pipeline,
        quality_snapshot=research_signal_quality,
    )
    if followup_alignment:
        research_signal_quality["followup_scope_alignment"] = followup_alignment
    research_signal_quality["research_output_readiness"] = (
        research_output_readiness_contract(
            research_signal_quality,
            flags=_flags_payload(flags),
            top_actions=top_actions,
        )
    )
    return {
        "counts": {
            **counts,
            "papers": paper_counts.get("all", 0),
        },
        "paper_counts": paper_counts,
        "operator_counts": operator_counts,
        "operator_detail_counts": operator_detail_counts,
        "blocked_attention_samples": blocked_attention_samples,
        "flags": _flags_payload(flags),
        "paper_pipeline": paper_pipeline,
        "research_yield": research_yield,
        "research_signal_quality": research_signal_quality,
        "provider_generation_attempts": provider_generation_attempt_summary(store),
        "investigation_pipeline": investigation_pipeline,
        "operator_model": {
            "source": "control_plane.read_models.operator_stage_for_record",
            "raw_state_note": "wake_ready/session_finished_ready are worker-delivery callbacks; paper polarity comes from decision artifacts and publication automation/finalization state.",
        },
        "top_actions": top_actions,
        "primary_operator_action": primary_action,
        "movement_diagnosis": movement,
        "active_items": active,
        "next_candidate": _overview_next_candidate(next_candidate),
        "recent_events": events,
        "recent_events_page": page_response(
            rows=events,
            next_cursor=next_cursor,
            has_more=has_more,
            page_size_value=page_size(event_limit),
            cursor="",
            filters={},
        ),
    }
