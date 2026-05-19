# GB10 missing-source artifact review

Scope: the 70 `sources:required` rows from `dashboard-compute-scale-backfill-audit.json`.

This is a read-only filesystem review of GB10 project artifacts under `/home/jeremy/projects/enoch_testing_ground/projects`.

## Summary

| Check | Count |
|---|---:|
| Rows reviewed | 70 |
| Project directories present on GB10 | 70 |
| Project directories missing on GB10 | 0 |
| Rows with non-empty `Source/provenance URL` in prompts | 0 |
| Rows with any URL in reviewed files | 4 |
| Rows with parent/source project token in reviewed files | 0 |

Controller source kinds:

- `followup_branch`: 70

## Finding

All 70 project directories and final decision artifacts are present on GB10, but the worker-side files do **not** carry the missing original source records. Every reviewed project is a `followup_branch`; each prompt has an empty `Source/provenance URL:` line. The only non-empty source-like JSON key across the batch is `metadata.source = langgraph_control_plane`, which identifies the controller, not the research source.

Therefore the 70 rows should not be backfilled from GB10 files by inference. Source recovery needs a deterministic control-plane lineage lookup or an explicit parent/source mapping, not LLM interpretation of titles.

## URL hits found in reviewed files

| Project | URLs |
|---|---|
| `calibrated-evidence-ledger-jury-with-larger-real-data-cove-0937d49bc3` | `https://dl.fbaipublicfiles.com/glue/superglue/data/v2/BoolQ.zip`.` |
| `live-tool-trace-contradiction-recovery-without-last-mentio-f02b02654c` | `http://127.0.0.1:8081`, `http://127.0.0.1:8082` |
| `multi-model-hakv-inference-fidelity-robustness-at-25--rete-563c210425` | `https://arxiv.org/abs/2506.03762` |
| `real-small-lm-kv-trace-test-for-2-bit-residual-block-gates-f8490ab41d` | `https://raw.githubusercontent.com/karpathy/char-rnn/master/data/tinyshakespeare/input.txt`.`, `https://download.pytorch.org/whl/cpu` |

These URL hits are not enough to repair `sources:required` generically: two are dataset/package/local-service URLs, one is a dependency/download URL set, and one is an arXiv URL in a single project. Backfill should remain fail-closed unless a source record can be tied deterministically to the project lineage.

## Recommended next step

Add a control-plane lineage recovery query for `followup_branch` rows: parent project -> parent research lineage/source records -> child signal source record. Only backfill when exactly one deterministic parent/source mapping is found, or when a stored parent pointer makes multiple sources explicitly valid.
