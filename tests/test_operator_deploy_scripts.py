from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_deploy_runtime_script_has_valid_bash_syntax() -> None:
    script = ROOT / "scripts" / "deploy-enoch-runtime.sh"
    subprocess.run(["bash", "-n", str(script)], check=True)


def test_deploy_runtime_can_run_longhaul_guard() -> None:
    text = (ROOT / "scripts" / "deploy-enoch-runtime.sh").read_text(encoding="utf-8")

    assert "ENOCH_CONTROL_LONGHAUL_GUARD" in text
    assert "scripts/enoch-longhaul-guard.sh" in text


def test_sync_codex_worker_config_script_has_valid_bash_syntax() -> None:
    script = ROOT / "scripts" / "sync-codex-worker-config.sh"
    subprocess.run(["bash", "-n", str(script)], check=True)


def test_sync_codex_worker_config_has_archive_safety_contract() -> None:
    text = (ROOT / "scripts" / "sync-codex-worker-config.sh").read_text(
        encoding="utf-8"
    )

    assert "symlink entries are not allowed in sync payload" in text
    assert "hardlink entries are not allowed in sync payload" in text
    assert "stage=\\$(mktemp -d)" in text
    assert 'tar -C \\"\\$stage\\" -xf -' in text
    assert "auth.json must be a regular file" in text
    assert "config.toml must be a regular file" in text


def test_sync_codex_worker_config_rejects_source_symlinks(tmp_path) -> None:
    source = tmp_path / "gb10-codex"
    dest = tmp_path / "cpu-codex"
    victims = tmp_path / "victims"
    source.mkdir()
    dest.mkdir()
    victims.mkdir()
    victim_auth = victims / "victim-auth"
    victim_config = victims / "victim-config.toml"
    victim_auth.write_text("auth-secret\n", encoding="utf-8")
    victim_config.write_text("[safe]\nvalue = 1\n", encoding="utf-8")
    (source / "auth.json").symlink_to(victim_auth)
    (source / "config.toml").symlink_to(victim_config)
    (dest / "auth.json").write_text('{"ok": true}\n', encoding="utf-8")
    (dest / "config.toml").write_text(
        '[projects."/var/lib/enoch-cpu-worker/projects/existing"]\n'
        'trust_level = "trusted"\n',
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "ssh").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
host="$1"
shift
bash -c "$*"
""",
        encoding="utf-8",
    )
    (fake_bin / "ssh").chmod(0o755)
    (fake_bin / "sudo").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-u" ]]; then
  shift 3
fi
exec "$@"
""",
        encoding="utf-8",
    )
    (fake_bin / "sudo").chmod(0o755)
    (fake_bin / "chown").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (fake_bin / "chown").chmod(0o755)
    before_auth_mode = victim_auth.stat().st_mode & 0o777
    before_config = victim_config.read_text(encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GB10_HOST": "gb10",
        "GB10_CODEX_HOME": str(source),
        "CPU_HOST": "cpu",
        "CPU_CODEX_HOME": str(dest),
        "CPU_WORKER_USER": "nobody",
    }

    result = subprocess.run(
        [str(ROOT / "scripts" / "sync-codex-worker-config.sh")],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "symlink entries are not allowed" in result.stderr
    assert not (dest / "auth.json").is_symlink()
    assert not (dest / "config.toml").is_symlink()
    assert victim_auth.stat().st_mode & 0o777 == before_auth_mode
    assert victim_config.read_text(encoding="utf-8") == before_config


def test_sync_codex_worker_config_accepts_regular_runtime_files(tmp_path) -> None:
    source = tmp_path / "gb10-codex"
    dest = tmp_path / "cpu-codex"
    source.mkdir()
    dest.mkdir()
    (source / "auth.json").write_text('{"source": true}\n', encoding="utf-8")
    (source / "config.toml").write_text("[plugins]\nexample = true\n", encoding="utf-8")
    (source / "skills").mkdir()
    (source / "skills" / "enoch-worker").mkdir()
    (source / "skills" / "enoch-worker" / "SKILL.md").write_text(
        "# skill\n", encoding="utf-8"
    )
    (dest / "auth.json").write_text('{"old": true}\n', encoding="utf-8")
    (dest / "config.toml").write_text(
        '[projects."/var/lib/enoch-cpu-worker/projects/existing"]\n'
        'trust_level = "trusted"\n',
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "ssh").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
host="$1"
shift
bash -c "$*"
""",
        encoding="utf-8",
    )
    (fake_bin / "ssh").chmod(0o755)
    (fake_bin / "sudo").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-u" ]]; then
  shift 3
fi
exec "$@"
""",
        encoding="utf-8",
    )
    (fake_bin / "sudo").chmod(0o755)
    (fake_bin / "chown").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (fake_bin / "chown").chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GB10_HOST": "gb10",
        "GB10_CODEX_HOME": str(source),
        "CPU_HOST": "cpu",
        "CPU_CODEX_HOME": str(dest),
        "CPU_WORKER_USER": "nobody",
    }

    result = subprocess.run(
        [str(ROOT / "scripts" / "sync-codex-worker-config.sh")],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads((dest / "auth.json").read_text(encoding="utf-8")) == {
        "source": True
    }
    config = (dest / "config.toml").read_text(encoding="utf-8")
    assert "[plugins]" in config
    assert "Preserved CPU worker project trust entries" in config
    assert "/var/lib/enoch-cpu-worker/projects/existing" in config
    assert (dest / "skills" / "enoch-worker" / "SKILL.md").is_file()


def test_runtime_drift_report_script_has_valid_bash_syntax() -> None:
    script = ROOT / "scripts" / "enoch-runtime-drift-report.sh"
    subprocess.run(["bash", "-n", str(script)], check=True)


def test_runtime_drift_report_checks_gb10_user_service() -> None:
    script = (ROOT / "scripts" / "enoch-runtime-drift-report.sh").read_text(
        encoding="utf-8"
    )

    assert 'service_scope: str = "system"' in script
    assert 'systemctl = "systemctl --user" if service_scope == "user"' in script
    assert 'service_scope="user"' in script
    assert "'mcp_servers': sorted(" not in script
    assert "mcp_names = mcp_server_names()" in script
    assert "'mcp_server_count': len(mcp_names)" in script
    assert "'mcp_servers_fingerprint': mcp_server_fingerprint(mcp_names)" in script


def test_runtime_drift_report_executes_without_literal_mcp_names(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_ssh = fake_bin / "ssh"
    fake_ssh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
host="$1"
case "$host" in
  enoch-core.exe.xyz)
    printf '%s\n' '{"host":"control","status_counts":{},"worker_lanes":[]}'
    ;;
  100.92.44.26)
    printf '%s\n' '{"host":"gb10","mcp_server_count":2,"mcp_servers_fingerprint":"gb10hash"}'
    ;;
  root@enoch-worker-cpu-1)
    printf '%s\n' '{"host":"cpu","mcp_server_count":2,"mcp_servers_fingerprint":"cpuhash"}'
    ;;
  *)
    printf 'unexpected host: %s\n' "$host" >&2
    exit 2
    ;;
esac
""",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o755)
    output = tmp_path / "runtime-drift.json"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }

    result = subprocess.run(
        [
            str(ROOT / "scripts" / "enoch-runtime-drift-report.sh"),
            "--output",
            str(output),
        ],
        check=False,
        env=env,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    for snapshot in report["workers"].values():
        assert "mcp_servers" not in snapshot
        assert snapshot["mcp_server_count"] == 2
        assert snapshot["mcp_servers_fingerprint"]


def test_runtime_drift_report_records_probe_timeouts() -> None:
    script = (ROOT / "scripts" / "enoch-runtime-drift-report.sh").read_text(
        encoding="utf-8"
    )

    assert "except subprocess.TimeoutExpired as exc:" in script
    assert '"returncode": -1' in script
    assert '"stderr": f"command timed out after {timeout}s:' in script


def test_deploy_script_restarts_gb10_user_service() -> None:
    script = (ROOT / "scripts" / "deploy-enoch-runtime.sh").read_text(encoding="utf-8")

    assert 'default_service_scope="user"' in script
    assert (
        'service_scope="${ENOCH_DEPLOY_SERVICE_SCOPE:-$default_service_scope}"'
        in script
    )
    assert "systemctl --user restart" in script


def test_deploy_script_retries_worker_health_after_restart() -> None:
    script = (ROOT / "scripts" / "deploy-enoch-runtime.sh").read_text(encoding="utf-8")

    assert "for attempt in \\$(seq 1 30)" in script
    assert "curl -fsS http://127.0.0.1:8787/healthz" in script


def test_deploy_script_waits_for_control_health_before_smoke() -> None:
    script = (ROOT / "scripts" / "deploy-enoch-runtime.sh").read_text(encoding="utf-8")

    assert "wait_for_remote_health" in script
    assert script.index("wait_for_remote_health") < script.index(
        "running control dashboard smoke on $host"
    )


def test_deploy_script_installs_with_uv_pip_for_restored_venvs() -> None:
    script = (ROOT / "scripts" / "deploy-enoch-runtime.sh").read_text(encoding="utf-8")

    assert "'$uv_bin' pip install --python .venv/bin/python -e ." in script
    assert "python -m pip install" not in script


def test_operator_scripts_expose_help_without_network_calls() -> None:
    for script_name in (
        "deploy-enoch-runtime.sh",
        "enoch-longhaul-guard.sh",
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


def test_longhaul_guard_script_has_valid_bash_syntax() -> None:
    script = ROOT / "scripts" / "enoch-longhaul-guard.sh"
    subprocess.run(["bash", "-n", str(script)], check=True)


def test_maintenance_scripts_have_valid_bash_syntax() -> None:
    for name in ("enoch-maintenance-stop.sh", "enoch-maintenance-resume.sh"):
        subprocess.run(["bash", "-n", str(ROOT / "scripts" / name)], check=True)


def test_maintenance_stop_resume_scripts_preserve_backup_timer_contract() -> None:
    stop = (ROOT / "scripts" / "enoch-maintenance-stop.sh").read_text(
        encoding="utf-8"
    )
    resume = (ROOT / "scripts" / "enoch-maintenance-resume.sh").read_text(
        encoding="utf-8"
    )
    combined = stop + resume

    for timer in (
        "enoch-research-autopilot.timer",
        "enoch-corpus-import-autopilot.timer",
        "enoch-queue-alert-check.timer",
        "enoch-source-lineage-check.timer",
    ):
        assert timer in stop
        assert timer in resume
    assert "enoch-paper-draft-next.timer" in stop
    assert "ENOCH_MAINTENANCE_RESUME_ENABLE_PAPER_DRAFT" in resume
    assert "systemctl disable --now" in stop
    assert "systemctl enable --now" in resume
    assert "/control/pause" in stop
    assert "/control/resume" in resume
    assert "/control/api/status" in combined
    assert "enoch-postgres-backup.timer" in combined
    assert "resume-enoch-automation" in resume
    assert "pgrep -af 'codex|enoch_codex_runner|enoch_codex_dispatch'" in stop
    assert "worker process checks failed" in stop
    assert '{"disabled", "masked", "not-found"}' in stop
    assert "StrictHostKeyChecking=accept-new" in stop
    assert "ENOCH_MAINTENANCE_WORKER_SSH_TIMEOUT" in stop
    assert "timeout=timeout_seconds" in stop
    assert "worker ssh check timed out" in stop


def test_longhaul_guard_links_incidents_to_durable_checks() -> None:
    script = ROOT / "scripts" / "enoch-longhaul-guard.sh"
    text = script.read_text(encoding="utf-8")

    assert "codex exec --skip-git-repo-check --json -C /tmp" in text
    assert 'sudo -u "$cpu_worker_user" -H' in text
    assert "/control/api/alerts/queue-check" in text
    assert '"dry_run": true' in text
    assert '"dry_run": false' in text
    assert '"refresh_worker": True' in text
    assert "/control/api/v1/automation-readiness" in text
    assert "post_repair_readiness" in text
    assert "readiness_blockers" in text
    assert "stale active worker lane exists" in text
    assert "missing_queue_check_proof" in text
    assert "post_repair_queue_check" in text
    assert "queue_alert_findings_present" in text


def test_longhaul_guard_records_unrepairable_readiness_stale_active(
    tmp_path,
) -> None:
    fake_ssh = tmp_path / "ssh"
    fake_ssh.write_text(
        """#!/usr/bin/env python3
import json
import sys

command = sys.argv[-1]
if "codex exec" in command:
    print(json.dumps({"item": {"type": "agent_message", "text": "ok"}}))
elif "/control/api/v1/automation-readiness" in command:
    print(json.dumps({
        "ok": False,
        "status": "blocked",
        "label": "Long-haul mode: BLOCKED - stale active worker lane exists",
        "blockers": ["stale active worker lane exists"],
        "summary": {"active": 2, "queued": 8},
    }))
elif "/control/api/status" in command:
    print(json.dumps({"counts": {"active": 2, "queued": 8}}))
elif "/control/api/alerts/queue-check" in command:
    print(json.dumps({
        "ok": True,
        "should_alert": False,
        "findings": [],
        "trace_id": "queue-check-test",
    }))
else:
    print(json.dumps({"ok": True}))
""",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o755)
    output = tmp_path / "guard.json"
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "ENOCH_CONTROL_HOST": "control-host",
        "ENOCH_CPU_HOST": "cpu-host",
    }

    result = subprocess.run(
        [str(ROOT / "scripts" / "enoch-longhaul-guard.sh"), "--output", str(output)],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    issue = report["issues"][0]
    assert result.returncode == 1
    assert report["ok"] is False
    assert report["cpu_codex_smoke"]["ok"] is True
    assert report["readiness_blockers"] == ["stale active worker lane exists"]
    assert issue["observed_issue"] == "stale_active_worker_lane"
    assert issue["proof_state"] == "missing_queue_check_proof"
    assert issue["repairable_by_guard"] is False
    assert "do not live-reconcile yet" in issue["immediate_mitigation"]


def test_longhaul_guard_fails_on_non_stale_queue_alert_findings(tmp_path) -> None:
    fake_ssh = tmp_path / "ssh"
    fake_ssh.write_text(
        """#!/usr/bin/env python3
import json
import sys

command = sys.argv[-1]
if "codex exec" in command:
    print(json.dumps({"item": {"type": "agent_message", "text": "ok"}}))
elif "/control/api/v1/automation-readiness" in command:
    print(json.dumps({
        "ok": True,
        "status": "ready",
        "label": "Long-haul mode: READY",
        "blockers": [],
        "summary": {"active": 1, "queued": 8},
    }))
elif "/control/api/status" in command:
    print(json.dumps({"counts": {"active": 1, "queued": 8}}))
elif "/control/api/alerts/queue-check" in command:
    print(json.dumps({
        "ok": True,
        "should_alert": True,
        "trace_id": "queue-check-worker-settling",
        "findings": [{
            "source": "worker_settling",
            "message": "worker is settling a completed VM run",
            "data": {"worker_run": {"run_id": "run-settling"}},
        }],
    }))
else:
    print(json.dumps({"ok": True}))
""",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o755)
    output = tmp_path / "guard.json"
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "ENOCH_CONTROL_HOST": "control-host",
        "ENOCH_CPU_HOST": "cpu-host",
    }

    result = subprocess.run(
        [str(ROOT / "scripts" / "enoch-longhaul-guard.sh"), "--output", str(output)],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert result.returncode == 1
    assert report["ok"] is False
    assert report["readiness_before"]["ok"] is True
    assert report["issues"][0]["observed_issue"] == "queue_alert_findings_present"
    assert "worker_settling" in report["issues"][0]["finding_sources"]
