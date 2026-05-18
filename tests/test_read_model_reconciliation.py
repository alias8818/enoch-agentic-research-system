from __future__ import annotations

from hypothesis import given, settings, strategies as st

from enoch_control_plane.control_plane.read_models import operator_counts_from_rows, operator_detail_counts_from_rows
from enoch_control_plane.control_plane.state_contract import OperatorLane

safe_id = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="-_"),
    min_size=1,
    max_size=40,
).filter(lambda value: value.strip("-_"))


def _active_queue(project_id: str, run_id: str, **extra: object) -> dict[str, object]:
    return {
        "project_id": project_id,
        "project_name": project_id,
        "status": "awaiting_wake",
        "last_run_state": "awaiting_wake",
        "current_run_id": run_id,
        "next_action_hint": "await_callback",
        **extra,
    }


def _completed_draft_ready(project_id: str, run_id: str, **extra: object) -> dict[str, object]:
    return {
        "project_id": project_id,
        "project_name": project_id,
        "status": "completed",
        "last_run_state": "wake_ready",
        "current_run_id": run_id,
        "next_action_hint": "draft_paper_or_select_next_project",
        "decision_gate_state": "positive",
        **extra,
    }


def _paper(project_id: str, run_id: str, paper_id: str, **extra: object) -> dict[str, object]:
    return {
        "paper_id": paper_id,
        "project_id": project_id,
        "run_id": run_id,
        "paper_status": "publication_draft",
        "review_status": "finalized",
        "finalization_package_path": "package.json",
        "draft_markdown_path": "paper.md",
        "evidence_bundle_path": "evidence_bundle.json",
        "claim_ledger_path": "claim_ledger.json",
        "manifest_path": "paper_manifest.json",
        **extra,
    }


@given(project_id=safe_id, run_id=safe_id, stale_paper_id=safe_id)
@settings(max_examples=80)
def test_active_queue_row_survives_stale_related_paper_reference(project_id: str, run_id: str, stale_paper_id: str) -> None:
    row = _active_queue(project_id, run_id, related_paper_id=f"stale-{stale_paper_id}")

    counts = operator_counts_from_rows([row])
    detail = operator_detail_counts_from_rows([row])

    assert counts[OperatorLane.RUNNING.value] == 1
    assert counts["total_operator_items"] == 1
    assert detail["running"] == 1


@given(project_id=safe_id, run_id=safe_id, paper_id=safe_id)
@settings(max_examples=80)
def test_completed_queue_with_matching_live_related_paper_counts_as_paper_only(project_id: str, run_id: str, paper_id: str) -> None:
    paper_id = f"paper-{paper_id}"
    rows = [
        _completed_draft_ready(project_id, run_id, related_paper_id=paper_id),
        _paper(project_id, run_id, paper_id),
    ]

    counts = operator_counts_from_rows(rows)
    detail = operator_detail_counts_from_rows(rows)

    assert counts[OperatorLane.READY_TO_PUBLISH.value] == 1
    assert counts.get(OperatorLane.WRITE_PAPER.value, 0) == 0
    assert counts["total_operator_items"] == 1
    assert detail["ready_to_publish"] == 1
    assert "run_complete_draft_needed" not in detail


@given(project_id=safe_id, active_run_id=safe_id, completed_run_id=safe_id, paper_id=safe_id)
@settings(max_examples=80)
def test_active_queue_precedence_over_completed_duplicate_rows(project_id: str, active_run_id: str, completed_run_id: str, paper_id: str) -> None:
    rows = [
        _completed_draft_ready(project_id, completed_run_id, related_paper_id=f"paper-{paper_id}"),
        _active_queue(project_id, active_run_id),
    ]

    counts = operator_counts_from_rows(rows)
    detail = operator_detail_counts_from_rows(rows)

    assert counts[OperatorLane.RUNNING.value] == 1
    assert counts["total_operator_items"] == 1
    assert detail["running"] == 1
    assert "run_complete_draft_needed" not in detail


def test_active_queue_does_not_hide_same_project_attention_row() -> None:
    rows = [
        _active_queue("drift-project", "active-run"),
        {
            "project_id": "drift-project",
            "project_name": "drift-project",
            "status": "blocked",
            "last_run_state": "gate_error",
            "current_run_id": "blocked-run",
            "next_action_hint": "inspect_worker_gate_failure",
            "manual_review_required": True,
        },
    ]

    counts = operator_counts_from_rows(rows)
    detail = operator_detail_counts_from_rows(rows)

    assert counts[OperatorLane.RUNNING.value] == 1
    assert counts[OperatorLane.NEEDS_OPERATOR.value] == 1
    assert counts["needs_attention"] == 1
    assert counts["total_operator_items"] == 2
    assert detail["running"] == 1
    assert detail["blocked_needs_operator"] == 1


def test_operator_counts_match_detail_counts_for_mixed_lifecycle_rows() -> None:
    rows = [
        _active_queue("active-project", "active-run"),
        _completed_draft_ready("paper-project", "paper-run", related_paper_id="paper-1"),
        _paper("paper-project", "paper-run", "paper-1"),
        {"project_id": "queued-project", "status": "queued"},
        {"project_id": "blocked-project", "status": "blocked"},
        {"paper_id": "imported-paper", "project_id": "imported-project", "paper_status": "publication_draft", "corpus_imported": True},
    ]

    counts = operator_counts_from_rows(rows)
    detail = operator_detail_counts_from_rows(rows)

    assert counts[OperatorLane.RUNNING.value] == detail["running"] == 1
    assert counts[OperatorLane.READY_TO_PUBLISH.value] == detail["ready_to_publish"] == 1
    assert counts[OperatorLane.READY_QUEUE.value] == detail["idea_queued"] == 1
    assert counts[OperatorLane.NEEDS_OPERATOR.value] == detail["blocked_needs_operator"] == 1
    assert counts[OperatorLane.PUBLISHED.value] == detail["published"] == 1
    assert counts["needs_attention"] == 1
    assert counts["total_operator_items"] == 5





def test_useful_signal_precedence_over_duplicate_no_paper_rows() -> None:
    no_paper = {
        "project_id": "signal-project",
        "project_name": "signal-project",
        "status": "completed",
        "last_run_state": "wake_ready",
        "current_run_id": "old-run",
        "next_action_hint": "draft_paper_or_select_next_project",
        "decision_gate_state": "negative",
        "decision_summary": "unsupported",
    }
    useful_signal = {
        **no_paper,
        "current_run_id": "signal-run",
        "research_outcome": "useful_signal",
        "hypothesis_status": "mixed",
        "evidence_strength": "moderate",
        "bounded_paper_ready": False,
        "useful_signal_summary": "bounded local signal",
    }

    for rows in ([no_paper, useful_signal], [useful_signal, no_paper]):
        counts = operator_counts_from_rows(list(rows))
        detail = operator_detail_counts_from_rows(list(rows))

        assert counts[OperatorLane.USEFUL_SIGNAL.value] == 1
        assert counts["total_operator_items"] == 1
        assert detail["useful_signal"] == 1
        assert "run_complete_no_paper" not in detail




def test_compute_scale_blocked_precedence_over_duplicate_no_paper_rows() -> None:
    no_paper = {
        "project_id": "scale-project",
        "project_name": "scale-project",
        "status": "completed",
        "last_run_state": "wake_ready",
        "current_run_id": "old-run",
        "next_action_hint": "draft_paper_or_select_next_project",
        "decision_gate_state": "negative",
        "decision_summary": "unsupported",
    }
    scale_blocked = {
        **no_paper,
        "current_run_id": "scale-run",
        "research_outcome": "useful_signal",
        "hypothesis_status": "mixed",
        "evidence_strength": "moderate",
        "scale_limits": "requires multi-GPU full-scale validation",
        "bounded_paper_ready": False,
        "useful_signal_summary": "promising but larger scale",
    }

    for rows in ([no_paper, scale_blocked], [scale_blocked, no_paper]):
        counts = operator_counts_from_rows(list(rows))
        detail = operator_detail_counts_from_rows(list(rows))

        assert counts[OperatorLane.COMPUTE_SCALE_BLOCKED.value] == 1
        assert counts["total_operator_items"] == 1
        assert detail["compute_scale_blocked"] == 1
        assert "run_complete_no_paper" not in detail


def test_active_queue_summary_ignores_stale_related_paper_projection() -> None:
    from enoch_control_plane.control_plane.read_models import summarize_queue_row

    row = _active_queue(
        "active-project",
        "active-run",
        related_paper_id="old-paper",
        related_paper_status="publication_draft",
        related_review_status="finalized",
        related_finalization_package_path="package.json",
    )

    summary = summarize_queue_row(row)

    assert summary["operator_lane"] == OperatorLane.RUNNING.value
    assert summary["operator_detail_stage"] == "running"
    assert summary["operator_next_step"] == "Wait for worker callback or gate completion."

class _OverviewStore:
    def __init__(self, queue_rows: list[dict[str, object]], paper_rows: list[dict[str, object]]) -> None:
        self._queue_rows = queue_rows
        self._paper_rows = paper_rows

    def queue_counts_sql(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self._queue_rows:
            status = str(row.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
        return counts

    def paper_counts_sql(self) -> dict[str, int]:
        return {"all": len(self._paper_rows)}

    def active_items_sql(self, *, limit: int) -> list[dict[str, object]]:
        del limit
        return [row for row in self._queue_rows if row.get("status") in {"dispatching", "awaiting_wake", "running", "wake_received", "reconciling"}]

    def next_candidate_sql(self) -> dict[str, object] | None:
        for row in self._queue_rows:
            if row.get("status") == "queued":
                return row
        return None

    def operator_queue_rows_sql(self) -> list[dict[str, object]]:
        return self._queue_rows

    def operator_paper_rows_sql(self) -> list[dict[str, object]]:
        return self._paper_rows

    def event_page(self, **kwargs: object) -> tuple[list[dict[str, object]], None, bool]:
        del kwargs
        return [], None, False


def test_overview_operator_cards_match_reconciled_pipeline_counts(tmp_path) -> None:
    from enoch_control_plane.control_plane import read_models

    project_dir = tmp_path / "write-project"
    (project_dir / ".enoch").mkdir(parents=True)
    (project_dir / ".enoch" / "project_decision.json").write_text('{"project_decision":"finalize_positive"}\n', encoding="utf-8")
    queue_rows = [
        _active_queue("active-project", "active-run", related_paper_id="stale-paper"),
        _completed_draft_ready("write-project", "write-run", project_dir=str(project_dir)),
        _completed_draft_ready("paper-project", "paper-run", related_paper_id="paper-1"),
    ]
    paper_rows = [_paper("paper-project", "paper-run", "paper-1")]
    store = _OverviewStore(queue_rows, paper_rows)

    overview = read_models.overview(store)  # type: ignore[arg-type]

    assert overview["operator_counts"][OperatorLane.RUNNING.value] == 1
    assert overview["operator_counts"][OperatorLane.WRITE_PAPER.value] == overview["paper_pipeline"]["write_needed"] == 1
    assert overview["operator_counts"][OperatorLane.READY_TO_PUBLISH.value] == overview["paper_pipeline"]["publish_ready"] == 1
    assert overview["operator_counts"]["total_operator_items"] == 3
    assert overview["paper_pipeline"]["raw_completed_no_paper_candidates"] == 1
    assert overview["paper_pipeline"]["next_write_candidate"]["project_id"] == "write-project"


def test_overview_last_import_result_uses_same_import_predicate_as_published_count() -> None:
    from enoch_control_plane.control_plane import read_models

    paper_rows = [
        {
            "paper_id": "ledger-imported-paper",
            "project_id": "ledger-imported-project",
            "run_id": "ledger-imported-run",
            "paper_status": "publication_draft",
            "review_status": "finalized",
            "finalization_package_path": "package.json",
            "corpus_imported": False,
            "corpus_import_id": "ledger-import-1",
            "artifact_slug": "ledger-imported-paper",
            "corpus_imported_at": "2026-05-17T12:00:00Z",
        }
    ]
    store = _OverviewStore([], paper_rows)

    overview = read_models.overview(store)  # type: ignore[arg-type]

    assert overview["operator_counts"][OperatorLane.PUBLISHED.value] == 1
    assert overview["paper_pipeline"]["published_imported"] == 1
    assert overview["paper_pipeline"]["last_import_result"]["paper_id"] == "ledger-imported-paper"


def test_overview_investigation_pipeline_uses_reconciled_rows() -> None:
    from enoch_control_plane.control_plane import read_models

    stale_signal = {
        "project_id": "duplicate-signal",
        "project_name": "duplicate-signal",
        "status": "completed",
        "last_run_state": "wake_ready",
        "current_run_id": "old-signal-run",
        "next_action_hint": "draft_paper_or_select_next_project",
        "decision_gate_state": "negative",
        "research_outcome": "useful_signal",
        "hypothesis_status": "mixed",
        "evidence_strength": "moderate",
        "bounded_paper_ready": False,
        "useful_signal_summary": "older local signal",
    }
    newer_signal = {
        **stale_signal,
        "current_run_id": "newer-signal-run",
        "useful_signal_summary": "newer local signal",
    }
    store = _OverviewStore([stale_signal, newer_signal], [])

    overview = read_models.overview(store)  # type: ignore[arg-type]

    assert overview["operator_counts"][OperatorLane.USEFUL_SIGNAL.value] == 1
    assert overview["operator_counts"]["total_operator_items"] == 1
    assert overview["investigation_pipeline"]["useful_signals"] == 1


def test_completed_queue_with_same_run_paper_without_related_pointer_counts_as_paper_only() -> None:
    rows = [
        {
            "project_id": "paper-project",
            "project_name": "paper-project",
            "status": "completed",
            "last_run_state": "wake_ready",
            "current_run_id": "paper-run",
            "next_action_hint": "select_next_project",
        },
        _paper("paper-project", "paper-run", "paper-1"),
    ]

    counts = operator_counts_from_rows(rows)
    detail = operator_detail_counts_from_rows(rows)

    assert counts[OperatorLane.READY_TO_PUBLISH.value] == 1
    assert counts["total_operator_items"] == 1
    assert detail["ready_to_publish"] == 1
    assert "run_complete_no_paper" not in detail


def test_blocked_queue_row_with_same_run_paper_still_needs_attention() -> None:
    rows = [
        {
            "project_id": "blocked-paper-project",
            "project_name": "blocked-paper-project",
            "status": "blocked",
            "last_run_state": "gate_error",
            "current_run_id": "paper-run",
            "next_action_hint": "inspect_worker_gate_failure",
            "manual_review_required": True,
            "related_paper_id": "paper-1",
        },
        _paper("blocked-paper-project", "paper-run", "paper-1"),
    ]

    counts = operator_counts_from_rows(rows)
    detail = operator_detail_counts_from_rows(rows)

    assert counts[OperatorLane.NEEDS_OPERATOR.value] == 1
    assert counts[OperatorLane.READY_TO_PUBLISH.value] == 1
    assert counts["needs_attention"] == 1
    assert counts["total_operator_items"] == 2
    assert detail["blocked_needs_operator"] == 1
    assert detail["ready_to_publish"] == 1

class _BatchedOverviewStore(_OverviewStore):
    def overview_read_model_parts(self, *, active_limit: int, event_limit: int) -> dict[str, object]:
        del active_limit, event_limit
        return {
            "counts": self.queue_counts_sql(),
            "paper_counts": self.paper_counts_sql(),
            "active_items": self.active_items_sql(limit=10),
            "next_candidate": self.next_candidate_sql(),
            "raw_queue_rows": [],
            "raw_paper_rows": self.operator_paper_rows_sql(),
            "events_page": ([], None, False),
        }


def test_overview_batched_parts_count_active_items_even_when_raw_queue_is_trimmed() -> None:
    from enoch_control_plane.control_plane import read_models

    store = _BatchedOverviewStore([_active_queue("active-project", "active-run")], [])

    overview = read_models.overview(store)  # type: ignore[arg-type]

    assert overview["active_items"][0]["project_id"] == "active-project"
    assert overview["operator_counts"][OperatorLane.RUNNING.value] == 1
    assert overview["operator_counts"]["total_operator_items"] == 1
    assert overview["operator_detail_counts"]["running"] == 1


def test_queue_summary_uses_related_artifact_paths_without_exposing_them() -> None:
    from enoch_control_plane.control_plane.read_models import summarize_queue_row

    summary = summarize_queue_row({
        "project_id": "ready-project",
        "project_name": "Ready Project",
        "status": "completed",
        "last_run_state": "wake_ready",
        "current_run_id": "ready-run",
        "related_paper_id": "paper-ready",
        "related_paper_status": "publication_draft",
        "related_review_status": "finalized",
        "related_finalization_package_path": "package.json",
        "related_draft_markdown_path": "/private/projects/ready/paper.md",
        "related_evidence_bundle_path": "/private/projects/ready/evidence_bundle.json",
        "related_claim_ledger_path": "/private/projects/ready/claim_ledger.json",
        "related_manifest_path": "/private/projects/ready/paper_manifest.json",
    })

    assert summary["operator_lane"] == OperatorLane.READY_TO_PUBLISH.value
    assert summary["operator_detail_stage"] == "ready_to_publish"
    assert summary["related_artifact_paths_present"] == {
        "finalization_package_path": True,
        "draft_markdown_path": True,
        "evidence_bundle_path": True,
        "claim_ledger_path": True,
        "manifest_path": True,
    }
    for field in (
        "related_finalization_package_path",
        "related_draft_markdown_path",
        "related_evidence_bundle_path",
        "related_claim_ledger_path",
        "related_manifest_path",
    ):
        assert field not in summary


def test_run_summary_uses_related_artifact_paths_without_exposing_them() -> None:
    from enoch_control_plane.control_plane.read_models import summarize_run_row

    summary = summarize_run_row({
        "run_id": "ready-run",
        "project_id": "ready-project",
        "state": "wake_ready",
        "gate_state": "wake_ready",
        "related_paper_id": "paper-ready",
        "related_paper_status": "publication_draft",
        "related_review_status": "finalized",
        "related_finalization_package_path": "package.json",
        "related_draft_markdown_path": "/private/projects/ready/paper.md",
        "related_evidence_bundle_path": "/private/projects/ready/evidence_bundle.json",
        "related_claim_ledger_path": "/private/projects/ready/claim_ledger.json",
        "related_manifest_path": "/private/projects/ready/paper_manifest.json",
    })

    assert summary["operator_lane"] == OperatorLane.READY_TO_PUBLISH.value
    assert summary["operator_detail_stage"] == "ready_to_publish"
    assert summary["related_artifact_paths_present"] == {
        "finalization_package_path": True,
        "draft_markdown_path": True,
        "evidence_bundle_path": True,
        "claim_ledger_path": True,
        "manifest_path": True,
    }
    for field in (
        "related_finalization_package_path",
        "related_draft_markdown_path",
        "related_evidence_bundle_path",
        "related_claim_ledger_path",
        "related_manifest_path",
    ):
        assert field not in summary


def test_operator_counts_recompute_stale_operator_stage_fields_from_raw_lifecycle() -> None:
    row = {
        "project_id": "stale-stage-project",
        "project_name": "stale-stage-project",
        "status": "completed",
        "last_run_state": "wake_ready",
        "current_run_id": "stale-stage-run",
        "next_action_hint": "select_next_project",
        "operator_stage": OperatorLane.RUNNING.value,
        "operator_lane": OperatorLane.RUNNING.value,
        "operator_detail_stage": "running",
        "operator_attention": False,
    }

    counts = operator_counts_from_rows([row])
    detail = operator_detail_counts_from_rows([row])

    assert counts.get(OperatorLane.RUNNING.value, 0) == 0
    assert counts[OperatorLane.COMPLETE_NO_PAPER.value] == 1
    assert counts["total_operator_items"] == 1
    assert detail["run_complete_no_paper"] == 1
    assert "running" not in detail


def test_reconciliation_preserves_sanitized_ready_to_publish_queue_summary() -> None:
    from enoch_control_plane.control_plane.read_models import operator_stage_for_record, summarize_queue_row

    summary = summarize_queue_row({
        "project_id": "sanitized-ready-project",
        "project_name": "Sanitized Ready Project",
        "status": "completed",
        "last_run_state": "wake_ready",
        "current_run_id": "sanitized-ready-run",
        "related_paper_id": "paper-ready",
        "related_paper_status": "publication_draft",
        "related_review_status": "finalized",
        "related_finalization_package_path": "package.json",
        "related_draft_markdown_path": "/private/projects/ready/paper.md",
        "related_evidence_bundle_path": "/private/projects/ready/evidence_bundle.json",
        "related_claim_ledger_path": "/private/projects/ready/claim_ledger.json",
        "related_manifest_path": "/private/projects/ready/paper_manifest.json",
    })
    paper_summary = _paper("sanitized-ready-project", "sanitized-ready-run", "paper-ready")

    recomputed_stage = operator_stage_for_record(summary)
    counts = operator_counts_from_rows([summary, paper_summary])
    detail = operator_detail_counts_from_rows([summary, paper_summary])

    assert recomputed_stage["operator_detail_stage"] == "ready_to_publish"
    assert counts[OperatorLane.READY_TO_PUBLISH.value] == 1
    assert counts["total_operator_items"] == 1
    assert detail["ready_to_publish"] == 1


def test_reconciliation_preserves_sanitized_ready_to_publish_paper_summary() -> None:
    from enoch_control_plane.control_plane.read_models import summarize_paper_row

    summary = summarize_paper_row(_paper("paper-project", "paper-run", "paper-1"))

    counts = operator_counts_from_rows([summary])
    detail = operator_detail_counts_from_rows([summary])

    assert counts[OperatorLane.READY_TO_PUBLISH.value] == 1
    assert counts["total_operator_items"] == 1
    assert detail["ready_to_publish"] == 1
