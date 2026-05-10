# Enoch agentic research workflow

Enoch is an agentic research-control system: it turns a research idea into an isolated project run, supervises the run on local AI hardware, captures evidence, and produces AI-generated research artifacts with claim/audit metadata.

## Core thesis

The system is valuable because it joins three layers that are often split apart:

1. **Operator reality** — GPU machines hang, processes detach, queues get stale, evidence is scattered, and completion signals lie.
2. **Control-plane reliability** — every transition needs idempotency, health checks, stale-state detection, queue safety, and operator-visible status.
3. **AI-native research output** — agents can run experiments, collect artifacts, and write reports, but the system must preserve provenance and uncertainty.

## Current architecture

For the canonical current runtime facts behind this diagram, see
[`current-runtime-snapshot.md`](current-runtime-snapshot.md).

```text
LLM research scout
        |
        v
Structured idea cards + local Postgres/control-plane ideas workbench
        |
        v
Idea intake / queue
        |
        v
enoch-core control plane (FastAPI + LangGraph-era state/graph model)
        |
        | dispatch / preflight / pause safety
        v
GB10 worker gate
        |
        | Codex agent execution + process/telemetry tracking
        v
Project workspace with run notes, metrics, results, `.enoch/project_decision.json`
        |
        | evidence sync
        v
Publication artifact pipeline (GLM-5.1 writer + packaging/provenance lint checks)
        |
        v
Dashboard, corpus export, and release artifacts
```


## Tooling boundary

Enoch Control Plane is built around a FastAPI service, a LangGraph-era control-plane state/graph model, and Codex execution hooks. [Codex CLI](https://github.com/Yeachan-Heo/Codex CLI) is credited as part of the Codex-native execution layer used to operate local agents. Enoch Control Plane owns queue safety, worker completion evidence, artifact packaging, and release framing; legacy orchestration wrappers do not own or author the generated papers.


## Intake boundary

The upstream intake process uses an LLM-assisted research scout to review news, public research papers, and systems trends, then frame candidate experiments for scoring. The current production runtime stores the editable ideas workbench and triage ledgers in local Postgres behind the Enoch control plane on `enoch-core`. Historical Notion identifiers may remain as provenance on imported rows, but Notion is not the active runtime authority.

Runtime authority begins when a scored candidate becomes a queue item for the Enoch control plane. From there, safety and truth come from control-plane state, worker preflight, worker-gate telemetry, process tracking, and evidence artifacts.

See `docs/idea-intake-workflow.md` for the full intake narrative. For the deterministic intake-to-publication state audit, review `docs/end-to-end-workflow-audit.md`. For the planned API/dashboard redesign and memory-hardening lane, review `docs/api-dashboard-redesign.md`.

## What is in scope

- queue and project state APIs;
- pause/maintenance controls;
- worker preflight and single-active-lane safety checks;
- worker-gate process tracking and CPU/GPU quiet-window evidence;
- professional `/control/dashboard` operator console backed by bounded read models;
- evidence synchronization from worker to VM;
- paper/research-artifact generation;
- packaging/provenance scanning and corpus export;
- tests for routing, state, safety, telemetry, and paper artifact behavior.

## What is explicitly out of scope

- n8n workflow exports as part of the released system;
- workflow-tool configuration exports from earlier prototypes;
- claims of peer review or human authorship for generated papers;
- public release without secret scanning and packaging/provenance lint checks.

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
