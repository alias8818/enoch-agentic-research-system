from types import SimpleNamespace

from scripts import requeue_supabase_cutover_paused_items as requeue
from scripts import supabase_controlled_resume_drill as drill


def test_wait_for_active_uses_control_state_active_items(monkeypatch):
    active = {"project_id": "idea-active", "status": "awaiting_wake"}
    monkeypatch.setattr(drill, "_get_state", lambda base, token: {"active_items": [active], "counts": {"awaiting_wake": 1}})

    def fail_overview(base, token):  # pragma: no cover - should not be called when state has active rows
        raise AssertionError("overview should not be needed when /control/state has active_items")

    monkeypatch.setattr(drill, "_get_overview", fail_overview)
    assert drill._wait_for_active("http://control", "token", timeout_seconds=0.1) == active


def test_worker_process_check_failure_is_not_treated_as_process_match(monkeypatch):
    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=255, stdout="Permission denied (publickey).\n")

    monkeypatch.setattr(requeue.subprocess, "run", fake_run)
    result = requeue._worker_process_check("jeremy@worker", ["idea-1"])

    assert result["checked"] is True
    assert result["ok"] is False
    assert result["matches"] == []
    assert result["returncode"] == 255
