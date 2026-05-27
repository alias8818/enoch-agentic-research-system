#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/deploy-enoch-runtime.sh --profile control
  scripts/deploy-enoch-runtime.sh --profile cpu-worker
  scripts/deploy-enoch-runtime.sh --profile gb10-worker

Environment overrides:
  ENOCH_DEPLOY_HOST          SSH host. Defaults depend on --profile.
  ENOCH_DEPLOY_RUNTIME       Remote runtime path. Defaults depend on --profile.
  ENOCH_DEPLOY_SERVICE       systemd service. Defaults depend on --profile.
  ENOCH_DEPLOY_UV            Remote uv binary. Default: uv, or /root/.local/bin/uv for cpu-worker.
  ENOCH_DEPLOY_SOURCE        Local source checkout. Default: current working directory.
  ENOCH_CONTROL_SMOKE        For control profile, run dashboard_v2_smoke.py when set to 1.
EOF
}

profile=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      profile="${2:-}"
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

if [[ -z "$profile" ]]; then
  usage >&2
  exit 2
fi

case "$profile" in
  control)
    default_host="enoch-core.exe.xyz"
    default_runtime="/opt/enoch-control-plane"
    default_service="enoch-control-plane.service"
    default_uv="uv"
    ;;
  cpu-worker)
    default_host="root@enoch-worker-cpu-1"
    default_runtime="/opt/enoch-control-plane"
    default_service="enoch-cpu-worker.service"
    default_uv="/root/.local/bin/uv"
    ;;
  gb10-worker)
    default_host="100.92.44.26"
    default_runtime="/home/jeremy/projects/enoch_testing_ground/enoch-control-plane"
    default_service="enoch-worker-gate.service"
    default_uv="uv"
    ;;
  *)
    echo "unknown profile: $profile" >&2
    usage >&2
    exit 2
    ;;
esac

host="${ENOCH_DEPLOY_HOST:-$default_host}"
runtime="${ENOCH_DEPLOY_RUNTIME:-$default_runtime}"
service="${ENOCH_DEPLOY_SERVICE:-$default_service}"
uv_bin="${ENOCH_DEPLOY_UV:-$default_uv}"
source_dir="${ENOCH_DEPLOY_SOURCE:-$(pwd)}"

if [[ ! -f "$source_dir/scripts/validate_runtime_deploy.py" ]]; then
  echo "source checkout missing scripts/validate_runtime_deploy.py: $source_dir" >&2
  exit 1
fi

rsync_args=(
  -az --delete
  --exclude .git
  --exclude .venv
  --exclude __pycache__
  --exclude .pytest_cache
  --exclude .ruff_cache
  --exclude .mypy_cache
  --exclude node_modules
  --exclude dist
  --exclude build
)

echo "deploying $profile to $host:$runtime"
rsync "${rsync_args[@]}" "$source_dir/" "$host:$runtime/"

echo "installing editable package on $host"
ssh "$host" "set -euo pipefail; cd '$runtime'; '$uv_bin' pip install --python .venv/bin/python -e ."

echo "restarting $service on $host"
ssh "$host" "sudo systemctl restart '$service'"

echo "validating runtime deploy on $host"
ssh "$host" "set -euo pipefail; cd '$runtime'; python3 scripts/validate_runtime_deploy.py --source '$runtime' --runtime '$runtime' --summary-only"

case "$profile" in
  control)
    if [[ "${ENOCH_CONTROL_SMOKE:-0}" == "1" ]]; then
      echo "running control dashboard smoke on $host"
      ssh "$host" "set -euo pipefail; token=\$(sudo jq -r .control_api_bearer_token /etc/enoch-control-plane/config.json); cd '$runtime'; ENOCH_CONTROL_TOKEN=\"\$token\" python3 scripts/dashboard_v2_smoke.py --base-url http://127.0.0.1:8787 --check-legacy-dashboard-redirect"
    fi
    ;;
  cpu-worker|gb10-worker)
    echo "checking worker health on $host"
    ssh "$host" "curl -fsS http://127.0.0.1:8787/healthz >/dev/null"
    ;;
esac

echo "deploy complete: $profile $host $runtime"
