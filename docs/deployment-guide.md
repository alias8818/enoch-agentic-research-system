# Deployment guide

This guide describes a two-machine Enoch deployment that mirrors the reference setup:

- **Control VM** — hosts the FastAPI control plane, dashboard, local Postgres/control-plane queue state, publication automation APIs, alert timers, and corpus/export tooling. In the reference deployment this is `enoch-core` with the checkout at `/opt/enoch-control-plane`.
- **Worker machine** — hosts the GB10 worker gate used by Codex runs, tracks process trees and telemetry, and stores project workspaces and evidence. In the reference deployment this runs from `~/projects/enoch_testing_ground/enoch-control-plane`.

A single-machine development deployment is also possible: run both services on localhost and set `worker_wake_gate_url` to the same host.

For the canonical reference host paths, storage authority, worker gate, and
compatibility boundaries, see
[`current-runtime-snapshot.md`](current-runtime-snapshot.md).

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
- Codex CLI stack used for agent execution
- optional NVIDIA telemetry libraries for GPU visibility

## 2. Clone and install

On each machine:

```bash
sudo mkdir -p /opt/enoch-control-plane
sudo chown "$USER":"$USER" /opt/enoch-control-plane
git clone https://github.com/alias8818/enoch-agentic-research-system.git /opt/enoch-control-plane
cd /opt/enoch-control-plane
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
sudo mkdir -p /etc/enoch-control-plane /var/lib/enoch-control-plane
sudo cp /opt/enoch-control-plane/config.example.json /etc/enoch-control-plane/config.json
sudo editor /etc/enoch-control-plane/config.json
```

Minimum required fields:

```json
{
  "listen_host": "0.0.0.0",
  "listen_port": 8787,
  "state_dir": "/var/lib/enoch-control-plane/state",
  "project_root": "/var/lib/enoch-control-plane/projects",
  "dispatch_script_path": "/opt/enoch-control-plane/deploy/enoch_codex_dispatch.sh",
  "control_api_bearer_token": "generate-a-long-random-token",
  "completion_callback_url": "https://automation.example.com/webhook/enoch-control-plane-wake-ready",
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

The worker can run the same app with a worker-focused config. For a minimal local worker, copy `config.example.json`, set `state_dir`, `project_root`, and `control_api_bearer_token`, then run the service on port `8787`.

The control VM uses:

- `worker_wake_gate_url` to call the worker API. The field name is a compatibility name; operator docs should call this the worker gate.
- `worker_wake_gate_bearer_token` for authenticated worker checks;
- `paper_evidence_sync_*` settings when importing evidence from worker project folders.

## 5. Install systemd service on the control VM

```bash
sudo cp /opt/enoch-control-plane/deploy/enoch-worker-gate.service /etc/systemd/system/enoch-control-plane.service
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

Use `control_api_bearer_token` as the dashboard/API token. The legacy worker-gate dashboard remains at `/dashboard`; the redesigned operator console is:

```text
http://<control-vm>:8787/control/dashboard
```

The redesigned `/control/dashboard` shell uses bounded `/control/api/v1/*` read models by default; reserve heavyweight legacy status endpoints for debugging only.

## 6. Enable Pushover queue alerts

Pushover is optional but recommended for queue hang/stoppage alerting.

In `/etc/enoch-control-plane/config.json`:

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
sudo cp /opt/enoch-control-plane/deploy/enoch-queue-alert-check.service /etc/systemd/system/
sudo cp /opt/enoch-control-plane/deploy/enoch-queue-alert-check.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now enoch-queue-alert-check.timer
systemctl list-timers enoch-queue-alert-check.timer
```

Manual alert/preflight check:

```bash
sudo ENOCH_CONFIG=/etc/enoch-control-plane/config.json /opt/enoch-control-plane/deploy/enoch_queue_alert_check.py
```


## 7. Local Postgres ideas and draft-only paper production

Notion sync is obsolete in the current runtime. Idea intake should go through the control-plane API backed by the current local Postgres/control-plane store:

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
cd /opt/enoch-control-plane
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

By default, the queue alert pump is execution-only: it dispatches the next queued project when the control plane is idle and dispatch-safe, and it does not draft papers. It also does not launch follow-up investigations unless `"queue_pump_followup_launch_enabled": true` is set. With that flag enabled, an idle pump tick with no queued candidate dry-runs `/control/api/v1/followups/launch-next`, queues one bounded follow-up if selected, then dispatches it through `/control/dispatch-next`. To restore the older draft-before-dispatch compatibility behavior, set `"queue_pump_paper_draft_enabled": true`; if `/control/papers/draft-next` drafts a paper, that timer tick skips `/control/dispatch-next` so publication writing catches up before another idea is launched.

If dispatch must remain disabled, leave `enoch-queue-alert-check.timer` disabled. Re-enable that timer only when the worker lane is healthy and dispatch should resume.

The Research Facility autopilot is the bounded end-to-end path for idea generation through positive-gated paper finalization. It is also opt-in and inert by default. Install/enable it only after the provider proxy, worker gate, and paper writer have passed smoke tests:

```bash
cd /opt/enoch-control-plane
ENOCH_INSTALL_RESEARCH_AUTOPILOT_UNITS=1 sudo -E scripts/install-control-plane.sh
sudo systemctl edit enoch-research-autopilot.service
# Add:
# [Service]
# Environment=ENOCH_ENABLE_RESEARCH_AUTOPILOT=1
# Environment=ENOCH_RESEARCH_AUTOPILOT_DISPATCH=1
# Environment=ENOCH_RESEARCH_AUTOPILOT_WAIT=1
# Environment=ENOCH_RESEARCH_AUTOPILOT_PAPERS=1
sudo systemctl daemon-reload
sudo systemctl enable --now enoch-research-autopilot.timer
```

Each autopilot tick calls `/control/api/research/run-cycle` and is capped at one provider request, one promotion, one dispatch, one paper draft, and one finalization package. It preserves the broad queue pause and the paper stage still blocks negative/non-positive decision artifacts. The checked-in timer interval is not the operator contract; the current `enoch-core` timer cadence should be inspected with `systemctl list-timers enoch-research-autopilot.timer` before reporting live frequency.

## Runtime provenance check

If the deployed runtime is copied into `/opt/enoch-control-plane`, verify it
against the source checkout before reporting a deploy as live:

```bash
cd /opt/enoch-release/enoch-agentic-research-system
python3 scripts/validate_runtime_deploy.py \
  --source /opt/enoch-release/enoch-agentic-research-system \
  --runtime /opt/enoch-control-plane \
  --expected-commit origin/main \
  --summary-only
```

This check fails if the source checkout is not at the expected commit, if a
runtime file is missing, or if any checked runtime file hash differs from the
source checkout.

## 8. Smoke-test core API paths

```bash
TOKEN=$(python3 - <<'PY'
import json
from pathlib import Path

print(json.loads(Path('/etc/enoch-control-plane/config.json').read_text(encoding='utf-8'))['control_api_bearer_token'])
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

The normal broad dispatch path is intentionally guarded:

1. queue item exists;
2. control plane is not paused;
3. maintenance mode is not active;
4. worker preflight is healthy;
5. no conflicting active GPU lane exists;
6. dispatch script launches the agent run;
7. worker gate tracks process/telemetry truth;
8. completion callback or status update is emitted only after the gate is satisfied.

Use dry-run dispatch first:

```bash
curl -fsS -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"dry_run":true,"requested_by":"operator"}' \
  http://127.0.0.1:8787/control/dispatch-next | python3 -m json.tool
```

For controlled validation work, dispatch exactly one known queued project while the broad queue remains paused:

```bash
PROJECT_ID="the-queued-project-id"

# Non-mutating preflight of the explicit candidate. This works while the queue is paused.
curl -fsS -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"project_id\":\"$PROJECT_ID\",\"dry_run\":true,\"requested_by\":\"operator\"}" \
  http://127.0.0.1:8787/control/dispatch-one | python3 -m json.tool

# Live dispatch of only that project. This still requires maintenance mode off,
# a healthy worker preflight, and no active worker lane. It preserves queue_paused=true.
curl -fsS -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"project_id\":\"$PROJECT_ID\",\"dry_run\":false,\"requested_by\":\"operator\"}" \
  http://127.0.0.1:8787/control/dispatch-one | python3 -m json.tool
```

`/control/dispatch-one` must not be used as a batch drain. It rejects unknown projects, non-queued projects, blocked/manual-review rows, and any request made while another worker lane is active.

## 9. Paper artifact workflow

The control plane can rewrite and package generated research artifacts when paper rows and evidence are present.

Use the operator state model in [`docs/state-model.md`](state-model.md) when interpreting dashboard/API paper counts:

- `write_needed` means a completed run is paper-positive and has no live paper row.
- `finalize_needed` means a draft needs automated rewrite/finalization/package work.
- `publish_ready` means a `publication_draft` has required evidence paths plus a finalized automation package and finalization package path, and does **not** have a matching `corpus_imports` ledger row. Historical finalized drafts already imported are tracked as `published_imported`, not actionable publish work.
- After importing papers into the public corpus, sync the local Postgres/control-plane import ledger with `python3 scripts/sync_corpus_import_ledger.py --corpus ../enoch-ai-research-corpus --sql-output /tmp/enoch-sync-corpus-imports.sql`, then apply that SQL through the configured database connection. The older `supabase db query` path is a compatibility/migration workflow, not the current production database owner.

Do not treat raw `wake_ready`, `draft_review`, or `publication_draft` values by themselves as user-facing paper work or publication readiness.

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

## Codex-native worker skill

Worker installs should include the Enoch Codex skill so GB10-side Codex runs understand the artifact and decision contract without relying on legacy wrapper context:

```bash
scripts/install-codex-enoch-worker-skill.sh
```

The skill installs to `$CODEX_HOME/skills/enoch-worker/SKILL.md` and documents the required `run_notes.md`, preferred `.enoch/project_decision.json` path, legacy `.omx/project_decision.json` compatibility path, positive/negative paper gate, follow-up rules, and GB10 smoke-first expectations.
