# Frontier AI scout — Research Facility ingest report

Date: 2026-06-28
Operator: Hermes manual Research Facility intake
Linear parent: ALI-205
Related children: ALI-206, ALI-207, ALI-208

## Source artifacts

- Scout note: `artifacts/research-facility/frontier-ai-scout-exa-arxiv-2026-06-28.md`
- Candidate input: `artifacts/research-facility/frontier-ai-scout-exa-arxiv-2026-06-28.candidates.json`
- Deterministic plan: `artifacts/research-facility/frontier-ai-scout-exa-arxiv-2026-06-28.plan.json`

## Planning command

```bash
python3 scripts/research_facility.py \
  artifacts/research-facility/frontier-ai-scout-exa-arxiv-2026-06-28.candidates.json \
  --output artifacts/research-facility/frontier-ai-scout-exa-arxiv-2026-06-28.plan.json \
  --requested-by hermes.manual_research_facility_intake
```

## Planned admission result

- Candidate count: 5
- Admitted count: 5
- Needs-review count: 0
- Rejected count: 0

## Live verification

Applied to live Enoch Postgres on `enoch-core.exe.xyz` using the production-safe Research Facility intake pattern: source/candidate upserts, admission insert by idempotency key, lineage insert by `where not exists`; no control-plane idea/project/queue promotion.

Verified via `enoch.research_facility_workbench`:

| candidate_id | title | status | admission | total_score | queued? |
|---|---|---:|---:|---:|---:|
| `adg-answer-divergence-data-selection-20260628` | Answer-divergence instruction data selection benchmark | admitted | admitted | 78.50 | no |
| `early-reasoning-quality-token-loss-curation-20260628` | Early-token reasoning quality scorer for post-training data curation | admitted | admitted | 77.65 | no |
| `curatorkit-auditable-curation-ledger-20260628` | Auditable post-training curation ledger inspired by CuratorKIT | admitted | admitted | 73.55 | no |
| `viasd-slim-verifier-speculative-decoding-20260628` | VIA-SD slim-verifier tier for speculative decoding | admitted | admitted | 73.40 | no |
| `learning-to-draft-throughput-controller-20260628` | Learning-to-Draft throughput controller for speculative decoding | admitted | admitted | 73.15 | no |

Additional verification counts:

- `research_admissions` rows for the five candidates: 5
- `research_lineage` candidate-target rows for the five candidates: 19

## Scope boundary

This was Research Facility candidate/admission injection only. It intentionally did not create control-plane `ideas`, `projects`, or `queue_items` rows and did not dispatch work.
