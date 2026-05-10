# Native Codex worker contract

Status: current worker-facing contract as of 2026-05-10.

A worker run closes by leaving auditable local artifacts. The worker does not decide publication readiness and does not manually mark papers ready. The control plane consumes the artifacts, callback, and decision gate.
For current runtime host topology and callback/reconnect boundaries, see
[`current-runtime-snapshot.md`](current-runtime-snapshot.md).

## Required artifacts

| Artifact | Required | Purpose |
| --- | ---: | --- |
| `run_notes.md` | Yes | Commands, logs, metrics, interpretation, limitations, and final decision. |
| `.enoch/project_decision.json` | Yes | Native Codex decision artifact consumed by the control plane. |
| `.omx/project_decision.json` | Compatibility only | Mirror while legacy readers still exist. Do not treat this as the source of truth. |
| `results/*` | When an experiment runs | Metrics, outputs, manifests, and machine-readable result evidence. |
| `logs/*` | For non-trivial commands | Bounded command logs or summaries sufficient for inspection. |

## Decision schema

Use exactly this shape and enum vocabulary:

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

Do not invent enum values such as `negative_result`, `promising`, `partial_viable`, `paper_candidate`, `validated`, or `approved`.

## Decision meanings

| Decision | Use when |
| --- | --- |
| `finalize_positive` | Evidence supports writing a paper now. |
| `finalize_negative` | Result is negative, non-viable, insufficient, or not paper-worthy. |
| `needs_review` | Real external/private/human evidence is required before closure. |
| `blocked` | An execution blocker prevented a valid test. |
| `continue` | More autonomous work is needed before closure. |
| `branch_new_project` | This run found a distinct adjacent idea. |

A completed run is not positive merely because it ran successfully. Negative, mixed, and no-paper results are normal.

## Evidence-depth rules

Match the evidence depth to the claim:

- A smoke/proxy/synthetic run may close `finalize_negative` only when it is an explicit early falsification of the hypothesis or success threshold.
- Proxy-only results must say what was directly tested, what was only proxied, and what direct/full evidence would be required to overturn the result.
- Keep `evidence_strength` at `weak` or `moderate` unless direct/full-scale evidence was actually produced.
- Do not use `finalize_positive` for a proxy-only result unless the original hypothesis was explicitly scoped to that proxy.
- Do not add new schema fields to explain uncertainty; use `run_notes.md`, `recommended_next_action`, and `stop_reason`.

## Follow-up rules

Set `followup_recommended: true` only when all are true:

1. the current run is no-paper;
2. concrete evidence points to a different bounded test;
3. the follow-up has a measurable success threshold;
4. the follow-up has a clear stop condition.

Follow-up metadata creates adjacent investigation work only. It does not make the parent run paper-positive and it does not bypass the positive paper decision gate.

## Callback and resilience boundary

The worker gate posts completion to `/control/api/worker-callback` with an idempotency key. If a callback-ready state lacks a delivered key, the worker gate retries automatically. If the control plane disconnects during a bounded Research Facility tick, the timer script checks control-plane recovery and lets the next tick continue rather than replaying a non-idempotent POST.

Still not covered: a worker process killed mid-run before a decision artifact exists. In that case, inspect the worker project directory, logs, and process evidence before reconciling the queue row.
