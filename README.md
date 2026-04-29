# Enoch Agentic Research System

![Enoch — Agentic Research Control Plane](site/assets/social-card.svg)

Enoch is an agentic research control plane: it queues ideas, gates dispatch, supervises local AI runs, preserves evidence, and packages AI-generated research artifacts with provenance instead of pretending autonomous work is just a script.

## The problem

Long-running autonomous AI work fails in ways ordinary scripts do not:

- child processes continue after an agent session appears idle;
- GPU workers can still be active when queue state says no work is running;
- queues become stale or disagree across sources;
- evidence scatters across machines and run folders;
- generated reports overstate results when claim boundaries aren't preserved.

Enoch treats those as control-plane problems, not model problems. It uses process tracking, CPU/GPU quiet-window telemetry, idempotent APIs, stale-state reconciliation, a live dashboard, evidence bundles, and claim ledgers to make autonomous work observable and auditable.

> Agentic AI systems need control planes. A model can propose and execute work, but a separate system should decide what is queued, what is safe to dispatch, whether work is actually done, and what evidence supports the final artifact.

## How it works

```text
LLM research scout
  -> structured idea cards
  -> Notion scoring / weight matrix
  -> queue candidate
  -> VM control plane
  -> worker preflight and dispatch safety checks
  -> GB10 worker wake gate
  -> agent run with process + telemetry supervision
  -> evidence sync
  -> AI-generated research artifact
  -> corpus quality gates
```

The repository contains the execution/control-plane layer and supporting docs. Historical notes describe earlier migration experiments, but this is not a workflow-export repository and does not ship workflow-tool configurations.

## Main components

- **Control plane API** — queue state, project state, paper review state, pause/maintenance controls, and dispatch decisions; built with FastAPI and LangGraph-era graph boundaries.
- **Wake gate** — proves a run is actually done, not just agent-session-closed: process-tree tracking and CPU/GPU quiet-window telemetry sustained over a configurable window.
- **Worker preflight** — authenticated health checks against the worker before dispatching new work, so dispatch fails early rather than silently.
- **Single-lane safety** — prevents overlapping GPU-heavy work on constrained local hardware; the control plane holds the lock, not the dispatch script.
- **Evidence sync** — copies run notes, metrics, result summaries, evidence bundles, and claim ledgers from worker projects into the control plane before artifact generation begins.
- **Artifact writer** — generates publication-style Markdown reports from evidence context while preserving uncertainty and provenance; does not free-float against raw model output.
- **Quality gates** — scans generated reports for placeholder citations, missing provenance, and missing evidence artifacts before they enter the corpus.

## Generated research artifacts

The reports produced by Enoch runs are AI-generated research artifacts, not human-authored or peer-reviewed papers. They are built from run notes, evidence bundles, claim ledgers, and reproducibility traces.

> The maintainer releases the corpus for inspection and critique but does not claim personal authorship of the generated papers, arguments, or prose.

See [`docs/release/authorship-and-provenance.md`](docs/release/authorship-and-provenance.md) for the full framing and recommended citation language.

## Runtime and upstream tooling

Enoch is the project-specific control plane and release package. It runs agent work through Codex/OMX automation, including [oh-my-codex](https://github.com/Yeachan-Heo/oh-my-codex) orchestration for local agent execution. OMX is part of the operating substrate; generated research artifacts are produced by Enoch runs and the artifact writer, not by OMX as an owning publisher.

## Idea intake

Ideas are sourced from an upstream LLM-assisted scouting process that reviews technical signals such as AI news, public research papers, systems discussions, and local hardware/runtime opportunities. Candidate ideas are framed as structured experiment cards, scored in a Notion weight matrix, and handed to Enoch as queue candidates.

Notion is best understood as an intake and prioritization surface. Runtime authority begins in the Enoch control plane.

See [`docs/idea-intake-workflow.md`](docs/idea-intake-workflow.md).

## Getting started

For a local developer smoke test, start with [`docs/quickstart.md`](docs/quickstart.md).

For a full deployment (control VM, worker machine, systemd service, dashboard/API smoke tests, optional Pushover alerts, dispatch checks, and paper-writer settings), see [`docs/deployment-guide.md`](docs/deployment-guide.md).

For individual config fields, start from `config.example.json` and see [`docs/configuration-reference.md`](docs/configuration-reference.md). Required values:

- inbound API bearer token
- completion callback URL/token
- project root and dispatch script path
- worker URL/token
- optional notification and paper-writer provider settings

Never commit live config files or credentials.

## Development

```bash
uv run pytest -q
```

## Documentation

**Using Enoch:**
- [`docs/quickstart.md`](docs/quickstart.md) — local clone-to-dashboard smoke test
- [`docs/deployment-guide.md`](docs/deployment-guide.md) — full deployment guide
- [`docs/configuration-reference.md`](docs/configuration-reference.md) — config field reference
- [`docs/system-workflow.md`](docs/system-workflow.md) — architecture and control-plane boundaries
- [`docs/idea-intake-workflow.md`](docs/idea-intake-workflow.md) — LLM scouting, Notion scoring, and queue handoff

**Release context:**
- [`docs/release/authorship-and-provenance.md`](docs/release/authorship-and-provenance.md) — how generated reports should be framed
- [`docs/featured-paper-selection.md`](docs/featured-paper-selection.md) — rationale for the launch highlight set
- [`docs/outreach/launch-announcement.md`](docs/outreach/launch-announcement.md) — draft launch copy and repo descriptions
- [`docs/launch-checklist.md`](docs/launch-checklist.md) — public launch checklist
- [`docs/launch-todo.md`](docs/launch-todo.md) — remaining public-release gates
- [`docs/historical/`](docs/historical/) — historical migration notes retained for engineering context only
- [`site/`](site/) — static launch site

## Security

Before publishing or deploying changes, run secret scans and tests. See [`SECURITY.md`](SECURITY.md).

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
