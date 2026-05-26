from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from enoch_control_plane.control_plane.state_contract import (
    PAPER_READINESS_BLOCKING_CLAIM_VERDICTS,
    PAPER_READINESS_CONTRACT,
    PAPER_READINESS_HARD_GATE_REQUIREMENTS,
    PAPER_READINESS_MATURITY_STATES,
    PAPER_READINESS_SCORE_FLOORS,
)

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
PAPER_READINESS_DECISION_FIELDS = (
    "maturity_state",
    "hard_gate",
    "claim_ledger",
    "scorecard",
    "next_transition",
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
            *PAPER_READINESS_DECISION_FIELDS,
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


def _has_paper_readiness_v2(payload: dict[str, Any]) -> bool:
    return any(
        key in payload
        for key in (
            "maturity_state",
            "hard_gate",
            "claim_ledger",
            "scorecard",
            "next_transition",
        )
    )


def _score(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _hard_gate_summary(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("hard_gate")
    hard_gate = raw if isinstance(raw, dict) else {}
    missing = [
        requirement
        for requirement in PAPER_READINESS_HARD_GATE_REQUIREMENTS
        if not truthy(hard_gate.get(requirement) or payload.get(requirement))
    ]
    return {
        "passed": not missing,
        "missing": missing,
        "requirements": list(PAPER_READINESS_HARD_GATE_REQUIREMENTS),
    }


def _claim_ledger_rows(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        claims = raw.get("claims")
        if isinstance(claims, list):
            return [item for item in claims if isinstance(item, dict)]
        return [raw]
    return []


def _claim_ledger_summary(payload: dict[str, Any]) -> dict[str, Any]:
    rows = _claim_ledger_rows(payload.get("claim_ledger"))
    verdicts = [_normal(row.get("verdict")) for row in rows if row.get("verdict")]
    central_rows = [row for row in rows if truthy(row.get("central"))]
    central_verdicts = [
        _normal(row.get("verdict")) for row in central_rows if row.get("verdict")
    ]
    blocking = sorted(
        {
            verdict
            for verdict in verdicts
            if verdict in PAPER_READINESS_BLOCKING_CLAIM_VERDICTS
        }
    )
    central_blocking = sorted(
        {
            verdict
            for verdict in central_verdicts
            if verdict in PAPER_READINESS_BLOCKING_CLAIM_VERDICTS
        }
    )
    return {
        "present": bool(rows),
        "claim_count": len(rows),
        "central_claim_count": len(central_rows),
        "verdicts": verdicts,
        "blocking_verdicts": blocking,
        "central_blocking_verdicts": central_blocking,
        "passed": bool(rows) and not central_blocking and not blocking,
    }


def _scorecard_summary(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("scorecard")
    scorecard = raw if isinstance(raw, dict) else {}
    below = [
        field
        for field, floor in PAPER_READINESS_SCORE_FLOORS.items()
        if _score(scorecard.get(field) or payload.get(field)) < floor
    ]
    return {
        "passed": not below,
        "below_floor": below,
        "floors": dict(PAPER_READINESS_SCORE_FLOORS),
        "scores": {
            field: _score(scorecard.get(field) or payload.get(field))
            for field in PAPER_READINESS_SCORE_FLOORS
        },
    }


def _missing_evidence(payload: dict[str, Any], hard_gate: dict[str, Any]) -> list[str]:
    raw = (
        payload.get("missing_evidence")
        or payload.get("missing_evidence_reasons")
        or payload.get("followup_required_evidence")
        or []
    )
    if isinstance(raw, str):
        values = split_numbered_list_text(raw)
    elif isinstance(raw, list):
        values = [part for item in raw for part in split_numbered_list_text(text(item))]
    else:
        values = []
    return [*values, *list(hard_gate.get("missing") or [])]


def _negative_nonpaper_decision(payload: dict[str, Any]) -> bool:
    return _normal(payload.get("project_decision")) in {
        "negative",
        "finalize_negative",
        "reject",
    } and _normal(payload.get("research_outcome")) not in {
        "useful_signal",
        "paper_positive",
        "positive",
    }


def _all_paper_gates_passed(
    hard_gate: dict[str, Any], claim_ledger: dict[str, Any], scorecard: dict[str, Any]
) -> bool:
    return bool(hard_gate["passed"] and claim_ledger["passed"] and scorecard["passed"])


def _has_paper_readiness_signal(
    hard_gate: dict[str, Any], claim_ledger: dict[str, Any], scorecard: dict[str, Any]
) -> bool:
    return bool(
        hard_gate["passed"] or claim_ledger["present"] or scorecard["scores"]["total"]
    )


def _readiness_state(
    payload: dict[str, Any],
    *,
    hard_gate: dict[str, Any],
    claim_ledger: dict[str, Any],
    scorecard: dict[str, Any],
    missing_evidence: list[str],
) -> str:
    requested = _normal(payload.get("maturity_state"))
    if _negative_nonpaper_decision(payload):
        return "archive_no_paper"
    if _all_paper_gates_passed(hard_gate, claim_ledger, scorecard):
        return "paper_ready"
    if missing_evidence and _normal(payload.get("research_outcome")) == "useful_signal":
        return "deepen_required"
    if missing_evidence and requested in {"analysis_ready", "paper_candidate"}:
        return "deepen_required" if requested == "analysis_ready" else "paper_candidate"
    if (
        truthy(payload.get("proxy_only"))
        or _normal(payload.get("maturity_state")) == "pilot_signal"
    ):
        return "pilot_signal"
    if requested in PAPER_READINESS_MATURITY_STATES:
        return requested
    if _has_paper_readiness_signal(hard_gate, claim_ledger, scorecard):
        return "paper_candidate"
    return "execution_complete"


def evaluate_paper_readiness_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Evaluate the project_decision_v2 paper-readiness contract.

    Legacy fields remain readable, but once a decision artifact supplies any v2
    paper-readiness field, only `paper_ready` may enter paper writing.
    """

    hard_gate = _hard_gate_summary(payload)
    claim_ledger = _claim_ledger_summary(payload)
    scorecard = _scorecard_summary(payload)
    missing_evidence = _missing_evidence(payload, hard_gate)
    maturity_state = _readiness_state(
        payload,
        hard_gate=hard_gate,
        claim_ledger=claim_ledger,
        scorecard=scorecard,
        missing_evidence=missing_evidence,
    )
    output_lane_by_state = {
        "paper_ready": "paper",
        "pilot_signal": "promising_signal",
        "deepen_required": "follow_up",
        "archive_no_paper": "archive",
        "execution_complete": "archive",
        "analysis_ready": "archive",
        "paper_candidate": "archive",
    }
    paper_ready = maturity_state == "paper_ready"
    return {
        "contract_version": PAPER_READINESS_CONTRACT["version"],
        "paper_ready": paper_ready,
        "maturity_state": maturity_state,
        "hard_gate": hard_gate,
        "claim_ledger": claim_ledger,
        "scorecard": scorecard,
        "missing_evidence": missing_evidence,
        "next_transition": payload.get("next_transition")
        or ("paper_pipeline.write_needed" if paper_ready else maturity_state),
        "output_lane": output_lane_by_state[maturity_state],
    }


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


def _paper_draft_gate_scan_readiness_v2(
    payload_by_source: dict[str, dict[str, Any]],
    values: list[tuple[str, str, str]],
) -> dict[str, Any] | None:
    v2_payloads = [
        (source, payload)
        for source, payload in payload_by_source.items()
        if _has_paper_readiness_v2(payload)
    ]
    if not v2_payloads:
        return None
    rejected: list[dict[str, Any]] = []
    for source, payload in v2_payloads:
        readiness = evaluate_paper_readiness_payload(payload)
        if readiness["paper_ready"]:
            return {
                "eligible": True,
                "reason": "project decision v2 is paper-ready",
                "source": source,
                "field": "maturity_state",
                "decision": readiness["maturity_state"],
                "values": values,
                "paper_readiness": readiness,
            }
        rejected.append(
            {
                "source": source,
                "maturity_state": readiness["maturity_state"],
                "missing_evidence": readiness["missing_evidence"],
                "hard_gate_missing": readiness["hard_gate"]["missing"],
                "blocking_claim_verdicts": readiness["claim_ledger"][
                    "blocking_verdicts"
                ],
                "scorecard_below_floor": readiness["scorecard"]["below_floor"],
            }
        )
    return {
        "eligible": False,
        "reason": "project decision v2 is not paper-ready",
        "source": v2_payloads[0][0],
        "field": "maturity_state",
        "decision": rejected[0]["maturity_state"],
        "values": values,
        "paper_readiness_rejections": rejected,
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
    payload_by_source = dict(_paper_decision_json_payloads(artifact_root))
    if not values and not payload_by_source:
        return {
            "eligible": False,
            "reason": "missing project decision artifact",
            "values": [],
        }

    primary = _paper_decision_primary_rows(values)

    if blocked := _paper_draft_gate_scan_primary_blocked(
        primary, payload_by_source, values
    ):
        return blocked
    if readiness_v2 := _paper_draft_gate_scan_readiness_v2(payload_by_source, values):
        return readiness_v2
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


def _summary_has_notion_url(summary: str) -> bool:
    for match in re.finditer(r"https://[^\s<>\"]+", summary):
        try:
            hostname = (urlparse(match.group(0)).hostname or "").lower()
        except ValueError:
            continue
        if hostname in {"notion.so", "www.notion.so"}:
            return True
    return False


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
    has_successor_url = bool(text(row.get("successor_notion_url"))) or (
        _summary_has_notion_url(summary)
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
