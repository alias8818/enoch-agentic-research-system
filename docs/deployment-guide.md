# Deployment guide

This guide describes a two-machine Enoch deployment that mirrors the reference setup:

- **Control VM** — hosts the FastAPI control plane, dashboard, queue state, paper review APIs, alert timer, and corpus/export tooling.
- **Worker machine** — hosts the wake gate used by OMX/Codex runs, tracks process trees and telemetry, and stores project workspaces and evidence.

A single-machine development deployment is also possible: run both services on localhost and set `worker_wake_gate_url` to the same host.

## 1. Prerequisites

Install on the control VM:

- Linux with systemd
- Python 3.11+
- `uv`
- `git`
- network access to the worker

Install on the worker:

- Linux with systemd
- Python 3.11+
- `uv`
- `git`
- OMX/Codex CLI stack used for agent execution
- optional NVIDIA telemetry libraries for GPU visibility

## 2. Clone and install

On each machine:

```bash
sudo mkdir -p /opt/enoch-agentic-research-system
sudo chown "$USER":"$USER" /opt/enoch-agentic-research-system
git clone https://github.com/alias8818/enoch-agentic-research-system.git /opt/enoch-agentic-research-system
cd /opt/enoch-agentic-research-system
uv venv --python /usr/bin/python3 .venv
uv pip install --python .venv/bin/python -e .
uv run pytest -q
```

For forks, replace `alias8818` with your GitHub owner.

## 3. Configure the control VM

The helper script can install dependencies, copy the checkout into `/opt`, create config/state directories, and install systemd units:

```bash
sudo scripts/install-control-plane.sh
```

If you prefer manual setup, create config and state directories:

```bash
sudo mkdir -p /etc/enoch /var/lib/enoch-control-plane
sudo cp /opt/enoch-agentic-research-system/config.example.json /etc/enoch/config.json
sudo editor /etc/enoch/config.json
```

Minimum required fields:

```json
{
  "listen_host": "0.0.0.0",
  "listen_port": 8787,
  "state_dir": "/var/lib/enoch-control-plane/state",
  "project_root": "/var/lib/enoch-control-plane/projects",
  "dispatch_script_path": "/opt/enoch-agentic-research-system/deploy/enoch_omx_dispatch.sh",
  "omx_inbound_bearer_token": "generate-a-long-random-token",
  "completion_callback_url": "https://automation.example.com/webhook/omx-wake-ready",
  "completion_callback_token": "generate-a-long-random-token",
  "worker_wake_gate_url": "http://worker.example:8787",
  "worker_wake_gate_bearer_token": "worker-api-token"
}
```

Generate tokens with a tool such as:

```bash
python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
```

## 4. Configure the worker

The helper script can install dependencies and write a worker-focused example config:

```bash
scripts/install-worker.sh
```

The worker can run the same app with a worker-focused config. For a minimal local worker, copy `config.example.json`, set `state_dir`, `project_root`, and `omx_inbound_bearer_token`, then run the service on port `8787`.

The control VM uses:

- `worker_wake_gate_url` to call the worker API;
- `worker_wake_gate_bearer_token` for authenticated worker checks;
- `paper_evidence_sync_*` settings when importing evidence from worker project folders.

## 5. Install systemd service on the control VM

```bash
sudo cp /opt/enoch-agentic-research-system/deploy/omx-wake-gate.service /etc/systemd/system/enoch-control-plane.service
sudo systemctl daemon-reload
sudo systemctl enable --now enoch-control-plane.service
sudo systemctl status enoch-control-plane.service
```

Check health:

```bash
curl -fsS http://127.0.0.1:8787/healthz
```

Open the dashboard:

```text
http://<control-vm>:8787/dashboard
```

Use `omx_inbound_bearer_token` as the dashboard/API token.

## 6. Enable Pushover queue alerts

Pushover is optional but recommended for queue hang/stoppage alerting.

In `/etc/enoch/config.json`:

```json
{
  "pushover_alerts_enabled": true,
  "pushover_app_token": "your-pushover-application-token",
  "pushover_user_key": "your-pushover-user-key",
  "queue_alert_cooldown_sec": 1800,
  "queue_alert_hang_after_sec": 3600
}
```

Install the timer:

```bash
sudo cp /opt/enoch-agentic-research-system/deploy/enoch-queue-alert-check.service /etc/systemd/system/
sudo cp /opt/enoch-agentic-research-system/deploy/enoch-queue-alert-check.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now enoch-queue-alert-check.timer
systemctl list-timers enoch-queue-alert-check.timer
```

Manual alert/preflight check:

```bash
sudo OMX_WAKE_GATE_CONFIG=/etc/enoch/config.json /opt/enoch-agentic-research-system/deploy/enoch_queue_alert_check.py
```


## 7. Supabase-native ideas and draft-only paper production

Notion sync is obsolete in the current runtime. Idea intake should go through the Supabase-backed control-plane API:

```bash
curl -fsS -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8787/control/intake/ideas \
  -d '{"dry_run": true, "ideas": [{"idea_id": "smoke-idea", "title": "Smoke Idea", "idea_status": "testing"}]}'
```

Inspect the canonical ideas workbench:

```bash
curl -fsS -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8787/control/api/intake/ideas | python3 -m json.tool
```

Legacy `enoch-notion-sync.*` units are not installed by default and the checked-in unit/script are inert compatibility stubs. Do not enable Notion sync for new deployments.

Paper drafting is dispatch-independent, but it is intentionally disabled by default because it can spend model tokens. The one-shot script exits before reading credentials or calling the control plane unless `ENOCH_ENABLE_PAPER_DRAFT_NEXT=1` is set. Install the timer only when a human explicitly wants draft-only paper production:

```bash
cd /opt/enoch-agentic-research-system
ENOCH_INSTALL_PAPER_DRAFT_NEXT_UNITS=1 sudo -E scripts/install-control-plane.sh
sudo systemctl edit enoch-paper-draft-next.service
# Add:
# [Service]
# Environment=ENOCH_ENABLE_PAPER_DRAFT_NEXT=1
sudo systemctl daemon-reload
sudo systemctl enable --now enoch-paper-draft-next.timer
# or one-shot, after the opt-in environment is present:
sudo systemctl start enoch-paper-draft-next.service
```

To guarantee no draft-next work runs, disable and mask both units. The script still remains token-safe by default if a future deploy copies the units back.

```bash
sudo systemctl disable --now enoch-paper-draft-next.timer enoch-paper-draft-next.service || true
sudo systemctl mask --now enoch-paper-draft-next.timer enoch-paper-draft-next.service
```

By default, the queue alert pump is execution-only: it dispatches the next queued project when the control plane is idle and dispatch-safe, and it does not draft papers. To restore the older draft-before-dispatch compatibility behavior, set `"queue_pump_paper_draft_enabled": true`; if `/control/papers/draft-next` drafts a paper, that timer tick skips `/control/dispatch-next` so publication writing catches up before another idea is launched.

If dispatch must remain disabled, leave `enoch-queue-alert-check.timer` disabled. Re-enable that timer only when the worker lane is healthy and dispatch should resume.

## 8. Smoke-test core API paths

```bash
TOKEN=$(python3 - <<'PY'
import json
from pathlib import Path

print(json.loads(Path('/etc/enoch/config.json').read_text(encoding='utf-8'))['omx_inbound_bearer_token'])
PY
)

curl -fsS -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8787/control/api/status | python3 -m json.tool

curl -fsS -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"wake_gate_url":"http://worker.example:8787","bearer_token":"worker-api-token","require_paused":false,"strict":false}' \
  http://127.0.0.1:8787/control/api/preflight | python3 -m json.tool
```

## 9. Dispatch flow

The dispatch path is intentionally guarded:

1. queue item exists;
2. control plane is not paused;
3. maintenance mode is not active;
4. worker preflight is healthy;
5. no conflicting active GPU lane exists;
6. dispatch script launches the agent run;
7. wake gate tracks process/telemetry truth;
8. completion callback or status update is emitted only after the gate is satisfied.

Use dry-run dispatch first:

```bash
curl -fsS -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"dry_run":true,"requested_by":"operator"}' \
  http://127.0.0.1:8787/control/dispatch-next | python3 -m json.tool
```

## 9. Paper artifact workflow

The control plane can rewrite and package generated research artifacts when paper rows and evidence are present.

Recommended model-provider settings for Synthetic.new / GLM-5.1:

```json
{
  "paper_writer_provider": "synthetic.new",
  "paper_writer_base_url": "https://api.synthetic.new/openai/v1",
  "paper_writer_model": "hf:zai-org/GLM-5.1",
  "paper_writer_api_key": "your-provider-key",
  "paper_writer_fallback_enabled": true,
  "paper_evidence_sync_enabled": true
}
```

Do not publish generated artifacts until the corpus packaging/provenance lint pass.

## 10. What is not included

This repository does not include:

- live secrets;
- private production config;
- generated paper corpus artifacts;
- old workflow-tool exports;
- private run state databases;
- production logs.

Those are intentionally excluded. Use the examples and docs to recreate a clean deployment.
