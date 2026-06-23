.PHONY: dev test test-quick lint format typecheck pre-commit clean run smoke setup-config check-deps openapi dashboard-build dashboard-e2e docker-up docker-down release-patch release-minor release-major

# One-command setup: fresh clone to running dev server
dev: setup-config
	uv sync --all-extras --dev
	@echo "Setup complete. Run 'make run' to start the dev server."

# Create local config from template
setup-config:
	@if [ ! -f .local/config/config.json ]; then \
		mkdir -p .local/state .local/projects .local/config; \
		cp config.example.json .local/config/config.json; \
		python3 -c "import json, pathlib, secrets; \
			p=pathlib.Path('.local/config/config.json'); \
			data=json.loads(p.read_text()); \
			data['state_dir']=str(pathlib.Path('.local/state').resolve()); \
			data['project_root']=str(pathlib.Path('.local/projects').resolve()); \
			data['dispatch_script_path']=str(pathlib.Path('deploy/enoch_codex_dispatch.sh').resolve()); \
			data['control_api_bearer_token']=secrets.token_urlsafe(32); \
			data['completion_callback_token']=secrets.token_urlsafe(32); \
			data['completion_callback_url']='http://127.0.0.1:8787/control/api/worker-callback'; \
			data['worker_wake_gate_url']='http://127.0.0.1:8787'; \
			data['worker_wake_gate_bearer_token']=data['control_api_bearer_token']; \
			p.write_text(json.dumps(data, indent=2)+'\n'); \
			print('Config created. Token:', data['control_api_bearer_token']); \
		"; \
	else \
		echo "Config already exists at .local/config/config.json"; \
	fi

# Run the API server
run:
	@export ENOCH_CONFIG=$$PWD/.local/config/config.json && \
	uv run uvicorn enoch_control_plane.app:app --host 127.0.0.1 --port 8787

# Run all tests with coverage
test:
	uv run pytest -q -n auto -m "not repo_root" --cov=enoch_control_plane --cov-branch --durations=10
	uv run pytest -q -m "repo_root" --cov=enoch_control_plane --cov-branch --cov-append --durations=5

# Quick test without coverage
test-quick:
	uv run pytest -q -n auto -m "not repo_root" --durations=10
	uv run pytest -q -m "repo_root" --durations=5

# Lint check (no modifications)
lint:
	uv run ruff check .
	uv run ruff format --check .

# Auto-fix lint and format issues
format:
	uv run ruff check --fix .
	uv run ruff format .

# Type checking
typecheck:
	uv run pyright --level error

# Run pre-commit hooks on all files
pre-commit:
	uv run pre-commit run --all-files

# Clean build artifacts
clean:
	rm -rf .coverage coverage.xml htmlcov/ .pytest_cache/ .ruff_cache/ .hypothesis/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Smoke test against running server
smoke:
	@export ENOCH_CONFIG=$$PWD/.local/config/config.json && \
	scripts/smoke-test-local.sh

# Check for unused dependencies
check-deps:
	uv run deptry .

# OpenAPI schema generation
openapi:
	uv run python scripts/generate_openapi_schema.py

# Dashboard build
dashboard-build:
	cd dashboard && npm ci && npm run build

# Dashboard E2E tests
dashboard-e2e:
	cd dashboard && npx playwright install --with-deps chromium && npm run test:e2e

# Docker services (Postgres for local dev)
docker-up:
	docker compose up -d

docker-down:
	docker compose down

# Release version bump (usage: make release-patch|release-minor|release-major)
release-patch:
	@python3 scripts/bump_version.py patch

release-minor:
	@python3 scripts/bump_version.py minor

release-major:
	@python3 scripts/bump_version.py major
