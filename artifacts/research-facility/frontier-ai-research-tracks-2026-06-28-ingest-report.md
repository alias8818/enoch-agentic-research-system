# Frontier AI research tracks — Research Facility ingest report

Date: 2026-06-28
Operator: Hermes manual Research Facility intake
Linear parent: ALI-205
Linear children: ALI-206, ALI-207, ALI-208

## Source artifacts

- Candidate input: `artifacts/research-facility/frontier-ai-research-tracks-2026-06-28.candidates.json`
- Deterministic plan: `artifacts/research-facility/frontier-ai-research-tracks-2026-06-28.plan.json`
- Planning command:

```bash
python3 scripts/research_facility.py \
  artifacts/research-facility/frontier-ai-research-tracks-2026-06-28.candidates.json \
  --output artifacts/research-facility/frontier-ai-research-tracks-2026-06-28.plan.json \
  --emit-sql /tmp/frontier-ai-research-tracks-2026-06-28.ledger.sql \
  --requested-by hermes.manual_research_facility_intake
```

The generated SQL plan was not retained as the applied artifact because the live `enoch.research_lineage` table lacks a unique constraint matching the repository planner's `ON CONFLICT (source_type, source_id, target_type, target_id, relation_type)` clause. The live mutation was instead applied with a narrow idempotent helper using `where not exists` for lineage inserts and no idea/project/queue promotion.

## Planned admission result

- Candidate count: 3
- Admitted count: 3
- Needs-review count: 0
- Rejected count: 0

## Live verification

Verified on `enoch-core.exe.xyz` against `enoch.research_facility_workbench`:

| candidate_id | status | admission | total_score | queued? |
|---|---:|---:|---:|---:|
| `frontier-dspark-deepspec-gb10-scheduler-20260628` | admitted | admitted | 75.55 | no |
| `frontier-post-training-quality-adjusted-efficiency-20260628` | admitted | admitted | 73.15 | no |
| `frontier-dataset-quality-generalized-understanding-benchmark-20260628` | admitted | admitted | 77.65 | no |

Additional verification counts:

- `research_admissions` rows for the three candidates: 3
- `research_lineage` candidate-target rows for the three candidates: 8

## Scope boundary

This was Research Facility intake/admission only. It intentionally did not create control-plane `ideas`, `projects`, or `queue_items` rows and did not dispatch work. A later explicit promotion step should choose which admitted candidate becomes runtime work.
