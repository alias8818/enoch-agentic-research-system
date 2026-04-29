from __future__ import annotations

import subprocess
import asyncio

from omx_wake_gate import app as appmod
from omx_wake_gate.config import GateConfig
from omx_wake_gate.models import DispatchRequest, TelemetrySample
from omx_wake_gate.state_store import StateStore


class _StaticTelemetry:
    def sample(self) -> TelemetrySample:
        return TelemetrySample(
            cpu_pct=0.0,
            gpu_pct=0.0,
            memory_source="uma_meminfo",
            uma_allocatable_mib=100_000,
            vram_used_mib=0,
        )


def test_dispatch_resolves_prompt_file_under_project_root(tmp_path, monkeypatch) -> None:
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
            omx_inbound_bearer_token="secret",
            completion_callback_url="http://127.0.0.1/callback",
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
    prompt_arg = captured["cmd"][captured["cmd"].index("--prompt-file") + 1]
    assert prompt_arg == str(prompt_file.resolve())
