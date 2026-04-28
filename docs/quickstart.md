# Quickstart

This quickstart gets a developer clone to a running local API and dashboard. It does not require a real worker machine.

## 1. Install dependencies and run tests

```bash
git clone https://github.com/alias8818/enoch-agentic-research-system.git
cd enoch-agentic-research-system
uv venv --python /usr/bin/python3 .venv
uv pip install --python .venv/bin/python -e .
uv run pytest -q
```

## 2. Create a local config

```bash
mkdir -p .local/state .local/projects .local/config
cp config.example.json .local/config/config.json
python3 - <<'PY'
import json, pathlib, secrets
p=pathlib.Path('.local/config/config.json')
data=json.loads(p.read_text())
data['state_dir']=str(pathlib.Path('.local/state').resolve())
data['project_root']=str(pathlib.Path('.local/projects').resolve())
data['dispatch_script_path']=str(pathlib.Path('deploy/enoch_omx_dispatch.sh').resolve())
data['omx_inbound_bearer_token']=secrets.token_urlsafe(32)
data['completion_callback_token']=secrets.token_urlsafe(32)
data['completion_callback_url']='http://127.0.0.1:8787/omx/event'
data['worker_wake_gate_url']='http://127.0.0.1:8787'
data['worker_wake_gate_bearer_token']=data['omx_inbound_bearer_token']
p.write_text(json.dumps(data, indent=2)+"\n")
print('token:', data['omx_inbound_bearer_token'])
PY
```

## 3. Run the API

```bash
export OMX_WAKE_GATE_CONFIG=$PWD/.local/config/config.json
uv run uvicorn omx_wake_gate.app:app --host 127.0.0.1 --port 8787
```

Open:

```text
http://127.0.0.1:8787/dashboard
```

Paste the generated token when prompted.

## 4. Run smoke tests

In another shell:

```bash
export OMX_WAKE_GATE_CONFIG=$PWD/.local/config/config.json
scripts/smoke-test-local.sh
```

Expected result: health, status, preflight, and dispatch dry-run endpoints respond with JSON.

## 5. Move to two-machine testing

After local smoke tests pass, follow `docs/deployment-guide.md` to configure a control VM and a worker machine.
