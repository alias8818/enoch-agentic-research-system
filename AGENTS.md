# AGENTS.md

Instructions for autonomous AI agents working on the Enoch Agentic Research System.

This sub-project inherits `/home/jeremy/Desktop/projects/enoch-release/AGENTS.md`.
For current issue status, priorities, blockers, mitigation tracking, release readiness,
paper production, worker health, or "what next" decisions, follow the parent Linear
source-of-truth and freshness-marker rule. The marker is:

`/home/jeremy/.codex/state/enoch-linear-last-check.json`

The marker only records when Linear was last checked. It is not a distilled issue
snapshot and must not be used as issue status. Query Linear when the marker is
missing, stale, or insufficient for the exact issue fields needed.

## Project Overview

Enoch Control Plane is a Python FastAPI/LangGraph control plane for auditable agentic research automation. It queues ideas, gates dispatch, supervises local AI runs, preserves evidence, and packages AI-generated research artifacts with provenance.

## Setup

```bash
# Clone and install (one command)
git clone https://github.com/alias8818/enoch-agentic-research-system.git && cd enoch-agentic-research-system && make dev
```

Or step-by-step:

```bash
uv venv --python /usr/bin/python3 .venv
uv pip install --python .venv/bin/python -e .
uv sync --all-extras --dev
```

## Configuration

```bash
mkdir -p .local/state .local/projects .local/config
cp config.example.json .local/config/config.json
# Edit .local/config/config.json with required values (bearer token, callback URL/token, worker URL/token)
```

Required config fields:
- `control_api_bearer_token` - API authentication token
- `completion_callback_url` / `completion_callback_token` - Worker callback endpoint
- `worker_wake_gate_url` / `worker_wake_gate_bearer_token` - Worker gate endpoint
- `project_root` - Local project directory
- `dispatch_script_path` - Path to dispatch script

Never commit live config files or credentials.

## Running

```bash
export ENOCH_CONFIG=$PWD/.local/config/config.json
uv run uvicorn enoch_control_plane.app:app --host 127.0.0.1 --port 8787
# Or: make run
```

Dashboard: `http://127.0.0.1:8787/control/dashboard-v2`

## Testing

```bash
make test              # Run all tests with coverage
make test-quick        # Run tests excluding repo_root marker
make lint              # Run ruff check + format check
make typecheck         # Run pyright type checking
```

Pytest configuration is in `pyproject.toml` under `[tool.pytest.ini_options]`. Tests use `test_*.py` naming convention. Coverage threshold is 75% (`fail_under = 75`).

Markers:
- `repo_root` - tests that touch the repository working tree (run separately)

## Build & Lint

```bash
make lint              # ruff check + ruff format --check
make format            # ruff check --fix + ruff format (auto-fix)
make typecheck         # pyright --level error
make pre-commit        # run all pre-commit hooks
```

## Project Structure

```
enoch_control_plane/          # Main Python package
  app.py                      # FastAPI application entry point
  config.py                   # GateConfig with all configuration fields
  gate.py                     # Wake gate / process tracking
  models.py                   # Pydantic models
  process_tracker.py          # Process tree tracking
  state_store.py              # SQLite state store
  telemetry.py                 # CPU/GPU/memory telemetry
  callback_outbox.py          # Callback delivery
  callbacks.py                # Callback sender
  timeutils.py                # UTC datetime utilities
  url_safety.py               # URL safety checks
  control_plane/
    router.py                 # Control plane API router (main)
    store.py                  # Control plane state store
    read_models.py            # Dashboard read models
    paper_writer.py           # Research artifact writer
    workload_routing.py       # Worker lane routing
    worker_adapter.py         # Worker preflight/dispatch
    supabase_store.py         # Postgres store adapter
    dashboard_v2/             # Built dashboard assets
  enoch_core/
    router.py                 # Enoch core API router
    logic.py                  # Core business logic
  observability/
    middleware.py             # Route observation JSONL middleware
  research_quality/           # Research quality evaluation
  source_lineage/             # Source lineage tracking
tests/                        # Test suite (90+ files)
scripts/                      # Operational and validation scripts
deploy/                       # Deployment scripts
supabase/migrations/          # Postgres migration files
dashboard/                    # React dashboard source (Vite + TypeScript)
docs/                         # Documentation
config.example.json           # Configuration template
```

## Conventions

- Python 3.11+ with `from __future__ import annotations`
- FastAPI with `Annotated` type hints for dependencies
- Pydantic v2 models for all API schemas
- JSONL structured logging via `enoch_control_plane/observability/middleware.py`
- UTC-only datetimes (`utc_now()` from models)
- Idempotent API design with `idempotency_key` fields
- All API endpoints require bearer token authorization
- ruff for linting (E9, F821, F822, F823) and formatting
- pyright for type checking (strict mode with warning-level opt-outs)
- Pre-commit hooks enforce: ruff, ruff-format, check-added-large-files, trailing-whitespace

## Dashboard V2 Product Discipline

Before changing Dashboard V2 UI, routes, tables, command results, detail pages,
dashboard copy, dashboard assets, or dashboard read-model rendering, use the
`enoch-dashboard-operator-design` skill.

Hard rules:

- Dashboard V2 is an operator command center, not a data explorer.
- Do not add a page, route, panel, table column, metric, badge, or visible JSON
  field unless it answers a concrete operator question.
- Prefer deletion, demotion, grouping, collapsed debug details, or existing-route
  reuse over adding another visible surface.
- Raw JSON must appear only inside collapsed `details.raw-details`.
- Red means operator risk, not normal active work.
- The command center should expose one primary next action above the fold.
- If semantics are wrong, fix the backend read model and add deterministic tests;
  do not patch truth with frontend copy.

## CI Workflows

- `.github/workflows/ci.yml` - Tests, lint, typecheck, semgrep, dashboard tests, E2E
- `.github/workflows/build.yml` - Coverage + SonarQube analysis
- `.github/workflows/pages.yml` - Static site deployment

## Key Dependencies

- `fastapi` - Web framework
- `langgraph` - Graph-based workflow
- `psycopg[binary]` - PostgreSQL driver
- `pydantic` - Data validation
- `uvicorn` - ASGI server
- `psutil` / `pynvml` - System telemetry

## Database

Postgres migrations in `supabase/migrations/`. Local dev can use docker-compose:
```bash
docker compose up -d    # Starts Postgres on localhost:5432
```
