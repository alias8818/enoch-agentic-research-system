from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_deploy_runtime_script_has_valid_bash_syntax() -> None:
    script = ROOT / "scripts" / "deploy-enoch-runtime.sh"
    subprocess.run(["bash", "-n", str(script)], check=True)


def test_sync_codex_worker_config_script_has_valid_bash_syntax() -> None:
    script = ROOT / "scripts" / "sync-codex-worker-config.sh"
    subprocess.run(["bash", "-n", str(script)], check=True)


def test_runtime_drift_report_script_has_valid_bash_syntax() -> None:
    script = ROOT / "scripts" / "enoch-runtime-drift-report.sh"
    subprocess.run(["bash", "-n", str(script)], check=True)


def test_operator_scripts_expose_help_without_network_calls() -> None:
    for script_name in (
        "deploy-enoch-runtime.sh",
        "enoch-runtime-drift-report.sh",
        "sync-codex-worker-config.sh",
    ):
        result = subprocess.run(
            [str(ROOT / "scripts" / script_name), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert "Usage:" in result.stdout
