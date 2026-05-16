# Bug-finding toolchain

This project uses layered checks because ordinary unit tests do not catch all
control-plane failure modes.

## Blocking checks

- `uv run ruff check .` is the fast correctness lint gate.
- `uv run pytest -q` is the blocking regression suite.
- `uv run coverage run -m pytest -q && uv run coverage report` enforces the
  configured coverage floor.

## Property-based checks

`tests/test_property_invariants.py` uses Hypothesis for invariants that should
hold across many weird inputs:

- artifact roots stay under the configured project root;
- process-tracker project directories stay bounded or resolve to no target;
- remote evidence paths do not preserve parent traversal.

These tests are intentionally small and should remain part of the normal pytest
suite.

## API contract smoke

`tests/test_schemathesis_api_contract.py` uses Schemathesis against a read-only
FastAPI route. This is the first stable API-contract smoke. Expand it gradually:
start with read-only endpoints, then add authenticated mutation endpoints only
when fixtures make the state effects explicit and reversible.

## Report-only checks

CI runs these as report-only signals so they can surface bugs without blocking
normal development during the initial rollout:

- `uv run pyright --level error`
- `uv run semgrep --config .semgrep/enoch-guardrails.yml --metrics=off --no-git-ignore .`

Pyright currently establishes the type-checking surface. Semgrep holds custom
project guardrails such as no `shell=True`, no hardcoded public counts, and no
silent broad exception swallowing.

## Agentic property-based testing

`scripts/agentic_property_testing.py` is a two-step harness inspired by agentic
property-based testing work:

1. Generate a prompt for a Python target:

   ```bash
   uv run python scripts/agentic_property_testing.py \
     --target enoch_control_plane/control_plane/router.py \
     --prompt-output artifacts/agentic-pbt/router-prompt.md
   ```

2. Give the prompt to an LLM and save its JSON proposal. Execute that proposal
   only when intentionally opted in:

   ```bash
   uv run python scripts/agentic_property_testing.py \
     --target enoch_control_plane/control_plane/router.py \
     --proposal-file artifacts/agentic-pbt/router-proposals.json \
     --execute-proposals
   ```

The execution step writes a markdown report under `artifacts/agentic-pbt/`. A
non-zero pytest run is treated as a candidate counterexample, not an automatic
confirmed bug; the report still needs human or follow-up agent validation.

Source inspiration: <https://arxiv.org/abs/2510.09907>.
