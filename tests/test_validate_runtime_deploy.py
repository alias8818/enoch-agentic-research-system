from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import validate_runtime_deploy


def test_runtime_deploy_validator_rejects_hash_drift(tmp_path: Path) -> None:
    source = tmp_path / "source"
    runtime = tmp_path / "runtime"
    (source / "enoch_control_plane" / "control_plane").mkdir(parents=True)
    (runtime / "enoch_control_plane" / "control_plane").mkdir(parents=True)
    (source / "enoch_control_plane" / "control_plane" / "router.py").write_text("source\n", encoding="utf-8")
    (runtime / "enoch_control_plane" / "control_plane" / "router.py").write_text("runtime\n", encoding="utf-8")

    report = validate_runtime_deploy.validate_runtime(
        source=source,
        runtime=runtime,
        paths=["enoch_control_plane/control_plane/router.py"],
    )

    assert report["ok"] is False
    assert report["failures"] == ["hash drift: enoch_control_plane/control_plane/router.py"]
    assert report["files"][0]["source_sha256"] != report["files"][0]["runtime_sha256"]


def test_runtime_deploy_validator_rejects_runtime_missing_file(tmp_path: Path) -> None:
    source = tmp_path / "source"
    runtime = tmp_path / "runtime"
    (source / "scripts").mkdir(parents=True)
    runtime.mkdir()
    (source / "scripts" / "validate_state_contract.py").write_text("print('ok')\n", encoding="utf-8")

    report = validate_runtime_deploy.validate_runtime(
        source=source,
        runtime=runtime,
        paths=["scripts/validate_state_contract.py"],
    )

    assert report["ok"] is False
    assert report["failures"] == ["missing runtime file: scripts/validate_state_contract.py"]


def test_runtime_deploy_validator_accepts_matching_files_and_commit(tmp_path: Path) -> None:
    source = tmp_path / "source"
    runtime = tmp_path / "runtime"
    source.mkdir()
    runtime.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=source, check=True)
    (source / "README.md").write_text("same\n", encoding="utf-8")
    (runtime / "README.md").write_text("same\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=source, check=True)
    expected = subprocess.run(["git", "rev-parse", "HEAD"], cwd=source, text=True, stdout=subprocess.PIPE, check=True).stdout.strip()

    report = validate_runtime_deploy.validate_runtime(
        source=source,
        runtime=runtime,
        paths=["README.md"],
        expected_commit=expected,
    )

    assert report["ok"] is True
    assert report["failures"] == []
    assert report["source_commit"] == expected
    assert report["expected_commit"] == expected


def test_runtime_deploy_cli_outputs_json_and_nonzero_on_drift(tmp_path: Path, capsys) -> None:
    source = tmp_path / "source"
    runtime = tmp_path / "runtime"
    source.mkdir()
    runtime.mkdir()
    (source / "README.md").write_text("source\n", encoding="utf-8")
    (runtime / "README.md").write_text("runtime\n", encoding="utf-8")

    code = validate_runtime_deploy.main([
        "--source",
        str(source),
        "--runtime",
        str(runtime),
        "--path",
        "README.md",
    ])

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["failures"] == ["hash drift: README.md"]
