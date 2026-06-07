# Enoch Holistic Research Review

## Executive summary

Enoch's strongest technical direction is **evidence-backed paper production**, not paper volume alone. Its defensible angle is a local, auditable, bounded research-control system that joins: (1) operator reality around flaky local workers and queues, (2) deterministic control-plane reliability, and (3) visible AI research artifacts with preserved evidence.

Repo evidence supports that this is already the project’s actual center of gravity:

- `AGENTS.md` describes Enoch as a FastAPI/LangGraph control plane for auditable agentic research automation that queues ideas, gates dispatch, supervises local AI runs, preserves evidence, and packages research artifacts with provenance.
- `docs/system-workflow.md` frames the value as joining operator reality, control-plane reliability, and AI-native research output.
- `docs/research-facility.md` already separates source ledgers, candidate ledgers, admission ledgers, and lineage ledgers, with bounded provider and dispatch policy.
- `docs/state-model.md` defines a deliberately small operator-state vocabulary, resisting raw-state sprawl.
- `tests/test_operational_trace.py` verifies bounded/redacted JSONL trace records and operator-relevant lane snapshots.

The main risk is dilution: Enoch can drift into a broad “agent dashboard + generated paper factory” instead of a research system with sharp claims. The research radar should push Enoch toward measurable claims about local-agent reliability, trace/replay, eval-driven development, queue safety, and agentic workload inference — and away from vague multi-agent role play, unvalidated paper claims, or heavyweight memory/inference systems without small local falsification tests.

## Strongest current direction

**Research-grade local agent control and evidence replay.** Enoch can credibly become a benchmarkable platform for studying how autonomous coding/research agents behave on constrained local hardware, with control-plane safety and trace/provenance first. That is more distinctive than competing with OpenHands, SWE-agent, Claude Code, or Devin as a general coding agent.

External comparison supports this positioning:

- SWE-agent emphasizes a carefully designed Agent-Computer Interface and research-hackable configuration rather than platform breadth: <https://github.com/swe-agent/swe-agent>.
- OpenHands is a broad generalist software-agent platform with sandboxing, browser, evaluation, and multi-agent support; copying that breadth would make Enoch less distinct: <https://arxiv.org/pdf/2407.16741>.
- SWE-smith points toward turning repositories into SWE-agent training/evaluation gyms, which suggests Enoch should treat traces and local project runs as dataset assets, not just operational logs: <https://github.com/SWE-bench/swe-smith>.

## Weakest assumptions

1. **Generated paper count is not the right north-star metric.** Paper-worthy output requires comparison, ablation, negative results, and reproducibility. The current paper gate is necessary but not sufficient.
2. **Worker completion is not scientific validity.** `current-runtime-snapshot.md` says the worker gate proves operational completion, not correctness or novelty. This should be elevated into research scoring.
3. **Trace exists, but replay schema is under-specified for publishable agent behavior studies.** Enoch has operational traces, source lineage, and research ledgers, but needs a unified trajectory schema linking prompt/model/tool/state/action/evidence/outcome/cost.
4. **Agent sidecars are tempting but risky.** `docs/llm-agentic-harness-evaluation.md` correctly says tool output should be advisory and workflow-scoped; this should become a research/eval surface, not a fast path to production mutation.
5. **Memory is not yet a research object.** Enoch needs inspectable, versionable memory for research context and agent learning, but not a black-box memory SaaS bolted in before defining what must be remembered.

## Highest-value features to add

1. **OpenTelemetry/OpenInference-compatible trace envelope for every research cycle.** Keep Enoch’s local ledgers authoritative, but map spans to standard fields so Phoenix/LangSmith/Weave/Braintrust-style analysis is possible. Phoenix is OTel/OpenInference-native and self-hostable: <https://github.com/Arize-ai/phoenix>.
2. **Replay/eval harness for Enoch trajectories.** A trajectory should be replayable against a fixed model/provider/tool stub or scored against deterministic validators.
3. **Failure-derived eval set.** Promote bad or interesting traces into versioned eval cases. This matches the broader eval-driven development pattern and Braintrust/LangSmith/Phoenix workflows.
4. **Research candidate “falsification contract” scoring.** Enoch already has candidate fields like hypothesis, baseline, success threshold, kill condition; make kill-condition quality a first-class score.
5. **Local agentic workload suffix/repetition measurement.** SuffixDecoding reports large speedups on repetitive agentic workloads and SWE-Bench: <https://suffix-decoding.github.io/>. Enoch can instrument its own agent outputs to test whether local tasks have enough repetition to justify suffix-cache speculation.
6. **Trace-derived memory with provenance and expiry.** ByteRover’s file-based agent-curated context tree and Zep/Graphiti’s temporal knowledge graph both point to versionable memory with explicit provenance, but Enoch should start with Markdown+SQLite+FTS/vector metadata before graph complexity.

## Features to remove or defer

1. **Generic multi-agent role crews.** CrewAI/MetaGPT-style roles are easy to demo but hard to validate. Defer until there is an eval showing role decomposition improves Enoch outcomes.
2. **Broad paper automation for weak/no-paper rows.** The state model already rejects this. Keep it strict.
3. **Memory platform integration without a memory benchmark.** First define Enoch memory tasks and stale-fact tests.
4. **Speculative decoding implementation inside the control plane.** Start with instrumentation and offline benchmarks; implementation belongs in worker/inference layer only if measurements justify it.
5. **General OpenHands clone features.** Browser UI, multi-agent collaboration, and sandbox breadth are already solved elsewhere; Enoch should interoperate/benchmark rather than copy.

## Best external projects to study

- SWE-agent / Mini-SWE-agent: minimal ACI and research-hackable benchmark discipline.
- OpenHands: event-stream software-agent platform, sandbox, evaluation breadth.
- SWE-smith: generating SWE tasks and trajectories from repositories.
- Phoenix / OpenInference: OTel-native traces, datasets, experiments.
- LangSmith: agent trajectory monitoring, online/offline eval workflow, LangGraph Studio ideas.
- Braintrust / Weave: eval-first regression and experiment comparison patterns.
- ByteRover: local file-based hierarchical context tree with provenance and lifecycle.
- Zep / Graphiti: temporally-aware knowledge graph for changing facts.
- SuffixDecoding / SAM Decoding / AdaSpec / AdaEDL / SpecDec++ / BanditSpec: adaptive speculation and agentic workload repetition.

## Recommended 30/60/90 day research plan

### 30 days

- Freeze the Research Radar schema and cards.
- Add/validate a unified trajectory schema draft mapped from current Enoch ledgers.
- Build a small failure-derived eval set from recent real incidents: queue pause/resume, worker settling, callback delivery, provider malformed output, paper gate false-positive risk.
- Measure token repetition/entropy in recent Enoch worker prompts and outputs to decide whether suffix-cache speculation is plausible.

### 60 days

- Implement a read-only trace export to JSONL/Parquet with OTel/OpenInference-compatible span names.
- Run baseline evals: no-memory vs trace-derived memory; native provider generation vs sidecar source-enriched generation; static vs adaptive candidate admission thresholds.
- Produce a small “negative results” report: ideas that fail on local GB10/CPU and why.

### 90 days

- Publish an internal benchmark report or workshop-style artifact on local-agent reliability traces.
- If repetition metrics justify it, prototype suffix/retrieval speculative decoding outside the control plane.
- If memory evals justify it, implement repo-local trace-derived memory with explicit provenance and invalidation.
