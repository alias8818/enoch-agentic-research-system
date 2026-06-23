from __future__ import annotations

import json
import subprocess
import asyncio

from enoch_control_plane import app as appmod
from enoch_control_plane.config import GateConfig
from enoch_control_plane.models import DispatchRequest, TelemetrySample
from enoch_control_plane.state_store import StateStore


class _StaticTelemetry:
    def sample(self) -> TelemetrySample:
        return TelemetrySample(
            cpu_pct=0.0,
            gpu_pct=0.0,
            memory_source="uma_meminfo",
            uma_allocatable_mib=100_000,
            vram_used_mib=0,
        )


def test_dispatch_resolves_prompt_file_under_project_root(
    tmp_path, monkeypatch
) -> None:
    script = tmp_path / "dispatch.sh"
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    script.chmod(0o755)

    project_dir = tmp_path / "project-1"
    prompt_file = project_dir / "prompts" / "initial.md"
    prompt_file.parent.mkdir(parents=True)
    prompt_file.write_text("do work", encoding="utf-8")

    monkeypatch.setattr(
        appmod,
        "config",
        GateConfig(
            state_dir=str(tmp_path / "state"),
            project_root=str(tmp_path),
            dispatch_script_path=str(script),
            control_api_bearer_token="secret",
            completion_callback_url="https://callback.example.com/callback",
            completion_callback_token="callback-token",
        ),
    )
    monkeypatch.setattr(appmod, "store", StateStore(tmp_path / "state"))
    monkeypatch.setattr(appmod, "telemetry", _StaticTelemetry())

    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"pid":123,"pgid":123}',
            stderr="",
        )

    monkeypatch.setattr(appmod.subprocess, "run", fake_run)

    response = asyncio.run(
        appmod.dispatch_run(
            DispatchRequest(
                run_id="run-1",
                project_id="project-1",
                project_dir="project-1",
                prompt_file="project-1/prompts/initial.md",
            ),
            authorization="Bearer secret",
        ),
    )

    assert response["accepted"] is True
    assert response["envelope_id"] == "run-1"
    events = [
        json.loads(line)
        for line in (tmp_path / "state" / "events.log")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    dispatch_events = [
        event for event in events if event["kind"] == "dispatch_envelope"
    ]
    assert [event["state"] for event in dispatch_events] == ["accepted", "started"]
    assert {event["envelope_id"] for event in dispatch_events} == {"run-1"}
    prompt_arg = captured["cmd"][captured["cmd"].index("--prompt-file") + 1]
    assert prompt_arg == str(prompt_file.resolve())


def test_dispatch_persists_failed_envelope_before_worker_error(
    tmp_path, monkeypatch
) -> None:
    script = tmp_path / "dispatch.sh"
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    script.chmod(0o755)

    project_dir = tmp_path / "project-1"
    prompt_file = project_dir / "prompts" / "initial.md"
    prompt_file.parent.mkdir(parents=True)
    prompt_file.write_text("do work", encoding="utf-8")

    monkeypatch.setattr(
        appmod,
        "config",
        GateConfig(
            state_dir=str(tmp_path / "state"),
            project_root=str(tmp_path),
            dispatch_script_path=str(script),
            control_api_bearer_token="secret",
            completion_callback_url="https://callback.example.com/callback",
            completion_callback_token="callback-token",
        ),
    )
    monkeypatch.setattr(appmod, "store", StateStore(tmp_path / "state"))

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="boom")

    monkeypatch.setattr(appmod.subprocess, "run", fake_run)

    try:
        asyncio.run(
            appmod.dispatch_run(
                DispatchRequest(
                    run_id="run-fail",
                    project_id="project-1",
                    project_dir="project-1",
                    prompt_file="project-1/prompts/initial.md",
                ),
                authorization="Bearer secret",
            ),
        )
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 502
    else:  # pragma: no cover - regression guard
        raise AssertionError("dispatch failure should raise")

    events = [
        json.loads(line)
        for line in (tmp_path / "state" / "events.log")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    dispatch_events = [
        event for event in events if event["kind"] == "dispatch_envelope"
    ]
    assert [event["state"] for event in dispatch_events] == ["accepted", "failed"]
    assert {event["envelope_id"] for event in dispatch_events} == {"run-fail"}
    assert dispatch_events[-1]["detail"]["message"] == "dispatch failed"
    assert dispatch_events[-1]["detail"]["stderr_present"] is True
    assert "boom" not in json.dumps(dispatch_events[-1]["detail"])


def test_dispatch_request_defaults_to_workspace_write_sandbox() -> None:
    request = DispatchRequest(
        run_id="run-safe",
        project_id="project-safe",
        project_dir="project-safe",
        prompt_file="project-safe/prompts/initial.md",
    )

    assert request.sandbox == "workspace-write"


def test_dispatch_rejects_project_dir_outside_configured_root(
    tmp_path, monkeypatch
) -> None:
    script = tmp_path / "dispatch.sh"
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    script.chmod(0o755)
    root = tmp_path / "projects"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    prompt_file = outside / "prompt.md"
    prompt_file.write_text("do work", encoding="utf-8")

    monkeypatch.setattr(
        appmod,
        "config",
        GateConfig(
            state_dir=str(tmp_path / "state"),
            project_root=str(root),
            dispatch_script_path=str(script),
            control_api_bearer_token="secret",
            completion_callback_url="https://callback.example.com/callback",
            completion_callback_token="callback-token",
        ),
    )

    try:
        asyncio.run(
            appmod.dispatch_run(
                DispatchRequest(
                    run_id="run-outside",
                    project_id="project-outside",
                    project_dir=str(outside),
                    prompt_file=str(prompt_file),
                ),
                authorization="Bearer secret",
            ),
        )
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400
        assert "project root" in str(getattr(exc, "detail", exc))
    else:  # pragma: no cover - regression guard
        raise AssertionError("dispatch accepted project_dir outside configured root")
