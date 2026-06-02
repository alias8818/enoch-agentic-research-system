from __future__ import annotations

from datetime import datetime, timezone

from enoch_control_plane.control_plane.longhaul_readiness import (
    evaluate_longhaul_readiness,
)

NOW = datetime(2026, 5, 10, 5, 0, 0, tzinfo=timezone.utc)


def _ready_payload() -> dict:
    return {
        "state": {
            "flags": {"queue_paused": False, "maintenance_mode": False},
            "counts": {"queued": 1, "active": 0, "blocked": 0},
            "next_candidate": {"project_id": "p1"},
        },
        "overview": {
            "operator_counts": {"needs_attention": 0},
            "paper_pipeline": {
                "write_needed": 0,
                "raw_completed_no_paper_candidates": 10,
                "not_writable_by_decision_gate": 10,
                "publish_ready": 0,
                "published_imported": 382,
            },
        },
        "timers": {
            "enoch-research-autopilot.timer": {
                "ActiveState": "active",
                "LastTriggerUSec": "Sun 2026-05-10 04:45:00 UTC",
            },
            "enoch-corpus-import-autopilot.timer": {
                "ActiveState": "active",
                "LastTriggerUSec": "Sun 2026-05-10 04:40:00 UTC",
            },
        },
        "services": {
            "enoch-research-autopilot.service": {
                "Result": "success",
                "InactiveEnterTimestamp": "Sun 2026-05-10 04:50:00 UTC",
            },
            "enoch-corpus-import-autopilot.service": {
                "Result": "success",
                "InactiveEnterTimestamp": "Sun 2026-05-10 04:55:00 UTC",
            },
        },
        "provider_budget": {
            "ok": True,
            "provider": "synthetic",
            "remaining_credits": 100.0,
            "rolling_remaining": 2500,
        },
        "research_quality": {
            "ok": True,
            "status": "warnings",
            "decisions_checked": 100,
            "problem_counts": {"weak_or_missing_evidence_strength": 1},
            "report_path": "/tmp/quality.json",
            "report_mtime": "2026-05-10T04:50:00Z",
        },
        "source_lineage": {
            "ok": True,
            "status": "clean",
            "candidates_checked": 0,
            "followups_checked": 1,
            "missing_sources": 0,
            "missing_lineage": 0,
            "problem_counts": {},
            "report_path": "/tmp/source-lineage.json",
            "report_mtime": "2026-05-10T04:51:00Z",
        },
    }


def test_longhaul_ready_when_all_checks_pass() -> None:
    payload = _ready_payload()
    result = evaluate_longhaul_readiness(now=NOW, **payload)
    assert result["ok"] is True
    assert result["label"] == "Long-haul mode: READY"
    assert result["blockers"] == []
    assert result["summary"]["research_timer_active"] is True
    assert result["summary"]["research_tick_age_seconds"] == 600
    assert result["summary"]["research_tick_max_age_seconds"] == 2700
    assert result["summary"]["corpus_timer_active"] is True
    assert result["summary"]["corpus_tick_age_seconds"] == 300


def test_queue_pause_is_first_class_blocker() -> None:
    payload = _ready_payload()
    payload["state"]["flags"]["queue_paused"] = True
    result = evaluate_longhaul_readiness(now=NOW, **payload)
    assert result["ok"] is False
    assert "queue_paused=true" in result["blockers"]
    assert result["label"] == "Long-haul mode: BLOCKED — queue_paused=true"


def test_publish_ready_requires_recent_corpus_tick() -> None:
    payload = _ready_payload()
    payload["overview"]["paper_pipeline"]["publish_ready"] = 2
    payload["services"]["enoch-corpus-import-autopilot.service"][
        "InactiveEnterTimestamp"
    ] = "Sun 2026-05-10 02:00:00 UTC"
    payload["timers"]["enoch-corpus-import-autopilot.timer"]["LastTriggerUSec"] = (
        "Sun 2026-05-10 02:00:00 UTC"
    )
    result = evaluate_longhaul_readiness(now=NOW, **payload)
    assert result["ok"] is False
    assert (
        "publish_ready=2 but latest corpus tick is stale or missing"
        in result["blockers"]
    )


def test_research_quality_blocker_fails_longhaul_readiness() -> None:
    payload = _ready_payload()
    payload["research_quality"] = {
        "ok": False,
        "status": "blocked",
        "problem_counts": {"unknown_decision": 1},
    }
    result = evaluate_longhaul_readiness(now=NOW, **payload)
    assert result["ok"] is False
    assert "research quality status=blocked" in result["blockers"]


def test_research_quality_warning_does_not_block_longhaul_readiness() -> None:
    payload = _ready_payload()
    payload["research_quality"] = {
        "ok": True,
        "status": "warnings",
        "decisions_checked": 100,
        "problem_counts": {"weak_or_missing_evidence_strength": 1},
    }
    result = evaluate_longhaul_readiness(now=NOW, **payload)
    assert result["ok"] is True
    assert result["summary"]["research_quality_status"] == "warnings"
    assert result["summary"]["research_quality_problem_counts"] == {
        "weak_or_missing_evidence_strength": 1
    }


def test_research_quality_post_prompt_monitor_is_exposed_in_summary() -> None:
    payload = _ready_payload()
    payload["research_quality"]["post_prompt_monitor"] = {
        "available": True,
        "candidate_count": 20,
        "decision_count": 13,
        "proxy_only_positive": 4,
        "malformed_provider_response_count": 1,
    }
    result = evaluate_longhaul_readiness(now=NOW, **payload)

    assert result["ok"] is True
    assert (
        result["summary"]["research_quality_post_prompt_monitor"]["candidate_count"]
        == 20
    )
    assert (
        result["summary"]["research_quality_post_prompt_monitor"][
            "malformed_provider_response_count"
        ]
        == 1
    )


def test_tick_freshness_treats_naive_iso_timestamps_as_utc() -> None:
    payload = _ready_payload()
    payload["services"]["enoch-research-autopilot.service"][
        "InactiveEnterTimestamp"
    ] = "2026-05-10T04:45:00"
    payload["services"]["enoch-research-autopilot.service"].pop(
        "ActiveEnterTimestamp", None
    )
    payload["timers"]["enoch-research-autopilot.timer"]["LastTriggerUSec"] = (
        "2026-05-10T04:45:00"
    )

    result = evaluate_longhaul_readiness(now=NOW, **payload)

    assert result["ok"] is True
    assert result["summary"]["research_tick_age_seconds"] == 900


def test_source_lineage_blocker_fails_longhaul_readiness() -> None:
    payload = _ready_payload()
    payload["source_lineage"] = {
        "ok": False,
        "status": "blocked",
        "problem_counts": {"followup_missing_parent_run_source": 1},
        "missing_sources": 1,
        "missing_lineage": 0,
    }
    result = evaluate_longhaul_readiness(now=NOW, **payload)

    assert result["ok"] is False
    assert "source lineage status=blocked" in result["blockers"]
    assert result["summary"]["source_lineage_status"] == "blocked"
    assert result["summary"]["source_lineage_missing_sources"] == 1


def test_source_lineage_warning_does_not_block_longhaul_readiness() -> None:
    payload = _ready_payload()
    payload["source_lineage"] = {
        "ok": True,
        "status": "warnings",
        "problem_counts": {"historical_source_lineage_gap": 70},
        "missing_sources": 0,
        "missing_lineage": 0,
    }
    result = evaluate_longhaul_readiness(now=NOW, **payload)

    assert result["ok"] is True
    assert result["summary"]["source_lineage_status"] == "warnings"
    assert result["summary"]["source_lineage_problem_counts"] == {
        "historical_source_lineage_gap": 70
    }


def test_provider_budget_must_be_checked_and_ok() -> None:
    payload = _ready_payload()
    payload["provider_budget"] = {"ok": False, "failures": ["rolling limit low"]}
    result = evaluate_longhaul_readiness(now=NOW, **payload)
    assert result["ok"] is False
    assert "provider budget below threshold or unavailable" in result["blockers"]


def test_structurally_unhealthy_llm_model_blocks_longhaul_readiness() -> None:
    payload = _ready_payload()
    payload["llm_model_health"] = {
        "ok": False,
        "status": "needs_attention",
        "unhealthy_count": 0,
        "structurally_unhealthy_count": 2,
        "models": [
            {
                "provider_id": "synthetic",
                "model_id": "owl",
                "endpoint_health": "healthy",
                "status": "healthy",
                "format_health": "degraded",
                "visible_output_health": "healthy",
                "reasoning_budget_health": "ok",
                "latest_failure_kind": "",
            },
            {
                "provider_id": "synthetic",
                "model_id": "kimi",
                "endpoint_health": "healthy",
                "status": "healthy",
                "format_health": "healthy",
                "visible_output_health": "empty",
                "reasoning_budget_health": "length_limited",
                "latest_failure_kind": "",
            },
        ],
    }

    result = evaluate_longhaul_readiness(now=NOW, **payload)

    assert result["ok"] is False
    assert "configured LLM model health needs attention" in result["blockers"]
    check = next(
        item for item in result["checks"] if item["name"] == "llm_model_health_ok"
    )
    assert check["ok"] is False
    assert "structural=2" in check["detail"]
    assert "owl=format_degraded" in check["detail"]
    assert "kimi=visible_output_empty" in check["detail"]
    assert result["summary"]["llm_model_health_status"] == "needs_attention"
    assert result["summary"]["llm_model_unhealthy_count"] == 0
    assert result["summary"]["llm_model_structurally_unhealthy_count"] == 2


def test_structural_llm_attention_does_not_block_when_workflows_have_usable_models() -> (
    None
):
    payload = _ready_payload()
    payload["llm_model_health"] = {
        "ok": False,
        "status": "needs_attention",
        "unhealthy_count": 0,
        "structurally_unhealthy_count": 1,
        "models": [
            {
                "provider_id": "synthetic",
                "model_id": "hf:zai-org/GLM-5.1",
                "endpoint_health": "healthy",
                "status": "healthy",
                "format_health": "healthy",
                "visible_output_health": "healthy",
                "reasoning_budget_health": "ok",
                "latest_failure_kind": "",
            },
            {
                "provider_id": "openrouter",
                "model_id": "moonshotai/kimi-k2.6",
                "endpoint_health": "healthy",
                "status": "healthy",
                "format_health": "degraded",
                "visible_output_health": "empty",
                "reasoning_budget_health": "length_limited",
                "latest_failure_kind": "",
            },
        ],
        "workflow_recommendations": [
            {
                "workflow_id": "research_generation",
                "enabled": True,
                "status": "needs_attention",
                "required_contracts": ["candidate_json"],
                "current_default_model": "hf:zai-org/GLM-5.1",
                "recommended_model_pool": ["hf:zai-org/GLM-5.1"],
                "recommended_default_model": "hf:zai-org/GLM-5.1",
            },
            {
                "workflow_id": "paper_writing",
                "enabled": True,
                "status": "healthy",
                "required_contracts": ["markdown_fenced_json"],
                "current_default_model": "openrouter/owl-alpha",
                "recommended_model_pool": ["openrouter/owl-alpha"],
                "recommended_default_model": "openrouter/owl-alpha",
            },
        ],
    }

    result = evaluate_longhaul_readiness(now=NOW, **payload)

    assert result["ok"] is True
    assert "configured LLM model health needs attention" not in result["blockers"]
    check = next(
        item for item in result["checks"] if item["name"] == "llm_model_health_ok"
    )
    assert check["ok"] is True
    assert "structural=1" in check["detail"]
    assert "moonshotai/kimi-k2.6=format_degraded" in check["detail"]
    assert result["summary"]["llm_model_health_status"] == "needs_attention"
    assert result["summary"]["llm_model_unhealthy_count"] == 0
    assert result["summary"]["llm_model_structurally_unhealthy_count"] == 1


def test_llm_workflow_unusable_default_blocks_longhaul_readiness() -> None:
    payload = _ready_payload()
    payload["llm_model_health"] = {
        "ok": False,
        "status": "needs_attention",
        "unhealthy_count": 0,
        "structurally_unhealthy_count": 1,
        "models": [
            {
                "provider_id": "synthetic",
                "model_id": "hf:bad-json",
                "endpoint_health": "healthy",
                "status": "healthy",
                "format_health": "degraded",
                "visible_output_health": "healthy",
                "reasoning_budget_health": "ok",
                "latest_failure_kind": "",
            },
            {
                "provider_id": "synthetic",
                "model_id": "hf:ok",
                "endpoint_health": "healthy",
                "status": "healthy",
                "format_health": "healthy",
                "visible_output_health": "healthy",
                "reasoning_budget_health": "ok",
                "latest_failure_kind": "",
            },
        ],
        "workflow_recommendations": [
            {
                "workflow_id": "research_generation",
                "enabled": True,
                "status": "needs_attention",
                "required_contracts": ["candidate_json"],
                "current_default_model": "hf:bad-json",
                "recommended_model_pool": ["hf:ok"],
                "recommended_default_model": "hf:ok",
            }
        ],
    }

    result = evaluate_longhaul_readiness(now=NOW, **payload)

    assert result["ok"] is False
    assert "configured LLM model health needs attention" in result["blockers"]
    check = next(
        item for item in result["checks"] if item["name"] == "llm_model_health_ok"
    )
    assert check["ok"] is False
    assert (
        "default_mismatches=research_generation:hf:bad-json->hf:ok" in check["detail"]
    )


def test_blocked_llm_workflow_blocks_longhaul_readiness() -> None:
    payload = _ready_payload()
    payload["llm_model_health"] = {
        "ok": False,
        "status": "needs_attention",
        "unhealthy_count": 0,
        "structurally_unhealthy_count": 1,
        "models": [],
        "workflow_recommendations": [
            {
                "workflow_id": "research_generation",
                "enabled": True,
                "status": "blocked",
                "required_contracts": ["candidate_json"],
                "recommended_model_pool": [],
                "recommended_default_model": "",
            }
        ],
    }

    result = evaluate_longhaul_readiness(now=NOW, **payload)

    assert result["ok"] is False
    assert "configured LLM model health needs attention" in result["blockers"]
    check = next(
        item for item in result["checks"] if item["name"] == "llm_model_health_ok"
    )
    assert check["ok"] is False
    assert "blocked_workflows=research_generation:candidate_json" in check["detail"]


def test_latest_provider_generation_failure_blocks_longhaul_readiness() -> None:
    payload = _ready_payload()
    payload["overview"]["provider_generation_attempts"] = {
        "ok": False,
        "status": "blocked",
        "attempt_count": 3,
        "recent_failed_count": 2,
        "latest_status": "failed",
        "latest_failure_kind": "rate_limited",
        "latest_reason": "provider generation skipped: 429 Too Many Requests",
    }

    result = evaluate_longhaul_readiness(now=NOW, **payload)

    assert result["ok"] is False
    assert "latest provider generation attempt failed" in result["blockers"]
    check = next(
        item
        for item in result["checks"]
        if item["name"] == "provider_generation_attempts_ok"
    )
    assert check["ok"] is False
    assert check["data"]["latest_failure_kind"] == "rate_limited"
    assert result["summary"]["provider_generation_attempt_status"] == "blocked"
    assert result["summary"]["provider_generation_latest_status"] == "failed"


def test_latest_provider_generation_success_clears_previous_failures() -> None:
    payload = _ready_payload()
    payload["overview"]["provider_generation_attempts"] = {
        "ok": True,
        "status": "ok",
        "attempt_count": 4,
        "recent_failed_count": 3,
        "latest_status": "success",
        "latest_failure_kind": "",
    }

    result = evaluate_longhaul_readiness(now=NOW, **payload)

    assert result["ok"] is True
    assert "latest provider generation attempt failed" not in result["blockers"]
    assert result["summary"]["provider_generation_recent_failed_count"] == 3
    assert result["summary"]["provider_generation_latest_status"] == "success"


def test_unhealthy_llm_model_health_blocks_longhaul_readiness() -> None:
    payload = _ready_payload()
    payload["llm_model_health"] = {
        "ok": False,
        "status": "needs_attention",
        "unhealthy_count": 2,
        "models": [
            {
                "provider_id": "openrouter",
                "model_id": "moonshotai/kimi-k2.6",
                "status": "unhealthy",
                "latest_failure_kind": "rate_limited",
            },
            {
                "provider_id": "openrouter",
                "model_id": "openrouter/owl-alpha",
                "status": "stale",
                "latest_failure_kind": "",
            },
        ],
    }

    result = evaluate_longhaul_readiness(now=NOW, **payload)

    assert result["ok"] is False
    assert "configured LLM model health needs attention" in result["blockers"]
    check = next(
        item for item in result["checks"] if item["name"] == "llm_model_health_ok"
    )
    assert check["ok"] is False
    assert check["data"]["unhealthy_count"] == 2
    assert result["summary"]["llm_model_health_status"] == "needs_attention"
    assert result["summary"]["llm_model_unhealthy_count"] == 2


def test_tick_freshness_uses_latest_timer_trigger_not_stale_inactive_timestamp() -> (
    None
):
    payload = _ready_payload()
    payload["services"]["enoch-research-autopilot.service"][
        "InactiveEnterTimestamp"
    ] = "Sun 2026-05-10 04:30:00 UTC"
    payload["timers"]["enoch-research-autopilot.timer"]["LastTriggerUSec"] = (
        "Sun 2026-05-10 04:59:00 UTC"
    )
    result = evaluate_longhaul_readiness(now=NOW, **payload)
    assert result["ok"] is True
    assert result["summary"]["research_tick_age_seconds"] == 60


def test_tick_freshness_uses_active_enter_for_running_service() -> None:
    payload = _ready_payload()
    payload["services"]["enoch-research-autopilot.service"].update(
        {
            "ActiveState": "activating",
            "ActiveEnterTimestamp": "Sun 2026-05-10 04:58:00 UTC",
            "InactiveEnterTimestamp": "Sun 2026-05-10 04:10:00 UTC",
        }
    )
    payload["timers"]["enoch-research-autopilot.timer"]["LastTriggerUSec"] = (
        "Sun 2026-05-10 04:58:00 UTC"
    )
    result = evaluate_longhaul_readiness(now=NOW, **payload)
    assert result["ok"] is True
    assert result["summary"]["research_tick_age_seconds"] == 120


def test_multi_lane_active_queue_counts_are_consistent_when_all_lanes_busy() -> None:
    payload = _ready_payload()
    payload["state"]["counts"].update({"queued": 3, "active": 2})
    payload["state"]["next_candidate"] = None
    payload["state"]["worker_lanes"] = [
        {
            "configured": True,
            "machine_target": "cpu-proxmox-1",
            "status": "active",
            "active_count": 1,
            "queued_count": 0,
        },
        {
            "configured": True,
            "machine_target": "gb10",
            "status": "active",
            "active_count": 1,
            "queued_count": 3,
        },
    ]

    result = evaluate_longhaul_readiness(now=NOW, **payload)

    assert result["ok"] is True
    check = next(
        item for item in result["checks"] if item["name"] == "queue_counts_consistent"
    )
    assert check["ok"] is True
    assert check["data"]["worker_lane_capacity"] == 2


def test_duplicate_active_on_same_lane_blocks_queue_count_consistency() -> None:
    payload = _ready_payload()
    payload["state"]["counts"].update({"queued": 0, "active": 2})
    payload["state"]["next_candidate"] = None
    payload["state"]["worker_lanes"] = [
        {
            "configured": True,
            "machine_target": "cpu-proxmox-1",
            "status": "active",
            "active_count": 2,
            "queued_count": 0,
        },
        {
            "configured": True,
            "machine_target": "gb10",
            "status": "idle",
            "active_count": 0,
            "queued_count": 0,
        },
    ]

    result = evaluate_longhaul_readiness(now=NOW, **payload)

    assert result["ok"] is False
    assert "queued/active state inconsistent" in result["blockers"]
    check = next(
        item for item in result["checks"] if item["name"] == "queue_counts_consistent"
    )
    assert check["ok"] is False
    assert check["data"]["lane_conflict"] is True


def test_stale_active_worker_lane_blocks_longhaul_readiness() -> None:
    payload = _ready_payload()
    payload["state"]["counts"].update({"queued": 0, "active": 1})
    payload["state"]["next_candidate"] = None
    payload["state"]["worker_lanes"] = [
        {
            "configured": True,
            "machine_target": "cpu-proxmox-1",
            "status": "active",
            "active_count": 1,
            "queued_count": 0,
            "active_confirmation": {
                "state": "stale_active",
                "matched": False,
                "reason": "worker reports no live run for active control-plane row",
            },
        },
        {
            "configured": True,
            "machine_target": "gb10",
            "status": "idle",
            "active_count": 0,
            "queued_count": 0,
        },
    ]

    result = evaluate_longhaul_readiness(now=NOW, **payload)

    assert result["ok"] is False
    assert "stale active worker lane exists" in result["blockers"]
    check = next(
        item
        for item in result["checks"]
        if item["name"] == "active_worker_lanes_confirmed"
    )
    assert check["ok"] is False
    assert check["data"]["stale_active_lanes"] == ["cpu-proxmox-1"]


def test_recent_worker_reconcile_grace_is_reported_without_blocking() -> None:
    payload = _ready_payload()
    payload["state"]["counts"].update({"queued": 0, "active": 1})
    payload["state"]["next_candidate"] = None
    payload["state"]["worker_lanes"] = [
        {
            "configured": True,
            "machine_target": "gb10",
            "status": "active",
            "active_count": 1,
            "queued_count": 0,
            "active_confirmation": {
                "state": "active_unconfirmed_grace",
                "matched": False,
                "reason": "worker reports no live run, but observation is within reconcile grace",
            },
        }
    ]

    result = evaluate_longhaul_readiness(now=NOW, **payload)

    assert result["ok"] is True
    check = next(
        item
        for item in result["checks"]
        if item["name"] == "active_worker_lanes_confirmed"
    )
    assert check["ok"] is True
    assert check["data"]["unconfirmed_grace_lanes"] == ["gb10"]


def test_open_lane_queued_work_requires_top_level_next_candidate() -> None:
    payload = _ready_payload()
    payload["state"]["counts"].update({"queued": 1, "active": 1})
    payload["state"]["next_candidate"] = None
    payload["state"]["worker_lanes"] = [
        {
            "configured": True,
            "machine_target": "cpu-proxmox-1",
            "status": "active",
            "active_count": 1,
            "queued_count": 0,
            "dispatch_available": False,
        },
        {
            "configured": True,
            "machine_target": "gb10",
            "status": "idle",
            "active_count": 0,
            "queued_count": 1,
            "dispatch_available": True,
        },
    ]

    result = evaluate_longhaul_readiness(now=NOW, **payload)

    assert result["ok"] is False
    assert "queued/active state inconsistent" in result["blockers"]
    check = next(
        item for item in result["checks"] if item["name"] == "queue_counts_consistent"
    )
    assert check["ok"] is False


def test_paused_maintenance_suppresses_idle_dispatch_expectation() -> None:
    payload = _ready_payload()
    payload["state"]["flags"].update({"queue_paused": True, "maintenance_mode": True})
    payload["state"]["counts"].update({"queued": 50, "active": 0})
    payload["state"]["next_candidate"] = None
    payload["state"]["worker_lanes"] = [
        {
            "configured": True,
            "machine_target": "cpu-proxmox-1",
            "status": "idle",
            "active_count": 0,
            "queued_count": 26,
            "dispatch_available": False,
        },
        {
            "configured": True,
            "machine_target": "gb10",
            "status": "idle",
            "active_count": 0,
            "queued_count": 24,
            "dispatch_available": False,
        },
    ]

    result = evaluate_longhaul_readiness(now=NOW, **payload)

    assert result["ok"] is False
    assert "queue_paused=true" in result["blockers"]
    assert "maintenance_mode=true" in result["blockers"]
    assert "queued/active state inconsistent" not in result["blockers"]
    check = next(
        item for item in result["checks"] if item["name"] == "queue_counts_consistent"
    )
    assert check["ok"] is True
    assert check["data"]["dispatch_expectation_suppressed"] is True


def test_paused_open_lane_still_requires_top_level_next_candidate() -> None:
    payload = _ready_payload()
    payload["state"]["flags"]["queue_paused"] = True
    payload["state"]["counts"].update({"queued": 1, "active": 0})
    payload["state"]["next_candidate"] = None
    payload["state"]["worker_lanes"] = [
        {
            "configured": True,
            "machine_target": "gb10",
            "status": "idle",
            "active_count": 0,
            "queued_count": 1,
            "dispatch_available": True,
        },
    ]

    result = evaluate_longhaul_readiness(now=NOW, **payload)

    assert result["ok"] is False
    assert "queued/active state inconsistent" in result["blockers"]
    check = next(
        item for item in result["checks"] if item["name"] == "queue_counts_consistent"
    )
    assert check["ok"] is False
    assert check["data"]["dispatch_expectation_suppressed"] is True


def test_multi_active_without_lane_capacity_blocks_queue_count_consistency() -> None:
    payload = _ready_payload()
    payload["state"]["counts"].update({"queued": 3, "active": 2})
    payload["state"]["next_candidate"] = None

    result = evaluate_longhaul_readiness(now=NOW, **payload)

    assert result["ok"] is False
    assert "queued/active state inconsistent" in result["blockers"]
