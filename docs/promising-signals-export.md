# Promising signals export

The promising-signals export preserves bounded Enoch research leads that are useful to keep but are **not** paper-positive and are **not** part of the public paper corpus.

For the current runtime topology and control-plane source of truth, see [`current-runtime-snapshot.md`](current-runtime-snapshot.md).

## Purpose

Some Enoch runs produce a small local signal, a plausible scale-up target, or a follow-up that is compute-scale blocked. Those records are valuable for future researchers, but treating them as papers would overclaim the evidence. The companion public repository [`alias8818/enoch-promising-signals`](https://github.com/alias8818/enoch-promising-signals) keeps those leads separate from the publication corpus.

## Export invariant

Never let an LLM interpretation become export truth. A row exports only when deterministic control-plane fields indicate one of these statuses:

- `useful_signal`
- `promising_if_scaled`
- `compute_scale_blocked`

The exporter excludes paper-positive rows, rows with live paper records, corpus-imported rows, hard negatives, and rows missing required claim/evidence boundaries. Missing source lineage may be repaired only by deterministic backfill from existing source metadata or by an explicit `internal_generated:<project_id>` source derived from queue/project metadata; the backfill must not invent external URLs, measurements, claims, or evidence.

## Generated surfaces

`scripts/export_promising_signals.py` writes:

- `data/signals.jsonl` — machine-readable source of truth.
- `signals/<project-id>.md` — one human-readable signal page per exported row.
- `signals/index.md` — generated table of exported signals.
- `schemas/promising-signal.schema.json` — JSON schema for the record contract.

Each exported record carries do-not-overclaim flags and a required disclaimer stating that the record is not a validated paper, not peer reviewed, and not a publication-positive corpus artifact.

## Backfill audit

Use the janitor before publishing when the audit bucket reports missing fields:

```bash
python3 scripts/backfill_promising_signals.py \
  --report-json artifacts/promising-signals-backfill-report.json \
  --report-markdown artifacts/promising-signals-backfill-report.md \
  --backfilled-rows-json /tmp/promising-signals-backfilled-rows.json
```

The report records repaired and parked rows with machine-readable reasons such as `missing_research_source_lineage`, `missing_source_url_or_title`, `missing_decision_field`, `missing_evidence_claim_boundary`, `stale_duplicate_superseded`, and `unrecoverable_project_identity`.

## Example

```bash
python3 scripts/export_promising_signals.py \
  --output-repo ../enoch-promising-signals \
  --project-id token-superposition-for-long-context-anchor-compression-2e427b5fb840
```

The command fails closed if validation finds missing fields, paper/corpus leakage, unredacted control-plane paths, or missing disclaimer language.
