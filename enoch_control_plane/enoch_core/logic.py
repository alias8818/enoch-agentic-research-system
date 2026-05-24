from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ACTIVE_QUEUE_STATUSES = {
    "dispatching",
    "awaiting_wake",
    "running",
    "wake_received",
    "reconciling",
}
WAKE_GATE_PAPER_STATES = {"wake_ready", "session_finished_ready"}
PAPER_DRAFT_NEXT_ACTION = "draft_paper_or_select_next_project"
EXCLUDED_DRAFT_NAME_FRAGMENT = (
    "human-validated",
    "human label",
    "human annotation",
    "human rater",
    "reviewer noise",
)
# Keep this intentionally narrow. Near-synonyms such as
# ``partial_viable`` or ``promising_synthetic_positive`` are useful research
# notes, but they are not canonical paper-positive decisions. They must not
# create operator-visible ``write_needed`` work.
PAPER_DRAFT_POSITIVE_DECISION_TOKENS = ("finalize_positive",)
PAPER_DRAFT_BLOCKED_DECISION_TOKENS = (
    "negative",
    "non_positive",
    "not_positive",
    "nonpositive",
    "not_promising",
    "do_not",
    "reject",
    "inconclusive",
    "needs_review",
    "proceed_with_caveats",
    "conditional_go_pilot",
)
PAPER_DECISION_FILES = (
    ".enoch/project_decision.json",
    ".omx/project_decision.json",
    "project_decision.json",
)
PAPER_PRIMARY_DECISION_FIELDS = (
    "project_decision",
    "decision",
    "verdict",
    "outcome",
    "recommendation",
)
PAPER_SUPPORTING_DECISION_FIELDS = ("hypothesis_status", "status")
PAPER_USEFUL_SIGNAL_FIELDS = (
    "research_outcome",
    "bounded_paper_ready",
    "claim_scope",
    "scale_limits",
    "useful_signal_summary",
    "compute_scale_blocked",
)
# Worker-produced artifacts are untrusted. Decision files should be tiny JSON
# documents, so cap reads to avoid control-plane CPU/memory exhaustion.
MAX_PAPER_DECISION_BYTES = 64 * 1024


def text(value: Any) -> str:
    return str(value or "").strip()


def split_numbered_list_text(value: str) -> list[str]:
    raw = text(value)
    if not raw:
        return []
    markers = list(re.finditer(r"(?<!\S)\d+\.\s+", raw))
    if len(markers) < 2:
        return [item.strip() for item in re.split(r"[\n;]+", raw) if item.strip()]
    items: list[str] = []
    for index, marker in enumerate(markers):
        start = marker.end()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(raw)
        item = raw[start:end].strip()
        if item:
            items.append(item)
    return items


def truthy(value: Any) -> bool:
    return value is True or value in {1, "1", "true", "True", "TRUE"}


def integer(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normal(value: Any) -> str:
    return text(value).lower().replace("-", "_").replace(" ", "_")


def _decision_tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", value) if token}


def _has_decision_token(value: str, tokens: tuple[str, ...]) -> bool:
    token_set = set(tokens)
    return value in token_set or bool(_decision_tokens(value) & token_set)


def _safe_decision_file(path: Path) -> bool:
    try:
        return path.exists() and path.is_file() and not path.is_symlink()
    except OSError:
        return False


def _read_decision_json(path: Path) -> dict[str, Any] | None:
    if not _safe_decision_file(path):
        return None
    try:
        if path.stat().st_size > MAX_PAPER_DECISION_BYTES:
            return None
        with path.open("rb") as handle:
            raw = handle.read(MAX_PAPER_DECISION_BYTES + 1)
    except OSError:
        return None
    if len(raw) > MAX_PAPER_DECISION_BYTES:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _paper_decision_json_values(
    artifact_root: str | Path,
) -> list[tuple[str, str, str]]:
    root = Path(artifact_root)
    values: list[tuple[str, str, str]] = []
    for relative in PAPER_DECISION_FILES:
        path = root / relative
        payload = _read_decision_json(path)
        if payload is None:
            continue
        for field in (
            *PAPER_PRIMARY_DECISION_FIELDS,
            *PAPER_SUPPORTING_DECISION_FIELDS,
            *PAPER_USEFUL_SIGNAL_FIELDS,
        ):
            if field in payload:
                values.append((relative, field, text(payload.get(field))))
    return values


def _paper_decision_json_payloads(
    artifact_root: str | Path,
) -> list[tuple[str, dict[str, Any]]]:
    root = Path(artifact_root)
    payloads: list[tuple[str, dict[str, Any]]] = []
    for relative in PAPER_DECISION_FILES:
        path = root / relative
        payload = _read_decision_json(path)
        if payload is not None:
            payloads.append((relative, payload))
    return payloads


def _bounded_useful_signal_ready(payload: dict[str, Any]) -> bool:
    """Return whether a useful-signal result is scoped enough for a bounded paper.

    This is deliberately narrower than "promising." It admits local-hardware
    useful signals only when the worker explicitly scopes the claim, names the
    scale limits, and marks the bounded paper as ready. Unsupported/proxy-only
    notes remain no-paper unless the artifact makes that scoped claim explicit.
    """

    outcome = _normal(payload.get("research_outcome"))
    if outcome not in {"useful_signal", "paper_positive"}:
        return False
    if not truthy(payload.get("bounded_paper_ready")):
        return False
    if _normal(payload.get("hypothesis_status")) not in {"supported", "mixed"}:
        return False
    if _normal(payload.get("evidence_strength")) not in {"moderate", "strong"}:
        return False
    if not text(payload.get("claim_scope")):
        return False
    if not text(payload.get("scale_limits")):
        return False
    return True


def bounded_useful_signal_row_gate(row: dict[str, Any]) -> dict[str, Any]:
    """Return a paper gate result for DB-scoped useful-signal rows.

    Paper-scout review can mark a completed no-paper row as
    ``bounded_paper_ready`` in the control-plane database without rewriting the
    worker artifact. The draft endpoint must honor that bounded review state;
    otherwise the dashboard can show write-needed candidates that the draft
    writer can never consume.
    """

    payload = {
        "project_decision": row.get("project_decision")
        or row.get("decision_gate_state")
        or row.get("last_run_state"),
        "research_outcome": row.get("research_outcome"),
        "bounded_paper_ready": row.get("bounded_paper_ready"),
        "hypothesis_status": row.get("hypothesis_status"),
        "evidence_strength": row.get("evidence_strength"),
        "claim_scope": row.get("claim_scope"),
        "scale_limits": row.get("scale_limits"),
    }
    if not _bounded_useful_signal_ready(payload):
        return {
            "eligible": False,
            "reason": "row is not a bounded useful-signal paper candidate",
            "research_outcome": text(payload.get("research_outcome")),
            "bounded_paper_ready": truthy(payload.get("bounded_paper_ready")),
        }
    return {
        "eligible": True,
        "reason": "bounded useful signal is paper-scoped",
        "source": "control_plane_row",
        "field": "bounded_paper_ready",
        "decision": text(payload.get("project_decision")),
        "research_outcome": text(payload.get("research_outcome")),
        "claim_scope": text(payload.get("claim_scope")),
        "scale_limits": text(payload.get("scale_limits")),
    }


def project_decision_payload(artifact_root: str | Path) -> dict[str, Any]:
    """Return the first parseable project decision JSON payload for follow-up metadata."""

    root = Path(artifact_root)
    for relative in PAPER_DECISION_FILES:
        path = root / relative
        payload = _read_decision_json(path)
        if payload is not None:
            return payload
    return {}


def followup_candidate_from_decision_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize optional follow-up metadata from a worker decision artifact."""

    if not isinstance(payload, dict):
        return {"followup_recommended": False}
    raw_type = _normal(payload.get("followup_type"))
    followup_type = raw_type if raw_type in {"deepen", "branch", "retry"} else ""
    required = payload.get("followup_required_evidence")
    if isinstance(required, str):
        required_evidence = split_numbered_list_text(required)
    elif isinstance(required, list):
        required_evidence = [
            part
            for item in required
            for part in split_numbered_list_text(text(item))
            if part
        ]
    else:
        required_evidence = []
    return {
        "followup_recommended": truthy(payload.get("followup_recommended")),
        "followup_type": followup_type,
        "followup_title": text(payload.get("followup_title")),
        "followup_hypothesis": text(payload.get("followup_hypothesis")),
        "followup_required_evidence": required_evidence,
        "followup_success_threshold": text(payload.get("followup_success_threshold")),
        "followup_stop_condition": text(payload.get("followup_stop_condition")),
    }


def _paper_decision_primary_rows(
    values: list[tuple[str, str, str]],
) -> list[tuple[str, str, str]]:
    return [
        (source, field, _normal(value))
        for source, field, value in values
        if field in PAPER_PRIMARY_DECISION_FIELDS
    ]


def _paper_draft_gate_blocked_primary(
    *,
    source: str,
    field: str,
    value: str,
    payload: dict[str, Any],
    values: list[tuple[str, str, str]],
) -> dict[str, Any]:
    if _bounded_useful_signal_ready(payload):
        return {
            "eligible": True,
            "reason": "bounded useful signal is paper-scoped",
            "source": source,
            "field": field,
            "decision": value,
            "values": values,
            "research_outcome": text(payload.get("research_outcome")),
            "claim_scope": text(payload.get("claim_scope")),
            "scale_limits": text(payload.get("scale_limits")),
        }
    return {
        "eligible": False,
        "reason": "project decision is not positive",
        "source": source,
        "field": field,
        "decision": value,
        "values": values,
    }


def _paper_draft_gate_positive_primary(
    *,
    source: str,
    field: str,
    value: str,
    payload: dict[str, Any],
    values: list[tuple[str, str, str]],
) -> dict[str, Any]:
    if _normal(
        payload.get("research_outcome")
    ) == "useful_signal" and not _bounded_useful_signal_ready(payload):
        return {
            "eligible": False,
            "reason": "useful signal is not bounded paper-ready",
            "source": source,
            "field": field,
            "decision": value,
            "values": values,
            "research_outcome": text(payload.get("research_outcome")),
            "bounded_paper_ready": truthy(payload.get("bounded_paper_ready")),
        }
    return {
        "eligible": True,
        "reason": "project decision is positive",
        "source": source,
        "field": field,
        "decision": value,
        "values": values,
    }


def _paper_draft_gate_scan_primary_blocked(
    primary: list[tuple[str, str, str]],
    payload_by_source: dict[str, dict[str, Any]],
    values: list[tuple[str, str, str]],
) -> dict[str, Any] | None:
    for source, field, value in primary:
        if not _has_decision_token(value, PAPER_DRAFT_BLOCKED_DECISION_TOKENS):
            continue
        payload = payload_by_source.get(source) or {}
        return _paper_draft_gate_blocked_primary(
            source=source,
            field=field,
            value=value,
            payload=payload,
            values=values,
        )
    return None


def _paper_draft_gate_scan_primary_positive(
    primary: list[tuple[str, str, str]],
    payload_by_source: dict[str, dict[str, Any]],
    values: list[tuple[str, str, str]],
) -> dict[str, Any] | None:
    for source, field, value in primary:
        if not _has_decision_token(value, PAPER_DRAFT_POSITIVE_DECISION_TOKENS):
            continue
        payload = payload_by_source.get(source) or {}
        return _paper_draft_gate_positive_primary(
            source=source,
            field=field,
            value=value,
            payload=payload,
            values=values,
        )
    return None


def _paper_draft_gate_continue_primary(
    primary: list[tuple[str, str, str]],
    values: list[tuple[str, str, str]],
) -> dict[str, Any] | None:
    if not any(value == "continue" for _, _, value in primary):
        return None
    source, field, value = next(
        (item for item in primary if item[2] == "continue"),
        primary[0],
    )
    return {
        "eligible": False,
        "reason": "continue decision is not paper-positive",
        "source": source,
        "field": field,
        "decision": value,
        "values": values,
    }


def paper_draft_decision_gate(artifact_root: str | Path) -> dict[str, Any]:
    """Return whether local project decision artifacts support paper drafting.

    The worker callback state only says the worker is done and the controller
    may either draft or move on. The actual draft/no-draft polarity lives in the
    project decision artifact. Keep this intentionally conservative for primary
    decision fields so negative, needs-review, and caveat-only outcomes do not
    become publication drafts merely because the worker session completed.
    """
    values = _paper_decision_json_values(artifact_root)
    if not values:
        return {
            "eligible": False,
            "reason": "missing project decision artifact",
            "values": [],
        }

    payload_by_source = dict(_paper_decision_json_payloads(artifact_root))
    primary = _paper_decision_primary_rows(values)

    if blocked := _paper_draft_gate_scan_primary_blocked(
        primary, payload_by_source, values
    ):
        return blocked
    if positive := _paper_draft_gate_scan_primary_positive(
        primary, payload_by_source, values
    ):
        return positive
    if continue_result := _paper_draft_gate_continue_primary(primary, values):
        return continue_result

    return {
        "eligible": False,
        "reason": "project decision lacks positive draft signal",
        "values": values,
    }


def queue_status_counts(queue_rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(text(row.get("status")) or "unknown" for row in queue_rows))


def run_state_counts(queue_rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(
        Counter(text(row.get("last_run_state")) or "unknown" for row in queue_rows)
    )


def active_queue_rows(queue_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row for row in queue_rows if text(row.get("status")) in ACTIVE_QUEUE_STATUSES
    ]


def assert_single_active_lane(queue_rows: list[dict[str, Any]]) -> tuple[bool, str]:
    active = active_queue_rows(queue_rows)
    if len(active) <= 1:
        return True, "zero or one active GB10 lane row"
    names = ", ".join(
        text(row.get("project_name")) or text(row.get("project_id"))
        for row in active[:5]
    )
    return False, f"multiple active GB10 lane rows: {names}"


def validate_branch_queued(row: dict[str, Any]) -> tuple[bool, str]:
    if (
        text(row.get("next_action_hint")) != "branch_queued"
        and text(row.get("last_run_state")) != "branch_queued"
    ):
        return True, "not a branch_queued row"
    summary = text(row.get("last_result_summary"))
    has_successor_id = bool(
        text(row.get("successor_project_id"))
        or re.search(r"\bidea-[0-9a-f]{8,}\b", summary)
    )
    has_successor_url = bool(
        text(row.get("successor_notion_url")) or "https://www.notion.so/" in summary
    )
    if has_successor_id and has_successor_url:
        return True, "branch_queued has concrete successor evidence"
    return (
        False,
        "branch_queued requires successor project_id and notion_page_url evidence",
    )


def _drafted_sets(paper_rows: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    project_ids = {
        text(row.get("project_id")) for row in paper_rows if text(row.get("project_id"))
    }
    run_ids = {text(row.get("run_id")) for row in paper_rows if text(row.get("run_id"))}
    return project_ids, run_ids


def eligible_paper_draft_candidates(
    queue_rows: list[dict[str, Any]],
    paper_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    drafted_project_ids, drafted_run_ids = _drafted_sets(paper_rows)

    def excluded(row: dict[str, Any]) -> bool:
        haystack = "\n".join(
            [
                text(row.get("project_name")),
                text(row.get("last_result_summary")),
                text(row.get("blocked_reason")),
            ]
        ).lower()
        return any(
            fragment in haystack for fragment in EXCLUDED_DRAFT_NAME_FRAGMENT
        ) or ("benchmark" in haystack and "human" in haystack)

    def draft_ready(row: dict[str, Any]) -> bool:
        last_run_state = text(row.get("last_run_state"))
        if last_run_state == "finalize_positive":
            return True
        return (
            last_run_state in WAKE_GATE_PAPER_STATES
            and text(row.get("next_action_hint")) == PAPER_DRAFT_NEXT_ACTION
            and bool(text(row.get("current_run_id")) or text(row.get("run_id")))
            and bool(
                text(row.get("project_dir"))
                or text(row.get("notion_page_url"))
                or text(row.get("last_result_summary"))
            )
        )

    candidates = [
        row
        for row in queue_rows
        if text(row.get("project_id"))
        and text(row.get("status")) == "completed"
        and draft_ready(row)
        and not truthy(row.get("manual_review_required"))
        and text(row.get("project_id")) not in drafted_project_ids
        and text(row.get("current_run_id") or row.get("run_id")) not in drafted_run_ids
        and not excluded(row)
    ]
    return sorted(
        candidates,
        key=lambda row: (
            1 if truthy(row.get("bounded_paper_ready")) else 0,
            text(row.get("updatedAt"))
            or text(row.get("last_callback_at"))
            or text(row.get("last_dispatch_at")),
            -integer(row.get("dispatch_priority"), 9999),
        ),
        reverse=True,
    )


def draft_candidate_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    run_id = text(candidate.get("current_run_id") or candidate.get("run_id"))
    return {
        "project_id": text(candidate.get("project_id")),
        "project_name": text(candidate.get("project_name"))
        or text(candidate.get("project_id")),
        "run_id": run_id,
        "notion_page_url": text(candidate.get("notion_page_url")),
        "project_dir": text(candidate.get("project_dir")),
        "draft_payload": {
            "project_id": text(candidate.get("project_id")),
            "run_id": run_id,
            "paper_type": "arxiv_draft",
            "force": False,
        },
    }


def _publication_ids(paper_rows: list[dict[str, Any]]) -> set[str]:
    return {
        text(row.get("paper_id"))
        for row in paper_rows
        if text(row.get("paper_status")) == "publication_draft"
        or text(row.get("paper_type")).startswith("publication")
    }


def eligible_paper_polish_candidates(
    paper_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    publication_ids = _publication_ids(paper_rows)
    candidates = [
        row
        for row in paper_rows
        if text(row.get("paper_status")) == "draft_review"
        and text(row.get("project_id"))
        and text(row.get("paper_id"))
        and text(row.get("draft_markdown_path"))
        and text(row.get("evidence_bundle_path"))
        and text(row.get("claim_ledger_path"))
        and text(row.get("manifest_path"))
        and f"{text(row.get('paper_id'))}:publication_v1" not in publication_ids
    ]
    return sorted(
        candidates,
        key=lambda row: text(row.get("updated_at")) or text(row.get("generated_at")),
        reverse=True,
    )


def polish_candidate_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "paper_id": text(candidate.get("paper_id")),
        "project_id": text(candidate.get("project_id")),
        "project_name": text(candidate.get("project_name"))
        or text(candidate.get("project_id")),
        "run_id": text(candidate.get("run_id")),
        "draft_markdown_path": text(candidate.get("draft_markdown_path")),
        "polish_payload": {
            "paper_id": text(candidate.get("paper_id")),
            "force": False,
            "model_id": "deterministic_template_v1",
        },
    }


def queue_projection(snapshot: dict[str, Any]) -> dict[str, Any]:
    queue_rows = list(snapshot.get("queue_rows") or [])
    paper_rows = list(snapshot.get("paper_rows") or [])
    single_active_ok, single_active_message = assert_single_active_lane(queue_rows)
    warnings = [] if single_active_ok else [single_active_message]
    return {
        "source": text(snapshot.get("source")),
        "captured_at": snapshot.get("captured_at"),
        "total_queue_rows": len(queue_rows),
        "total_paper_rows": len(paper_rows),
        "status_counts": queue_status_counts(queue_rows),
        "run_state_counts": run_state_counts(queue_rows),
        "active_rows": active_queue_rows(queue_rows),
        "draft_candidate_count": len(
            eligible_paper_draft_candidates(queue_rows, paper_rows)
        ),
        "polish_candidate_count": len(eligible_paper_polish_candidates(paper_rows)),
        "warnings": warnings,
    }
