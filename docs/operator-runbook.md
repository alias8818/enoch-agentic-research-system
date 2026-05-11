# Enoch operator runbook

Status: current operator guide as of 2026-05-10.

This runbook describes the current native Codex/control-plane deployment model. It is intentionally question-first: use it to decide whether long-haul automation is safe, what needs attention, and whether paper writing is correctly gated.

For the one-page canonical current-runtime facts, see
[`current-runtime-snapshot.md`](current-runtime-snapshot.md).

## Current topology

| Surface | Current owner | Notes |
| --- | --- | --- |
| Control plane | `enoch-core` at `/opt/enoch-control-plane` | FastAPI dashboard/API, local Postgres storage, automation timers, paper/corpus tooling. |
| Runtime database | local Postgres `enoch_control` on `enoch-core` | Older `supabase_*` config names and scripts are compatibility/migration naming, not Supabase Cloud runtime ownership. |
| Worker gate | GB10 checkout at `~/projects/enoch_testing_ground/enoch-control-plane` | Native Codex worker execution, process tracking, telemetry, and project artifacts. |
| Worker decision artifact | `.enoch/project_decision.json` | Preferred native contract. `.omx/project_decision.json` is a compatibility mirror only. |
| Control callback path | Tailscale URL to `/control/api/worker-callback` | Callback writes are idempotent by idempotency key. |

## Long-haul readiness

Use the readiness endpoint or script before resuming 24x7 automation:

```bash
uv run python scripts/check_longhaul_readiness.py \
  --live \
  --config /etc/enoch-control-plane/config.json \
  --control-url "$ENOCH_CONTROL_URL"
```

`READY` means the control plane sees the required automation posture: queue unpaused, maintenance off, timers active, recent successful research tick, corpus import freshness when needed, no blocked/attention work, consistent queue counts, positive-gated paper counters, and provider budget OK.

`BLOCKED` means at least one precondition failed. Do not unpause or widen automation until the blocker is understood. The first blocker in the readiness payload is the operator starting point, not the whole diagnosis.

## Dashboard questions

| Question | Trust this | Meaning |
| --- | --- | --- |
| What needs me? | `needs_attention` / `needs_operator` | Real blocker, worker question, dispatch failure, stale callback, or manual-action flag. |
| What is running? | `running`, `counts.active`, active worker rows | Active dispatch/run/paper/finalization or callback wait. |
| What can be written? | `paper_pipeline.write_needed` | Decision-gated positive paper work only. |
| Needs another investigation? | `investigation_pipeline.followup_needed` | No-paper row with concrete bounded follow-up metadata. |
| What can be published? | `paper_pipeline.publish_ready` | Finalized package missing corpus import ledger. |
| What is done/no paper? | `complete_no_paper` | Completed worker delivery that is not paper-positive. |

Raw states such as `wake_ready`, `draft_review`, `approved_for_corpus`, and `callback_pending` are debugging evidence. They are not the operator workflow.

## If active=0 and queued=0

1. Check the readiness payload first. If `READY`, the system may simply be idle.
2. Inspect Research Facility autopilot timer and last service result:

```bash
systemctl list-timers enoch-research-autopilot.timer --no-pager
systemctl show enoch-research-autopilot.service -p Result -p ActiveState --no-pager
```

3. Check provider budget. A budget block prevents candidate generation before tokens are spent.
4. Inspect Research Facility ledgers for admitted candidates and recent generation outcomes.
5. Inspect Research Quality status; the systemd tick refreshes `/var/lib/enoch-control-plane/research-quality/latest-report.json` after bounded cycles, and stale/missing reports are operator-visible readiness evidence.
6. Inspect `investigation_pipeline.followup_needed`; a follow-up candidate is adjacent investigation work, not paper-writing work.
6. If no candidates exist and the timer is healthy, the next bounded tick may generate or admit one candidate. Do not manually drain a broad queue.

## If research last result=exit-code

1. Read the recent service log:

```bash
journalctl -u enoch-research-autopilot.service -n 120 --no-pager
```

2. Distinguish benign bounded backpressure from real failure. A prior active worker lane can be a normal skip/noop. Provider quota, missing token, callback failure, or control-plane API errors are real blockers.
3. Re-run readiness after the next timer tick or after the specific fault is fixed.
4. Do not retry `/control/api/research/run-cycle` blindly. The live POST is intentionally not treated as a generic idempotent retry surface.

## If callback_pending or stale_callback_ready appears

`callback_pending` means the worker gate is ready and waiting for delivery confirmation. `stale_callback_ready` means the gate reached callback-ready but the local worker record has no delivered idempotency key.

Inspect:

```bash
journalctl -u enoch-control-plane.service -n 160 --no-pager
curl -fsS -H "Authorization: Bearer $TOKEN" \
  "$ENOCH_CONTROL_URL/control/api/status" | python3 -m json.tool
```

Current hardening:

- worker callbacks are recorded idempotently by idempotency key;
- callback-ready states without delivered keys are retried automatically by the worker gate;
- startup reconciliation can recover missing idle/finished observations;
- the dashboard still surfaces stale callback issues when they persist.

Still not covered: if the worker process is killed mid-run before the gate can observe completion and before a decision artifact exists, the operator must inspect the worker project directory and reconcile the active row from evidence.

## Pause and resume

Pause before maintenance, uncertain callback state, provider budget failures, worker instability, or public release operations:

```bash
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"requested_by":"operator","reason":"maintenance"}' \
  "$ENOCH_CONTROL_URL/control/pause"
```

Resume only after readiness blockers are cleared and worker preflight passes:

```bash
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"requested_by":"operator","reason":"ready"}' \
  "$ENOCH_CONTROL_URL/control/resume"
```

If you need a single controlled dispatch while the broad queue remains paused, use `/control/dispatch-one` with an explicit `project_id` after a dry run. Do not use it as a batch drain.

## Paper-writing gate

Confirm papers are written only from positive decisions:

1. Trust `paper_pipeline.write_needed`, not raw completed/no-paper counts.
2. Inspect the project decision artifact:
   - preferred: `.enoch/project_decision.json`;
   - compatibility mirror only: `.omx/project_decision.json`.
3. The only normal positive decision is exact `finalize_positive`.
4. `finalize_negative`, `needs_review`, `blocked`, missing, malformed, unknown, and follow-up-only decisions are no-paper until a later independent run becomes positive.
5. `continue` is not positive unless the control-plane compatibility parser has exact supported evidence in its supporting field.

Negative and mixed results are successful worker outcomes when they are evidence-backed. They must not become paper-writing backlog.
