#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/enoch-runtime-drift-report.sh [--output PATH]

Collects a read-only JSON snapshot of the deployed Enoch runtime:
- source checkout version and commit
- control-plane package, service, lane, queue, and recent experiment state
- GB10 and CPU worker Codex versions/config fingerprints
- worker health, service status, and selected resource pressure

The report intentionally prints only hashes/fingerprints for config/auth files;
it never emits token or auth file contents.

Environment overrides:
  ENOCH_CONTROL_HOST          Default: enoch-core.exe.xyz
  ENOCH_GB10_HOST             Default: 100.92.44.26
  ENOCH_CPU_HOST              Default: root@enoch-worker-cpu-1
  ENOCH_CONTROL_RUNTIME       Default: /opt/enoch-control-plane
  ENOCH_GB10_CODEX_HOME       Default: /home/jeremy/.codex
  ENOCH_CPU_CODEX_HOME        Default: /var/lib/enoch-cpu-worker/.codex
EOF
}

output=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      output="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

control_host="${ENOCH_CONTROL_HOST:-enoch-core.exe.xyz}"
gb10_host="${ENOCH_GB10_HOST:-100.92.44.26}"
cpu_host="${ENOCH_CPU_HOST:-root@enoch-worker-cpu-1}"
control_runtime="${ENOCH_CONTROL_RUNTIME:-/opt/enoch-control-plane}"
gb10_codex_home="${ENOCH_GB10_CODEX_HOME:-/home/jeremy/.codex}"
cpu_codex_home="${ENOCH_CPU_CODEX_HOME:-/var/lib/enoch-cpu-worker/.codex}"
source_dir="$(pwd)"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

python3 - "$source_dir" "$control_host" "$gb10_host" "$cpu_host" "$control_runtime" "$gb10_codex_home" "$cpu_codex_home" > "$tmp" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any


source_dir = pathlib.Path(sys.argv[1])
control_host = sys.argv[2]
gb10_host = sys.argv[3]
cpu_host = sys.argv[4]
control_runtime = sys.argv[5]
gb10_codex_home = sys.argv[6]
cpu_codex_home = sys.argv[7]


def run(argv: list[str], *, timeout: int = 30) -> dict[str, Any]:
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def ssh(host: str, command: str, *, timeout: int = 30) -> dict[str, Any]:
    return run(["ssh", host, command], timeout=timeout)


def git_value(args: list[str]) -> str:
    result = run(["git", "-C", str(source_dir), *args])
    return result["stdout"] if result["ok"] else ""


def file_sha(path: pathlib.Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_snapshot() -> dict[str, Any]:
    return {
        "path": str(source_dir),
        "commit": git_value(["rev-parse", "HEAD"]),
        "branch": git_value(["rev-parse", "--abbrev-ref", "HEAD"]),
        "dirty": bool(git_value(["status", "--short"])),
        "version_file_sha256": file_sha(source_dir / "VERSION")[:16],
        "pyproject_sha256": file_sha(source_dir / "pyproject.toml")[:16],
    }


def parse_json_stdout(result: dict[str, Any]) -> Any:
    if not result["ok"] or not result["stdout"]:
        return None
    try:
        return json.loads(result["stdout"])
    except json.JSONDecodeError:
        return None


def control_snapshot() -> dict[str, Any]:
    command = rf"""sudo python3 - <<'PYREMOTE'
import hashlib, json, pathlib, subprocess, urllib.request
runtime = pathlib.Path({control_runtime!r})
cfg_path = pathlib.Path('/etc/enoch-control-plane/config.json')
cfg = json.loads(cfg_path.read_text())
token = cfg['control_api_bearer_token']
def get(path):
    req = urllib.request.Request('http://127.0.0.1:8787' + path, headers={{'Authorization': f'Bearer {{token}}'}})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)
status = get('/control/api/status')
overview = get('/control/api/v1/overview')
def cmd(args):
    p = subprocess.run(args, cwd=runtime, capture_output=True, text=True, check=False)
    return p.stdout.strip() if p.returncode == 0 else ''
print(json.dumps({{
  'host': subprocess.run(['hostname'], capture_output=True, text=True).stdout.strip(),
  'runtime': str(runtime),
  'git_commit': cmd(['git', 'rev-parse', 'HEAD']),
  'version': (runtime / 'VERSION').read_text().strip() if (runtime / 'VERSION').exists() else '',
  'service_active': subprocess.run(['systemctl', 'is-active', 'enoch-control-plane.service'], capture_output=True, text=True).stdout.strip(),
  'status_counts': status.get('counts'),
  'worker_lanes': [
    {{
      'machine_target': lane.get('machine_target'),
      'status': lane.get('status'),
      'active_count': lane.get('active_count'),
      'queued_count': lane.get('queued_count'),
      'dispatch_available': lane.get('dispatch_available'),
      'dispatch_blocker': lane.get('dispatch_blocker'),
      'active_project': (lane.get('active_item') or {{}}).get('project_name'),
      'next_project': (lane.get('next_candidate') or {{}}).get('project_name'),
    }}
    for lane in status.get('worker_lanes', [])
  ],
  'recent_experiments': [
    item.get('project_name') or item.get('title') or item.get('project_id')
    for item in (
      overview.get('recent_events', [])[:10]
      if isinstance(overview.get('recent_events'), list)
      else []
    )
  ],
  'config_fingerprint': hashlib.sha256(cfg_path.read_bytes()).hexdigest()[:16],
}}, sort_keys=True))
PYREMOTE"""
    result = ssh(control_host, command, timeout=45)
    return parse_json_stdout(result) or {
        "host": control_host,
        "error": result["stderr"] or result["stdout"],
    }


def codex_snapshot(
    host: str,
    codex_home: str,
    *,
    service: str | None = None,
    service_scope: str = "system",
) -> dict[str, Any]:
    command = rf"""python3 - <<'PYREMOTE'
import hashlib, json, pathlib, shutil, subprocess, tomllib
home = pathlib.Path({codex_home!r})
codex_candidates = [
    'codex',
    str(home.parent / '.nvm/versions/node/v22.22.1/bin/codex'),
    '/usr/local/bin/codex',
    '/usr/bin/codex',
]
def digest(name):
    p = home / name
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else ''
def size(name):
    p = home / name
    return p.stat().st_size if p.exists() else 0
def mcp_server_names():
    config = home / 'config.toml'
    if not config.exists():
        return []
    data = tomllib.loads(config.read_text())
    return sorted((data.get('mcp_servers') or {}).keys())
def mcp_server_fingerprint(names):
    return hashlib.sha256('\n'.join(names).encode()).hexdigest()[:16] if names else ''
def cmd(args):
    p = subprocess.run(args, capture_output=True, text=True, check=False)
    return {{'ok': p.returncode == 0, 'stdout': p.stdout.strip(), 'stderr': p.stderr.strip(), 'returncode': p.returncode}}
def codex_version():
    for candidate in codex_candidates:
        try:
            p = subprocess.run(
                [candidate, '--version'],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            continue
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.strip()
    return ''
mcp_names = mcp_server_names()
payload = {{
  'host': subprocess.run(['hostname'], capture_output=True, text=True).stdout.strip(),
  'codex_home': str(home),
  'codex_version': codex_version(),
  'config_fingerprint': digest('config.toml'),
  'config_size': size('config.toml'),
  'auth_fingerprint': digest('auth.json'),
  'auth_size': size('auth.json'),
  'plugins_sha': (home / '.tmp/plugins.sha').read_text().strip() if (home / '.tmp/plugins.sha').exists() else '',
  'skills_present': sorted([p.name for p in (home / 'skills').iterdir()]) if (home / 'skills').exists() else [],
  'mcp_server_count': len(mcp_names),
  'mcp_servers_fingerprint': mcp_server_fingerprint(mcp_names),
}}
print(json.dumps(payload, sort_keys=True))
PYREMOTE"""
    if host.startswith("root@"):
        remote = ssh(host, command, timeout=30)
    else:
        remote = ssh(host, command, timeout=30)
    payload = parse_json_stdout(remote) or {
        "host": host,
        "error": remote["stderr"] or remote["stdout"],
    }
    if service:
        systemctl = "systemctl --user" if service_scope == "user" else "systemctl"
        active = ssh(host, f"{systemctl} is-active {service}", timeout=10)
        payload["service_active"] = active["stdout"] if active["ok"] else ""
    return payload


report = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "source": source_snapshot(),
    "control": control_snapshot(),
    "workers": {
        "gb10": codex_snapshot(
            gb10_host,
            gb10_codex_home,
            service="enoch-worker-gate.service",
            service_scope="user",
        ),
        "cpu": codex_snapshot(cpu_host, cpu_codex_home, service="enoch-cpu-worker.service"),
    },
}
print(json.dumps(report, indent=2, sort_keys=True))
PY

if [[ -n "$output" ]]; then
  mkdir -p "$(dirname "$output")"
  cp "$tmp" "$output"
  echo "wrote drift report: $output"
else
  cat "$tmp"
fi
