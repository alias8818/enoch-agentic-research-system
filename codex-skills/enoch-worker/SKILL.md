---
name: enoch-worker
description: Use when running an Enoch autonomous research project on a worker machine. Explains the expected artifacts, decision schema, negative/positive paper gate, follow-up rules, and operator-safety boundaries for Codex-native Enoch runs.
---

# Enoch Worker Skill

Use this skill whenever the current directory is an Enoch project workspace or the prompt says the run is controlled by Enoch.

## What Enoch is

Enoch is an autonomous research control plane. The control plane queues ideas, dispatches one worker lane at a time, receives worker completion callbacks, decision-gates paper writing, and publishes only finalized/sanitized artifacts.

The worker's job is not to produce a positive result. The worker's job is to run a bounded, evidence-backed experiment and leave clear artifacts that let the control plane decide what happens next.

## Worker contract

Work autonomously inside the project directory.

Required artifacts:

- `run_notes.md` — concise report with commands, logs, metrics, interpretation, limitations, and final decision.
- `.enoch/project_decision.json` — preferred native decision path consumed by Enoch Control Plane.
- `.omx/project_decision.json` — legacy compatibility path for existing readers; keep it consistent with `.enoch/project_decision.json` during transition.
- Metric/result files under `results/` when an experiment runs.
- Logs under `logs/` for non-trivial commands.

Do not wait for human input for ordinary installable/downloadable/runnable dependencies. Use a smoke test before any calibrated or long run.

## Decision schema

Write `.enoch/project_decision.json` with this exact shape and enum vocabulary, and mirror it to `.omx/project_decision.json` when compatibility is required:

```json
{
  "project_decision": "finalize_positive | finalize_negative | needs_review | blocked | continue | branch_new_project",
  "hypothesis_status": "supported | unsupported | mixed | inconclusive",
  "confidence": "low | medium | high",
  "evidence_strength": "weak | moderate | strong",
  "novelty_progress": true,
  "results_changed": true,
  "recommended_next_action": "one concrete next action or stop rationale",
  "stop_reason": "",
  "followup_recommended": false,
  "followup_type": "",
  "followup_title": "",
  "followup_hypothesis": "",
  "followup_required_evidence": [],
  "followup_success_threshold": "",
  "followup_stop_condition": "",
  "followup_depth": 0
}
```

Do not invent synonyms like `negative_result`, `promising`, `paper_candidate`, or `partial_viable`.

## Paper gate rules

- `finalize_positive`: only when evidence supports writing a paper now.
- `finalize_negative`: negative, non-viable, insufficient, or not paper-worthy result.
- `needs_review`: only when real external/private/human evidence is required.
- `blocked`: execution blocker prevented a valid test.
- `continue`: more autonomous work is needed before closure.
- `branch_new_project`: this run found a distinct adjacent idea.

A completed run is not paper-positive just because it ran successfully. Negative and mixed results are normal.

## Follow-up rules

Use follow-up fields only when a no-paper run produced specific bounded evidence for a next adjacent test.

Set `followup_recommended: true` only when all are true:

1. the current run is no-paper;
2. there is concrete evidence for a different bounded test;
3. the follow-up has a measurable success threshold;
4. the follow-up has a clear stop condition.

Do not recommend follow-up for weak speculation, ordinary incremental tweaks, or hard negatives.

## GB10 constraints

- Start with a small smoke test.
- Calibrate CPU/GPU/memory before long runs.
- Swap may be disabled; use `MemAvailable`, UMA memory, and process telemetry rather than assuming swap exists.
- Prefer deterministic scripts and saved logs over narrative-only claims.
- Keep outputs bounded and inspectable.

## Final answer style

At the end of a run, state:

- final decision;
- key metrics;
- artifact paths;
- validation commands run;
- one concrete next action or stop rationale.

The control plane consumes artifacts and callbacks; do not manually write papers or mark publications ready from a worker run.
