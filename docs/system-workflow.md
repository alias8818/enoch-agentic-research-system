# Enoch agentic research workflow

Enoch is an agentic research-control system: it turns a research idea into an isolated project run, supervises the run on local AI hardware, captures evidence, and produces AI-generated research artifacts with claim/audit metadata.

## Core thesis

The system is valuable because it joins three layers that are often split apart:

1. **Operator reality** — GPU machines hang, processes detach, queues get stale, evidence is scattered, and completion signals lie.
2. **Control-plane reliability** — every transition needs idempotency, health checks, stale-state detection, queue safety, and operator-visible status.
3. **AI-native research output** — agents can run experiments, collect artifacts, and write reports, but the system must preserve provenance and uncertainty.

## Current architecture

```text
LLM research scout
        |
        v
Structured idea cards + Notion weight matrix
        |
        v
Idea intake / queue
        |
        v
VM control plane (FastAPI + LangGraph-era state model)
        |
        | dispatch / preflight / pause safety
        v
GB10 worker wake gate
        |
        | OMX/Codex agent execution + process/telemetry tracking
        v
Project workspace with run notes, metrics, results, claim ledgers
        |
        | evidence sync
        v
Publication artifact pipeline (GLM-5.1 writer + quality gates)
        |
        v
Dashboard, corpus export, and release artifacts
```


## Intake boundary

The upstream intake process used an LLM-assisted research scout to review news, public research papers, and systems trends, then frame candidate experiments for scoring. Notion acted as the weight-matrix and triage surface. That intake layer explains where ideas came from, but it is not the runtime authority.

Runtime authority begins when a scored candidate becomes a queue item for the Enoch control plane. From there, safety and truth come from control-plane state, worker preflight, wake-gate telemetry, process tracking, and evidence artifacts.

See `docs/idea-intake-workflow.md` for the full intake narrative.

## What is in scope

- queue and project state APIs;
- pause/maintenance controls;
- worker preflight and single-active-lane safety checks;
- wake-gate process tracking and CPU/GPU quiet-window evidence;
- control dashboard for operators;
- evidence synchronization from worker to VM;
- paper/research-artifact generation;
- quality scanning and corpus export;
- tests for routing, state, safety, telemetry, and paper artifact behavior.

## What is explicitly out of scope

- n8n workflow exports as part of the released system;
- workflow-tool configuration exports from earlier prototypes;
- claims of peer review or human authorship for generated papers;
- public release without secret scanning and quality gates.

Earlier workflow-tool references appear only in historical notes because they were part of the prototype lineage. They are not the workflow being released here.

## Why this matters

The project demonstrates the engineering discipline needed around autonomous AI systems:

- agents need external supervision;
- queues need reconciliation;
- GPU worker lanes need safety gates;
- evidence needs to survive context boundaries;
- generated claims need provenance;
- dashboards need to expose operational truth, not just optimistic state.

That is the sell: Enoch is not just prompt automation. It is reliability engineering around agentic AI work.
