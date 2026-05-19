# ChatGPT Pro speculative decoding ideas ingest — 2026-05-19

Source: `../new-chatgpt-pro-ideas-05-19.md`

## Ingest result

Converted the ChatGPT Pro speculative-decoding research map into 15 explicit Research Facility candidates.

Admission planner result:

- 15 candidates planned
- 5 admitted
- 10 needs_review
- 0 rejected

The 5 admitted candidates were promoted into queued idea/project rows. Promotion does not dispatch work by itself.

## Queued admitted candidates

1. Dynamic Speculative Vocabulary for DFlash and EAGLE Heads
2. Grammar and Schema-Aware Speculative Decoding
3. Unified Entropy and Acceptance Controller for Speculative Decoding
4. SSD-lite Verification-Outcome Prediction for DFlash
5. Retrieval Suffix-Cache Speculation for Agentic Enoch Workloads

## Needs-review candidates preserved in Research Facility ledgers

- Negative Rejection Cache for Agentic Speculation
- Token-Class Micro-Drafters for Structured Tokens
- Batch-Aware Speculation Budget Allocator
- Early-Exit Self-Drafter with Calibrated Logit Lens
- Budgeted Multi-Proposer Router for Speculative Decoding
- Bonus-Token Branch Predictor for Low-Acceptance Rounds
- Copy-on-Write KV Layout for Speculative Tree Verification
- Budgeted Adaptive Prefix Tree Speculation for DFlash
- Traversal Rejection-Rescue Verification for Speculative Trees
- Domain-Specialized Bounded Draft Adapter for Enoch Traces

## Local artifacts

- `artifacts/research-facility/new-chatgpt-pro-ideas-05-19.candidates.json`
- `artifacts/research-facility/new-chatgpt-pro-ideas-05-19.plan.json`
- `artifacts/research-facility/new-chatgpt-pro-ideas-05-19.ledger.sql`

## Verification evidence

- `python3 -m json.tool artifacts/research-facility/new-chatgpt-pro-ideas-05-19.candidates.json`
- `uv run python scripts/research_facility.py artifacts/research-facility/new-chatgpt-pro-ideas-05-19.candidates.json --output artifacts/research-facility/new-chatgpt-pro-ideas-05-19.plan.json --emit-sql artifacts/research-facility/new-chatgpt-pro-ideas-05-19.ledger.sql --requested-by codex-manual-ingest --default-machine gb10 --default-model gpt-5.5 --default-sandbox danger-full-access`
- Applied SQL on enoch-core via `psql` with `ON_ERROR_STOP=1`.
- Production DB verification: 15 rows with prompt_version `manual_spec_decoding_research_map_2026-05-19`: 5 admitted and 10 needs_review.
- Control-plane verification: `/control/state` reports 5 queued, 0 active, readiness READY, and the 5 admitted speculative-decoding projects are present in the queued page.
