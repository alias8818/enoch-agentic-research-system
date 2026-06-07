# Top 10 Recommendations

1. **Make trajectory/replay the main research object.**
   - Why: Enoch’s distinctive value is auditable local agent operation.
   - Evidence: repo docs emphasize queue safety, evidence, state model, operational traces.
   - Validate: replay 20 real trajectories from JSONL/ledger export.
   - Kill it if: replay cannot recover enough context to score outcomes.

2. **Adopt portable trace semantics, not a proprietary observability dependency.**
   - Why: Phoenix/OpenInference and OTel let Enoch remain local/self-hostable.
   - Evidence: Phoenix is OTel/OpenInference-native and supports tracing/evals/datasets.
   - Validate: export one research cycle as OTel-like spans.
   - Kill it if: mapping loses essential Enoch-specific state.

3. **Build a failure-derived eval set before adding more automation.**
   - Why: recent operational incidents are better eval seeds than synthetic happy paths.
   - Evidence: Enoch has real incidents around queue pauses, worker settling, callbacks, provider failures.
   - Validate: 25 cases with expected state/action labels.
   - Kill it if: failures are too heterogeneous to score deterministically.

4. **Treat source-enriched idea generation as the first sidecar trial.**
   - Why: low blast radius; outputs stay advisory until deterministic admission.
   - Evidence: existing `llm-agentic-harness-evaluation.md` already selects this as the safest PoC.
   - Validate: compare source usefulness and admitted yield vs native generation.
   - Kill it if: source enrichment increases cost/malformed output without improving admissions.

5. **Instrument token repetition before doing speculative decoding.**
   - Why: SuffixDecoding claims strongest speedups on repetitive agentic workloads.
   - Evidence: SuffixDecoding reports SWE-Bench/AgenticSQL gains but open chat is weaker.
   - Validate: entropy/repetition metrics over 100 Enoch outputs.
   - Kill it if: repetition is too low for suffix/prompt lookup speculation.

6. **Start memory with repo-local, inspectable, versionable artifacts.**
   - Why: Enoch is research-grade; memory must be auditable.
   - Evidence: ByteRover argues for file-based hierarchical context with provenance; Enoch already uses docs/ledgers.
   - Validate: Markdown+SQLite memory improves incident replay accuracy.
   - Kill it if: retrieval adds no benefit over existing docs/session search.

7. **Use temporal graph memory only for changing facts.**
   - Why: Zep/Graphiti’s strength is bitemporal change tracking; it is overkill for static notes.
   - Evidence: Zep paper focuses on dynamic facts and temporal reasoning.
   - Validate: model/provider/worker/issue-state temporal queries.
   - Kill it if: simple SQLite validity windows answer the queries.

8. **Prefer small ACI improvements over broad tool access.**
   - Why: SWE-agent’s ACI lesson is that narrow interfaces improve agent behavior.
   - Evidence: SWE-agent and OpenHands both emphasize tool/action design.
   - Validate: compare worker runs with raw shell vs constrained task tools.
   - Kill it if: constrained tools reduce success without improving safety.

9. **Score negative results as first-class research artifacts.**
   - Why: local hardware cannot validate everything; honest negative/scale-blocked results are publishable if structured.
   - Evidence: Enoch already has useful_signal and compute_scale_blocked lanes.
   - Validate: publish an internal negative-results report with reproducible artifacts.
   - Kill it if: artifacts are too shallow to support a defensible claim.

10. **Keep Enoch’s paper claims narrower than its automation capability.**
   - Why: automation can produce prose faster than evidence.
   - Evidence: state model correctly gates paper writing on exact positive decisions.
   - Validate: claim ledger rejects unsupported external claims.
   - Kill it if: generated papers repeatedly need manual de-hyping.
