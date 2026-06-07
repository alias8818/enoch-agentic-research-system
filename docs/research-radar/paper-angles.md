# Top Paper-Worthy Experiment Candidates

Runtime context: see [current-runtime-snapshot.md](../current-runtime-snapshot.md) for current GB10 and worker-gate topology referenced by these paper angles.


1. **ReplayBench for local autonomous research agents**
   - Claim: a bounded trace/replay schema can predict and reduce failure modes in local agentic systems.
   - Artifacts: trace schema, replay harness, failure-derived eval set, before/after metrics.
   - Paper type: empirical agent evaluation / systems workshop.
   - GB10 feasibility: high.

2. **Agentic workload suffix speculation on Enoch traces**
   - Claim: repetitive local agent workflows have enough suffix/token reuse for retrieval-based speculation to beat vanilla decoding without changing output distribution.
   - Artifacts: repetition profiler, offline simulator, small vLLM/proxy benchmark if justified.
   - Paper type: speculative decoding/inference paper.
   - GB10 feasibility: medium.

3. **Eval-driven research candidate admission**
   - Claim: explicit hypothesis/baseline/success/kill-condition scoring improves admitted candidate quality and reduces no-paper churn.
   - Artifacts: candidate dataset, scoring rubric, ablation of admission fields.
   - Paper type: systems/empirical agent evaluation.
   - GB10 feasibility: high.

4. **Trace-derived memory for long-running research agents**
   - Claim: inspectable trace-derived memory improves incident replay and follow-up selection versus no-memory/vector-only baselines.
   - Artifacts: repo-local memory store, benchmark tasks, retrieval ablations.
   - Paper type: memory/context management paper.
   - GB10 feasibility: high.

5. **Queue safety and worker settling benchmark for autonomous local agents**
   - Claim: deterministic queue/worker invariants reduce false pages and missed hangs in long-running local agent systems.
   - Artifacts: seeded queue states, worker-gate simulations, false positive/missed alert metrics.
   - Paper type: systems reliability paper.
   - GB10 feasibility: high.
