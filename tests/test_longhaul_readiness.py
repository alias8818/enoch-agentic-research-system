from __future__ import annotations

from datetime import datetime, timezone

from enoch_control_plane.control_plane.longhaul_readiness import evaluate_longhaul_readiness

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
            "enoch-research-autopilot.timer": {"ActiveState": "active", "LastTriggerUSec": "Sun 2026-05-10 04:45:00 UTC"},
            "enoch-corpus-import-autopilot.timer": {"ActiveState": "active", "LastTriggerUSec": "Sun 2026-05-10 04:40:00 UTC"},
        },
        "services": {
            "enoch-research-autopilot.service": {"Result": "success", "InactiveEnterTimestamp": "Sun 2026-05-10 04:50:00 UTC"},
            "enoch-corpus-import-autopilot.service": {"Result": "success", "InactiveEnterTimestamp": "Sun 2026-05-10 04:55:00 UTC"},
        },
        "provider_budget": {"ok": True, "provider": "synthetic", "remaining_credits": 100.0, "rolling_remaining": 2500},
    }


def test_longhaul_ready_when_all_checks_pass() -> None:
    payload = _ready_payload()
    result = evaluate_longhaul_readiness(now=NOW, **payload)
    assert result["ok"] is True
    assert result["label"] == "Long-haul mode: READY"
    assert result["blockers"] == []


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
    payload["services"]["enoch-corpus-import-autopilot.service"]["InactiveEnterTimestamp"] = "Sun 2026-05-10 02:00:00 UTC"
    result = evaluate_longhaul_readiness(now=NOW, **payload)
    assert result["ok"] is False
    assert "publish_ready=2 but latest corpus tick is stale or missing" in result["blockers"]


def test_provider_budget_must_be_checked_and_ok() -> None:
    payload = _ready_payload()
    payload["provider_budget"] = {"ok": False, "failures": ["rolling limit low"]}
    result = evaluate_longhaul_readiness(now=NOW, **payload)
    assert result["ok"] is False
    assert "provider budget below threshold or unavailable" in result["blockers"]
