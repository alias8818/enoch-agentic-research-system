from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts import research_facility


def _args(**overrides: object) -> argparse.Namespace:
    base = {
        "default_machine": "192.168.1.77",
        "default_model": "gpt-5.5",
        "default_sandbox": "danger-full-access",
        "admit_threshold": 72.0,
        "review_threshold": 58.0,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _strong_candidate(**overrides: object) -> dict[str, object]:
    candidate: dict[str, object] = {
        "candidate_id": "ssm-anchor-memory-test",
        "generation_mode": "fresh_grounded",
        "title": "SSM Anchor Memory Test",
        "category": "long-context",
        "priority": "High",
        "source_kind": "arxiv",
        "source_urls": ["https://arxiv.org/abs/2401.00000"],
        "hypothesis": "Sparse exact anchors plus recurrent state improve long-context recall on local hardware.",
        "mechanism": "Store SSM state summaries and exact anchors, then retrieve with query-conditioned scoring.",
        "description": "A bounded long-context experiment.",
        "implementation": "Run synthetic multi-needle and multi-hop tasks against RAG and sliding-window baselines.",
        "baseline_to_beat": "Vector RAG and periodic exact-anchor baselines.",
        "success_threshold": "Beat vector RAG by 10 points at 256k context under a 2 percent memory budget.",
        "kill_condition": "Stop if anchors alone explain all gains or accuracy is below baseline.",
        "accessibility_delta": "Could make million-token style workflows viable for home GPUs.",
        "expected_artifacts": ["run_notes.md", "metrics.json", ".omx/project_decision.json"],
        "required_evidence": ["baseline comparison", "memory budget", "failure cases"],
        "likely_failure_modes": ["anchor overfit", "state smearing"],
        "novelty_score": 9,
        "feasibility_score": 8,
        "accessibility_score": 9,
        "falsifiability_score": 9,
    }
    candidate.update(overrides)
    return candidate


def test_research_facility_admits_only_contract_complete_grounded_candidates() -> None:
    plan = research_facility.plan_candidates([_strong_candidate()], _args())[0]

    assert plan.admission_decision == "admitted"
    assert plan.admitted_idea_id == "ssm-anchor-memory-test"
    assert plan.candidate["status"] == "admitted"
    assert plan.candidate["total_score"] >= 72
    assert plan.hard_failures == []


def test_research_facility_rejects_fresh_grounded_without_source() -> None:
    plan = research_facility.plan_candidates([_strong_candidate(source_urls=[])], _args())[0]

    assert plan.admission_decision == "rejected"
    assert "fresh_grounded requires source_ids or source_urls" in plan.hard_failures


def test_research_facility_rejects_followup_without_parent_lineage() -> None:
    plan = research_facility.plan_candidates(
        [_strong_candidate(generation_mode="followup_from_negative", source_urls=[])],
        _args(),
    )[0]

    assert plan.admission_decision == "rejected"
    assert "followup_from_negative requires parent_project_id or parent_run_id" in plan.hard_failures


def test_research_facility_requires_novelty_comparison_for_similar_prior_projects() -> None:
    plan = research_facility.plan_candidates(
        [_strong_candidate(similar_prior_projects=["old-negative"], novelty_comparison="")],
        _args(),
    )[0]

    assert plan.admission_decision == "rejected"
    assert "similar_prior_projects requires novelty_comparison" in plan.hard_failures


def test_research_facility_emits_auditable_ledgers_and_optional_queue_sql() -> None:
    plan = research_facility.plan_candidates([_strong_candidate()], _args())[0]

    sql = research_facility.emit_sql([plan], requested_by="pytest", queue_admitted=True)

    assert "insert into enoch.research_sources" in sql
    assert "insert into enoch.research_candidates" in sql
    assert "insert into enoch.research_admissions" in sql
    assert "insert into enoch.research_lineage" in sql
    assert "insert into enoch.ideas" in sql
    assert "insert into enoch.projects" in sql
    assert "insert into enoch.queue_items" in sql
    assert "research_facility" in sql
    assert "on conflict (project_id) do update" in sql


def test_research_facility_cli_extracts_json_from_markdown(tmp_path: Path) -> None:
    source = tmp_path / "ideas.md"
    output = tmp_path / "plan.json"
    source.write_text("Here is the batch:\n```json\n" + json.dumps([_strong_candidate()]) + "\n```\n", encoding="utf-8")

    assert research_facility.main([str(source), "--output", str(output)]) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["candidate_count"] == 1
    assert payload["admitted_count"] == 1


def test_research_facility_cli_keeps_empty_scanner_batch_empty(tmp_path: Path) -> None:
    source = tmp_path / "empty_scan.json"
    source.write_text(
        json.dumps(
            {
                "ok": False,
                "source_count": 0,
                "candidate_count": 0,
                "errors": [{"source": "arxiv:test", "error": "rate limited"}],
                "sources": [],
                "candidates": [],
            }
        )
    )
    output = tmp_path / "plan.json"

    assert research_facility.main([str(source), "--output", str(output)]) == 0

    payload = json.loads(output.read_text())
    assert payload["candidate_count"] == 0
    assert payload["admitted_count"] == 0
    assert payload["rejected_count"] == 0
    assert payload["plans"] == []


def test_research_facility_runtime_methods_are_present() -> None:
    from enoch_control_plane.control_plane.store import ControlPlaneStore
    from enoch_control_plane.control_plane.supabase_store import SupabaseControlPlaneStore

    assert ControlPlaneStore(Path(":memory:")).research_facility_workbench_projection() == []
    assert callable(getattr(SupabaseControlPlaneStore("postgresql://example.invalid/postgres", connect=lambda: None), "research_facility_workbench_projection"))


def test_research_facility_emits_full_source_records_when_present() -> None:
    candidate = _strong_candidate(
        source_ids=["arxiv-abc"],
        source_records=[
            {
                "source_id": "arxiv-abc",
                "source_kind": "arxiv",
                "title": "Source Title",
                "url": "https://arxiv.org/abs/2401.00000",
                "external_id": "2401.00000",
                "retrieved_at": "2026-05-09T00:00:00Z",
                "summary": "Source summary",
                "payload_json": {"query": "test"},
                "content_hash": "abc123",
            }
        ],
    )
    plan = research_facility.plan_candidates([candidate], _args())[0]

    sql = research_facility.emit_sql([plan], requested_by="pytest", queue_admitted=False)

    assert "external_id, retrieved_at, summary" in sql
    assert "Source summary" in sql
    assert "arxiv-abc" in sql
    assert "'source', 'arxiv-abc', 'candidate'" in sql


def test_research_facility_merges_exact_history_duplicates() -> None:
    candidate = _strong_candidate()
    row = research_facility.normalize_candidate(candidate, default_machine="192.168.1.77", default_model="gpt-5.5", default_sandbox="danger-full-access")
    args = _args(history=[{"project_id": "prior-project", "title": row["title"], "dedupe_key": row["dedupe_key"], "decision_gate_state": "negative"}])

    plan = research_facility.plan_candidates([candidate], args)[0]

    assert plan.admission_decision == "merged"
    assert plan.candidate["status"] == "merged"
    assert plan.candidate["similar_prior_projects"][0]["project_id"] == "prior-project"


def test_research_facility_requires_novelty_comparison_for_similar_history() -> None:
    candidate = _strong_candidate(novelty_comparison="")
    args = _args(
        history=[
            {
                "project_id": "prior-similar-negative",
                "title": "SSM Anchor Memory Variant",
                "mechanism": "Store SSM state summaries and exact anchors, then retrieve with query-conditioned scoring.",
                "baseline_to_beat": "Vector RAG and periodic exact-anchor baselines.",
                "decision_gate_state": "negative",
            }
        ]
    )

    plan = research_facility.plan_candidates([candidate], args)[0]

    assert plan.admission_decision == "rejected"
    assert "similar_prior_projects requires novelty_comparison" in plan.hard_failures
    assert plan.candidate["similar_prior_projects"]


def test_research_facility_cli_loads_history_json(tmp_path: Path) -> None:
    candidate_path = tmp_path / "ideas.json"
    history_path = tmp_path / "history.json"
    output = tmp_path / "plan.json"
    candidate = _strong_candidate()
    row = research_facility.normalize_candidate(candidate, default_machine="192.168.1.77", default_model="gpt-5.5", default_sandbox="danger-full-access")
    candidate_path.write_text(json.dumps([candidate]), encoding="utf-8")
    history_path.write_text(json.dumps([{"project_id": "prior-project", "title": row["title"], "dedupe_key": row["dedupe_key"]}]), encoding="utf-8")

    assert research_facility.main([str(candidate_path), "--history-json", str(history_path), "--output", str(output)]) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["history_count"] == 1
    assert payload["plans"][0]["admission_decision"] == "merged"
