# Enoch launch announcement drafts

## One-line positioning

Enoch is an agentic research control plane: it queues ideas, gates dispatch, supervises local AI runs, preserves evidence, and packages AI-generated research artifacts with provenance instead of pretending autonomous work is just a script.

## Short launch post

I’m releasing Enoch, a local agentic research control plane, plus a corpus of 393 canonical AI-generated research artifacts.

The interesting part is not that the papers are “human papers.” They are not. They are explicitly AI-generated artifacts, and I do not claim personal authorship of their prose, arguments, or results.

The interesting part is the system around them: idea intake, scoring, queue state, maintenance pause, worker preflight, worker-gated execution, process/telemetry truth, evidence sync, claim ledgers, paper rewriting, packaging/provenance lint scans, strict claim/evidence audit status, and a dashboard for seeing what the system is actually doing. Enoch is built with FastAPI/LangGraph-era control-plane boundaries and operated through Codex automation, including Codex CLI.

The quality floor is explicit: operational health, promising-signal preservation, paper-corpus readiness, and public trust posture are separate claims. A useful signal can be preserved without calling it a paper, and a generated paper can pass the current gates without being peer-reviewed or independently replicated.

Repos:

- Code: https://github.com/alias8818/enoch-agentic-research-system
- Corpus: https://github.com/alias8818/enoch-ai-research-corpus
- Docs: https://solo-09d10f60.mintlify.app/

## Longer announcement

Over the last few weeks I built and operated Enoch: a control plane for autonomous AI research runs on a local worker machine, using LangGraph-era control-plane patterns and Codex orchestration for local agent execution.

The problem I kept hitting was not “can a model write code or a report?” It was everything around that: queues hanging, stale state, worker/process truth disagreeing with dashboard state, evidence spread across machines, paper drafts missing key experimental context, and no clean way to pause the lane for maintenance.

Enoch treats those as first-class systems problems.

A run goes through:

1. LLM-assisted idea scouting and structured idea cards.
2. Control-plane scoring / ideas workbench intake.
3. Control-plane queue and maintenance gates.
4. Worker preflight and single-lane safety checks.
5. Wake-gated execution with process and telemetry observation.
6. Evidence sync: run notes, metrics, claim ledgers, manifests, and bundles.
7. AI artifact rewriting against evidence context.
8. Corpus packaging/provenance lint scans, strict claim/evidence audit, and provenance packaging.

I’m also releasing a corpus of 393 canonical generated research artifacts from the system. These are publication-style AI-generated reports, not peer-reviewed publications and not human-authored papers. The point is transparency: show the outputs, show the evidence shape, keep promising signals out of the paper count, and let people inspect the system that generated them.

What I hope is useful to others:

- a concrete pattern for supervising long-running local agent work with Enoch Control Plane, LangGraph-era state boundaries, and Codex-local orchestration;
- a worker-gate model for deciding when autonomous work is actually done;
- queue reconciliation and pause/maintenance controls;
- evidence-bounded writing rather than free-floating LLM summaries;
- explicit quality-floor buckets so weak/local-only records, promising signals, and paper-corpus artifacts are not conflated;
- examples of local AI infrastructure experiments that include negative findings and caveats.

## GitHub repo descriptions

Code repo:

> Agentic research control plane built with FastAPI/LangGraph-era state boundaries and operated through Codex: queue state, worker preflight, worker-gated execution, evidence sync, dashboard, alerts, quality-floor buckets, and AI-generated paper packaging.

Corpus repo:

> 393 canonical AI-generated research artifacts produced by Enoch, packaged with provenance metadata, evidence bundles, claim-ledger files, manifests, packaging/provenance reports, and a strict claim/evidence audit report. Current public status: 393/393 packaging/provenance lint passes and 393/393 strict claim/evidence audit pass.

Docs repo:

> Source-grounded Enoch docs for operators, contributors, and reviewers covering the control plane, corpus, deployment, provenance, and release boundaries. Hosted at https://solo-09d10f60.mintlify.app/ with source at https://github.com/alias8818/enoch-docs.

## Thread outline

1. “I’m releasing Enoch: an agentic research control plane plus 393 canonical AI-generated research artifacts.”
2. “The papers are not human-authored; that is explicit. The point is the system that generated and bounded them.”
3. “Why I built it: queues hung, dashboards lied, workers kept running, evidence got scattered.”
4. “What Enoch does: queue, preflight, pause, worker gate, evidence sync, claim ledgers, paper writer, packaging/provenance lint checks, strict audit, and quality-floor buckets—operated through Codex, with Codex CLI credited as orchestration infrastructure.”
5. “Some highlighted artifacts: Evidence-Bound Proof Synthesizer, Resource-Bounded Agent Kernel, DFlash GB10 throughput, Value-per-Joule Broker, and Memory Pressure Admission Gate.”
6. “What I want feedback on: control-plane design, evidence schema, quality-floor framing, and which experiments deserve real replication.”


## Launch order

1. GitHub repos and launch site are the source-of-truth surfaces.
2. Personal site/blog post should use the longer announcement and link code, corpus, docs, and the launch site.
3. X/LinkedIn should use the short launch post plus one screenshot/card from `site/highlights.json` or the sanitized dashboard images.
4. Hacker News/Reddit/dev communities should emphasize the control-plane and evidence-bound corpus, not claims of peer-reviewed papers.
5. Convert substantive feedback into GitHub issues before changing pipeline behavior or public claims.

## Screenshot/card candidates

- `enoch-docs/images/dashboard-active-queue.png` — operator dashboard state.
- `enoch-docs/images/dashboard-paper-reviews.png` — publication automation/detail view.
- `enoch-docs/images/dashboard-papers.png` — generated artifact paths and ledgers.
- `enoch-docs/images/dashboard-queued-queue.png` — queue/intake view.
- `site/highlights.json` — text cards for the highlighted artifacts.
