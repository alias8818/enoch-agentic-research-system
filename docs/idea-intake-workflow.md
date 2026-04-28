# Idea intake workflow

The Enoch execution system did not start from hand-picked prompts alone. It used an upstream agentic intake process to discover, score, and organize candidate research ideas before the control plane dispatched experiments.

This document describes that intake layer because it is important to the full system story. It is also intentionally separated from the current runtime control plane: the released workflow does not depend on publishing old workflow-tool exports.

## Summary

```text
External signals
  -> LLM research scout
  -> candidate idea cards
  -> scoring / weight matrix
  -> Notion idea database
  -> queue selection / dispatch planning
  -> Enoch control plane
  -> GB10 worker experiment
  -> evidence + generated research artifact
```

## Stage 1 — External signal scouting

The upstream agentic scout reviewed technical signals such as:

- AI/ML news;
- arXiv-style research papers;
- systems/inference discussions;
- LLM tooling and serving trends;
- local hardware/runtime opportunities;
- gaps that looked testable on available infrastructure.

The scout's job was not to produce finished research. Its job was to propose candidate experiments that were:

- concrete enough to run;
- small enough for local hardware;
- relevant to AI systems, model serving, RAG, evaluation, routing, memory, or reliability;
- likely to produce a useful positive, negative, or mixed result.

## Stage 2 — Candidate idea framing

Candidate ideas were converted into structured idea records. A good idea record captured:

- working title;
- core hypothesis;
- expected mechanism;
- benchmark or evaluation sketch;
- required hardware/software;
- novelty estimate;
- implementation difficulty;
- expected evidence type;
- failure/kill criteria;
- why it might matter.

This made the idea pool machine-actionable instead of a pile of prose.

## Stage 3 — Weight matrix scoring

Ideas were scored with a weight matrix in Notion. The goal was to turn subjective research instinct into a repeatable prioritization signal.

Typical scoring dimensions included:

| Dimension | Purpose |
|---|---|
| Novelty | Is this meaningfully different from obvious baseline work? |
| Feasibility | Can it run on available hardware and time budget? |
| Evidence potential | Can the experiment produce measurable support/refutation? |
| Systems relevance | Does it touch serving, reliability, memory, routing, evaluation, or agent infrastructure? |
| Implementation complexity | Is the build small enough to complete autonomously? |
| Risk / uncertainty | Is the outcome uncertain enough to be worth testing? |
| Reuse value | Will artifacts, harnesses, or results help future work? |
| Publication/artifact potential | Could the result become a useful technical report? |

The point was not to pretend the scores were objectively true. The point was to make priority explicit, auditable, and adjustable.

## Stage 4 — Notion as intake database

Notion acted as the intake and triage database for ideas.

It provided:

- human-readable idea cards;
- weighted prioritization fields;
- status tracking;
- links back to source inspiration;
- queue handoff metadata;
- a place to review or adjust candidates before execution.

Important distinction:

> Notion was the intake/reference surface. It was not the core execution engine.

The current release positions Notion as an upstream planning and metadata layer. The durable execution story lives in the Enoch control plane and wake-gate system.

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
Notion/intake decides what may be worth running.
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

> Enoch used an upstream LLM-assisted research-scouting process to review technical signals, propose candidate experiments, and score them in a Notion weight matrix. Notion acted as the intake and prioritization surface. The execution authority lived in the Enoch control plane, which handled dispatch safety, worker preflight, process/telemetry gating, evidence synchronization, and artifact generation.

## What should not be overclaimed

- The intake scout did not guarantee novelty.
- The weight matrix was a prioritization tool, not a proof of value.
- Notion was not the execution engine.
- The generated papers remain AI-generated artifacts, not peer-reviewed human scholarship.

## Future improvements

A cleaner future implementation would replace ad hoc intake with first-class graph nodes:

```text
ScoutSignals -> GenerateIdea -> ScoreIdea -> Deduplicate -> Human/Operator Triage -> QueueCandidate -> DispatchGraph
```

This would make the intake process reproducible, testable, and versioned alongside the control plane.
