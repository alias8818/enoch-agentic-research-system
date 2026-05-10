# Idea intake workflow

The Enoch execution system should not depend on hand-picked prompts or ad-hoc ChatGPT batches alone. The Research Facility is the first-class intake lane for discovering, scoring, admitting, and tracing candidate research ideas before the control plane dispatches experiments.

This document describes that intake layer because it is important to the full system story. It is intentionally separated from runtime dispatch: generated candidates do not become work until an admission decision promotes them into the control-plane idea/project/queue ledgers.
For current runtime topology, storage authority, and bounded Research Facility
automation, see [`current-runtime-snapshot.md`](current-runtime-snapshot.md).

## Summary

```text
External signals + prior Enoch results
  -> Research Facility source ledger
  -> generated candidate ledger
  -> dedupe / history comparison
  -> scoring / admission ledger
  -> local Postgres/control-plane ideas workbench
  -> queue selection / dispatch planning
  -> Enoch control plane
  -> GB10 worker experiment
  -> evidence + generated research artifact
```

## Stage 1 — Research Facility source scouting

The Research Facility source ledger records technical signals such as:

- AI/ML news;
- public research papers;
- systems/inference discussions;
- LLM tooling and serving trends;
- local hardware/runtime opportunities;
- gaps that looked testable on available infrastructure.

The source scanner's job is not to produce finished research. Its job is to provide grounded inputs for candidate experiments that are:

- concrete enough to run;
- small enough for local hardware;
- relevant to AI systems, model serving, RAG, evaluation, routing, memory, or reliability;
- likely to produce a useful positive, negative, or mixed result.

## Stage 2 — Candidate generation

Candidate ideas are converted into structured research proposals in `enoch.research_candidates`. A good candidate record captures:

- working title;
- core hypothesis;
- expected mechanism;
- baseline to beat;
- success threshold;
- benchmark or evaluation sketch;
- required hardware/software;
- novelty estimate;
- implementation difficulty;
- expected artifacts;
- required evidence;
- failure/kill criteria;
- why it might matter.

This keeps the idea pool machine-actionable instead of a pile of prose.

## Stage 3 — Dedupe and scoring

Candidates are scored before admission. The goal is to turn subjective research instinct into a repeatable prioritization signal while preventing idea spam, shallow incremental sludge, and re-runs of known negatives.

Typical scoring dimensions included:

| Dimension | Purpose |
|---|---|
| Novelty | Is this meaningfully different from obvious baseline work? |
| Feasibility | Can it run on available hardware and time budget? |
| Falsifiability | Does the proposal have a crisp success threshold and kill condition? |
| Evidence potential | Can the experiment produce measurable support/refutation? |
| Systems relevance | Does it touch serving, reliability, memory, routing, evaluation, or agent infrastructure? |
| Implementation complexity | Is the build small enough to complete autonomously? |
| Risk / uncertainty | Is the outcome uncertain enough to be worth testing? |
| Accessibility impact | Does this materially help local/home AI viability rather than chase a tiny benchmark tweak? |
| Reuse value | Will artifacts, harnesses, or results help future work? |
| Publication/artifact potential | Could the result become a useful technical report? |

The point is not to pretend the scores are objectively true. The point is to make priority explicit, auditable, and adjustable.

## Stage 4 — Admission and control-plane idea workbench

The current production runtime stores intake and triage data in local Postgres behind the Enoch control plane. Historical Notion identifiers may remain on imported rows as provenance, but they are no longer runtime authority.

Admission is recorded in `enoch.research_admissions`. This is the operator-facing answer to “why did this get queued?” A candidate may be admitted, rejected, merged, or held for review.

The workbench provides:

- human-readable idea cards;
- weighted prioritization fields;
- admission reasons;
- lineage back to sources and prior Enoch evidence;
- status tracking;
- links back to source inspiration;
- queue handoff metadata;
- a place to review or adjust candidates before execution.

Important distinction:

> Control-plane ideas are the editable intake ledger. The Enoch control plane remains the execution authority.

The current runtime does not require Notion sync to create, inspect, or dispatch idea candidates. See [`research-facility.md`](research-facility.md) for the concrete ledgers and admission planner.

## Stage 5 — Queue handoff

Once an idea was selected, it became a queue/project candidate for the control plane.

The handoff needed enough structure to let the system create a run workspace:

- project ID;
- project name;
- hypothesis/prompt;
- relevant constraints;
- target machine or workload class;
- expected output artifact;
- status and priority metadata.

This is where the system moved from idea management into operational execution.

## Stage 6 — Control-plane execution

After intake, Enoch handled execution concerns:

- pause/maintenance controls;
- dispatch safety;
- worker preflight;
- single-active-lane protection;
- process-tree tracking;
- CPU/GPU quiet-window checks;
- stale queue reconciliation;
- run notes and metrics capture;
- evidence synchronization;
- paper/corpus artifact generation.

The key architectural boundary is:

```text
Research Facility admissions decide what may be worth running.
Control-plane ideas/projects/queue rows represent admitted runtime work.
Enoch control plane decides what is safe and true during execution.
```

## Why this matters

This intake workflow makes the project more than a script runner. It shows a complete loop:

1. observe the field;
2. generate candidate ideas;
3. score them against explicit criteria;
4. queue the best candidates;
5. run experiments under a reliability control plane;
6. preserve evidence;
7. generate auditable research artifacts.

That loop is the agentic system story.

## Public framing

Recommended wording:

> Enoch uses an upstream LLM-assisted research-scouting process to review technical signals, propose candidate experiments, and store candidate records in a local Postgres/control-plane ideas workbench. Execution authority lives in the Enoch control plane, which handles dispatch safety, worker preflight, process/telemetry gating, evidence synchronization, and artifact generation.

## What should not be overclaimed

- The intake scout did not guarantee novelty.
- The weight matrix was a prioritization tool, not a proof of value.
- Control-plane ideas are not the execution engine; they are the intake ledger.
- The generated papers remain AI-generated artifacts, not peer-reviewed human scholarship.

## Future improvements

A cleaner future implementation would make scouting and scoring first-class graph nodes:

```text
ScanSources -> GenerateCandidate -> Deduplicate -> ScoreCandidate -> AdmitOrReject -> QueueCandidate -> DispatchGraph
```

The current implementation starts this path with `enoch.research_sources`, `enoch.research_candidates`, `enoch.research_admissions`, `enoch.research_lineage`, and the deterministic planner in `scripts/research_facility.py`.
