# Blockwise stabilized 4-bit Adam second moment on a small transformer

Generated from graph: `2026-06-30T18:44:52.350174+00:00`
Runtime context: see [current-runtime-snapshot.md](../../current-runtime-snapshot.md) for live topology referenced by this packet.
Candidate kind: `negative`
Signal: `signal:blockwise-stabilized-4-bit-adam-second-moment-on-a-small-t-d75abbd657`
Status: `compute_scale_blocked`
Score: `83`

## Operator next action

Bounded full-scale validation of nonzero-floor 4-bit Adam second moments

## Scope and limits

- Claim scope: Historical bounded rejudge only: preserves the original local/toy/small/medium evidence as a useful signal without asserting full-scale validation.
- Scale limits: Historical rejudge found scale/full-validation limits in the original stop reason or next action; park unless a cheaper bounded test is defined.
- Hypothesis status: `mixed`
- Evidence strength: `moderate`

## Dashboard context

This packet is generated from the paper-material graph and is safe to inspect while the queue is running. It is an operator packet, not a dispatch command.
