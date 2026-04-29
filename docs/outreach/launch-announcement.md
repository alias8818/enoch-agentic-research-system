# Enoch launch announcement drafts

## One-line positioning

Enoch is an agentic research control plane: it queues ideas, gates dispatch, supervises local AI runs, preserves evidence, and packages AI-generated research artifacts with provenance instead of pretending autonomous work is just a script.

## Short launch post

I’m releasing Enoch, a local agentic research control plane, plus a corpus of 120 AI-generated research artifacts.

The interesting part is not that the papers are “human papers.” They are not. They are explicitly AI-generated artifacts, and I do not claim personal authorship of their prose, arguments, or results.

The interesting part is the system around them: idea intake, scoring, queue state, maintenance pause, worker preflight, wake-gated execution, process/telemetry truth, evidence sync, claim ledgers, paper rewriting, quality scans, and a dashboard for seeing what the system is actually doing.

Repos:

- Code: https://github.com/alias8818/enoch-agentic-research-system
- Corpus: https://github.com/alias8818/enoch-ai-research-corpus

## Longer announcement

Over the last few weeks I built and operated Enoch: a control plane for autonomous AI research runs on a local worker machine.

The problem I kept hitting was not “can a model write code or a report?” It was everything around that: queues hanging, stale state, worker/process truth disagreeing with dashboard state, evidence spread across machines, paper drafts missing key experimental context, and no clean way to pause the lane for maintenance.

Enoch treats those as first-class systems problems.

A run goes through:

1. LLM-assisted idea scouting and structured idea cards.
2. Notion scoring / weight-matrix intake.
3. Control-plane queue and maintenance gates.
4. Worker preflight and single-lane safety checks.
5. Wake-gated execution with process and telemetry observation.
6. Evidence sync: run notes, metrics, claim ledgers, manifests, and bundles.
7. AI paper rewriting against evidence context.
8. Corpus quality scans and provenance packaging.

I’m also releasing a corpus of 120 generated research artifacts from the system. These are publication-style AI-generated reports, not peer-reviewed publications and not human-authored papers. The point is transparency: show the outputs, show the evidence shape, and let people inspect the system that generated them.

What I hope is useful to others:

- a concrete pattern for supervising long-running local agent work;
- a wake-gate model for deciding when autonomous work is actually done;
- queue reconciliation and pause/maintenance controls;
- evidence-bounded writing rather than free-floating LLM summaries;
- examples of local AI infrastructure experiments that include negative findings and caveats.

## GitHub repo descriptions

Code repo:

> Agentic research control plane: queue state, worker preflight, wake-gated execution, evidence sync, dashboard, alerts, and AI-generated paper packaging.

Corpus repo:

> 120 AI-generated research artifacts produced by Enoch, packaged with provenance metadata, evidence bundles, claim ledgers, manifests, and quality reports.

## Thread outline

1. “I’m releasing Enoch: an agentic research control plane plus 120 AI-generated research artifacts.”
2. “The papers are not human-authored; that is explicit. The point is the system that generated and bounded them.”
3. “Why I built it: queues hung, dashboards lied, workers kept running, evidence got scattered.”
4. “What Enoch does: queue, preflight, pause, wake gate, evidence sync, claim ledgers, paper writer, quality gates.”
5. “Some highlighted artifacts: Evidence-Bound Proof Synthesizer, Resource-Bounded Agent Kernel, DFlash GB10 throughput, Value-per-Joule Broker, and Memory Pressure Admission Gate.”
6. “What I want feedback on: control-plane design, evidence schema, generated-paper framing, and which experiments deserve real replication.”
