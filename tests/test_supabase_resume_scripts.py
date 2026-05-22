from types import SimpleNamespace

import pytest

from enoch_control_plane.enoch_core.store import IdempotencyConflict
from scripts import requeue_supabase_cutover_paused_items as requeue
from scripts import supabase_controlled_resume_drill as drill


def test_wait_for_active_uses_control_state_active_items(monkeypatch):
    active = {"project_id": "idea-active", "status": "awaiting_wake"}
    monkeypatch.setattr(
        drill,
        "_get_state",
        lambda base, token: {"active_items": [active], "counts": {"awaiting_wake": 1}},
    )

    def fail_overview(
        base, token
    ):  # pragma: no cover - should not be called when state has active rows
        raise AssertionError(
            "overview should not be needed when /control/state has active_items"
        )

    monkeypatch.setattr(drill, "_get_overview", fail_overview)
    assert (
        drill._wait_for_active("http://control", "token", timeout_seconds=0.1) == active
    )


def test_worker_process_check_failure_is_not_treated_as_process_match(monkeypatch):
    def fake_run(*args, **kwargs):
        return SimpleNamespace(
            returncode=255, stdout="Permission denied (publickey).\n"
        )

    monkeypatch.setattr(requeue.subprocess, "run", fake_run)
    result = requeue._worker_process_check("jeremy@worker", ["idea-1"])

    assert result["checked"] is True
    assert result["ok"] is False
    assert result["matches"] == []
    assert result["returncode"] == 255


def test_worker_process_check_filters_locally_without_remote_project_regex(monkeypatch):
    observed = {}

    def fake_run(cmd, **kwargs):
        observed["cmd"] = cmd
        return SimpleNamespace(
            returncode=0, stdout="123 45 python run.py safe-id\n456 78 unrelated\n"
        )

    monkeypatch.setattr(requeue.subprocess, "run", fake_run)
    result = requeue._worker_process_check(
        "jeremy@worker", ["safe-id'; touch /tmp/pwn #", "safe-id"]
    )

    assert observed["cmd"][-1] == "ps -eo pid=,etimes=,cmd="
    assert "safe-id" not in observed["cmd"][-1]
    assert result["matches"] == ["123 45 python run.py safe-id"]


def test_resume_drill_fails_if_repause_fails(monkeypatch):
    args = SimpleNamespace(
        token_file="/tmp/missing",
        control_url="http://control",
        ssh_host="",
        apply=True,
        leave_unpaused=False,
        dispatch_timeout=1,
        active_wait_seconds=0.01,
    )
    monkeypatch.setenv("ENOCH_CONTROL_PLANE_TOKEN", "token")
    monkeypatch.setattr(drill, "validate_resume_readiness", lambda _args: {"ok": True})
    monkeypatch.setattr(
        drill,
        "_get_state",
        lambda _base, _token: {
            "flags": {"queue_paused": True, "maintenance_mode": True},
            "active_items": [],
        },
    )
    monkeypatch.setattr(
        drill,
        "_get_overview",
        lambda _base, _token: {
            "counts": {"queued": 1},
            "lanes": {"active": [{"project_id": "p1"}]},
        },
    )

    def fake_request(method, url, token, payload=None, **kwargs):  # noqa: ANN001 - patched HTTP boundary
        del token, payload, kwargs
        if url.endswith("/control/dispatch-next") and method == "POST":
            return (
                200,
                {"action": "paused"}
                if len(calls) == 1
                else {"action": "live_dispatch"},
            )
        if url.endswith("/control/resume"):
            return (200, {"flags": {"queue_paused": False}})
        if url.endswith("/control/pause"):
            return (500, {"error": "pause failed"})
        raise AssertionError(url)

    calls: list[str] = []

    def counted_request(method, url, token, payload=None, **kwargs):  # noqa: ANN001
        if url.endswith("/control/dispatch-next"):
            calls.append(url)
        return fake_request(method, url, token, payload, **kwargs)

    monkeypatch.setattr(drill, "_request", counted_request)

    with pytest.raises(drill.DrillError, match="failed to re-pause"):
        drill.drill(args)


def test_requeue_reconcile_conflicts_on_reused_event_key_with_different_identity(
    monkeypatch,
):
    class Cursor:
        rowcount = 1

        def __init__(self):
            self._fetchone = None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, sql, params=()):
            normalized = " ".join(str(sql).lower().split())
            if normalized.startswith("set search_path"):
                return self
            if normalized.startswith("select q.project_id"):
                self._fetchall = [
                    {
                        "project_id": "p1",
                        "project_name": "P1",
                        "status": "paused",
                        "next_action_hint": "maintenance_cutover_reconcile",
                        "last_run_state": "",
                        "current_run_id": "",
                        "updated_at": "now",
                    }
                ]
                return self
            if normalized.startswith("update queue_items"):
                self._fetchall = [{"project_id": "p1"}]
                return self
            if normalized.startswith("select event_id"):
                self._fetchone = {
                    "event_id": 5,
                    "event_type": "queue.other",
                    "entity_type": "control",
                    "entity_id": "queue",
                    "payload_hash": "same-hash-not-enough",
                }
                return self
            if normalized.startswith("insert into control_events"):
                raise AssertionError("conflicting replay must not insert")
            raise AssertionError(normalized)

        def fetchall(self):
            return getattr(self, "_fetchall", [])

        def fetchone(self):
            return self._fetchone

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self):
            return Cursor()

        def commit(self):
            pass

    monkeypatch.setattr(requeue, "_connect", lambda _database_url: Conn())
    monkeypatch.setattr(
        requeue,
        "_worker_process_check",
        lambda _host, _ids: {"checked": False, "matches": []},
    )

    args = SimpleNamespace(
        database_url="postgres://example",
        worker_ssh_host="",
        requested_by="unit",
        idempotency_key="requeue-key",
        apply=True,
    )

    with pytest.raises(IdempotencyConflict):
        requeue.reconcile(args)
