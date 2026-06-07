# Prioritized Idea Backlog

Runtime context: see [current-runtime-snapshot.md](../current-runtime-snapshot.md) for current GB10/control-plane topology referenced by this backlog.


## Immediate instrumentation

1. Unified trajectory schema for research cycles: trace_id, run_cycle_id, source/admission lineage, model/provider, prompt hash, tool calls, worker lane, action, artifact paths, decision, paper gate, cost, latency, failure_kind.
2. OTel/OpenInference-compatible export adapter for Enoch operational traces.
3. Failure-derived eval set from real incidents: queue pause/resume, worker settling, stale active lane, provider malformed JSON, paper gate ambiguity.
4. Token repetition/entropy profiler for worker prompts, outputs, paper drafts, and callback traces.

## Benchmark improvements

1. Enoch ReplayBench: replay past trajectories with fixed tool stubs and judge deterministic state transitions.
2. Queue SafetyBench: seeded queue/lane states measuring false alert, missed alert, and auto-reconciliation correctness.
3. Paper GateBench: project_decision artifacts with hidden expected gate labels.
4. Tool ReliabilityBench: sidecar source enrichment tasks scored by source usefulness and malformed output rate.

## Architecture changes

1. Treat traces as first-class research data assets, not just logs.
2. Add explicit research-memory namespace: repo-local, project-global, trace-derived, and user/workstyle separated.
3. Keep sidecar agents read-only and advisory until evals prove benefit.
4. Separate “research candidate generation” from “dispatch” even more strongly in UI and API language.

## Speculative decoding experiments

1. Measure suffix repetition in Enoch agent workloads. **Immediate.**
2. Offline prompt-lookup/suffix-cache simulation over existing Enoch outputs. **Medium.**
3. Entropy-based adaptive draft length microbenchmark on GB10. **Medium.**
4. Bandit selection among draft strategies for agentic workloads. **High risk.**

## Memory/context experiments

1. Markdown+SQLite trace-derived memory with provenance and TTL. **Immediate.**
2. Benchmark repo-local memory vs no-memory on Enoch incident replay. **Medium.**
3. Temporal graph memory only for facts that change over time: provider health, model routes, worker status, issue states. **Medium/high.**
4. Agent-curated memory with mandatory human-readable diffs. **Medium.**

## Agent reliability experiments

1. Compare native generation vs web/source-enriched sidecar on admitted-candidate yield.
2. Compare minimal ACI vs raw shell/filesystem access for local worker tasks.
3. Evaluate whether “first useful report before mutation” reduces incident MTTR.
4. Test queue/worker quiet-window thresholds against false positives and missed hangs.

## Long-shot ideas

1. Enoch as a generator of local-agent reliability benchmark tasks.
2. Trace-to-training-data pipeline for small coding/research agents.
3. Agentic workload suffix decoding paper using Enoch traces.
4. Temporal evidence graph for generated research claims.

## Kill/defer candidates

1. Generic role-based multi-agent crews without an eval.
2. Paper drafting from weak/non-positive rows.
3. Production speculative decoding before offline repetition/acceptance data.
4. Black-box memory SaaS before memory benchmark.
5. Broad OpenHands/Devin clone features.
