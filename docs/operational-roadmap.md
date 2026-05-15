# Enoch operational roadmap

Status: future TODO / feature backlog as of 2026-05-10.

This page is not a commitment to implement every item immediately. It captures the next engineering direction after the native Codex worker migration, Research Facility autopilot, local Postgres control-plane move, long-haul readiness card, and corpus import automation.
For current runtime topology, see
[`current-runtime-snapshot.md`](current-runtime-snapshot.md).

## Future feature: self-healing doctor system

Problem: Enoch now has enough moving parts that a single hidden failed timer, stale active row, dirty release repo, provider quota issue, worker callback miss, or disk/mount problem can silently reduce 24x7 usefulness unless the operator notices the dashboard.

Goal: make operational diagnosis and safe repair first-class, structured, and auditable.

### Proposed layers

| Layer | Purpose | May mutate state? | LLM involved? |
| --- | --- | ---: | ---: |
| Doctor | Deterministically inspect live state, logs, timers, DB, worker, provider budget, corpus/release surfaces, and queue invariants. | No | No |
| Self-healer | Apply only allowlisted low-risk repairs with exact evidence and event logging. | Yes, bounded | No |
| LLM advisor | Analyze non-allowlisted failures and propose a fix plan from bounded evidence. | No by default | Yes |
| Operator escalation | Send Pushover/webhook messages with diagnosis, applied safe fixes, or approval-required proposed fixes. | No | Optional |

### Initial doctor command

```bash
scripts/enoch_doctor.py --live --json
```

The doctor should produce structured output like:

```json
{
  "ok": false,
  "severity": "warn",
  "problem": "research_autopilot_failed",
  "evidence": ["enoch-research-autopilot.service Result=exit-code"],
  "safe_auto_fix_available": true,
  "recommended_action": "reset failed state after confirming timer script reports healthy backpressure"
}
```

### Initial self-heal command

```bash
scripts/enoch_self_heal.py --live --apply-safe
```

Safe fixes should be allowlisted and evented. Examples:

- `systemctl reset-failed` for known benign oneshot timer outcomes after a passing readiness check.
- Restart `enoch-control-plane.service` after failed health check and clean config validation.
- Restart GB10 worker gate after failed health/preflight and no active worker process.
- Re-run capped corpus import when `publish_ready > 0` and release repos are clean.
- Clear a stale active queue row only when worker API proves no live run and callback/decision evidence exists.
- Re-run provider-budget preflight after provider transient error before spending tokens.

Unsafe fixes should require operator approval:

- Deleting or rewriting project artifacts.
- Force-pushing public repos.
- Unpausing broad queue after an explicit operator pause.
- Changing DB schema or migration state.
- Running arbitrary LLM-proposed shell commands.
- Remounting disks unless the mountpoint and device are explicitly configured and no process is writing.

### Alert/webhook integration

Pushover remains the human alert surface, but the same doctor report can be sent to a webhook that engages an LLM advisor. The LLM should receive only bounded evidence:

- doctor JSON
- readiness payload
- recent control events
- selected systemd logs
- relevant config snippets with secrets redacted
- allowed command list
- forbidden command list

The LLM advisor returns a proposed diagnosis and repair plan, not direct root-shell execution, unless a future policy explicitly allowlists that repair.

## Top 10 project needs

1. **Self-healing doctor and repair loop**
   - Build `enoch_doctor.py`, then `enoch_self_heal.py --apply-safe`, then wire doctor output to dashboard and Pushover/webhook.

2. **One canonical operational truth API**
   - Expand `/control/api/v1/automation-readiness` into a fuller operations contract that includes queue, worker, provider, corpus, release, disk, DB, and timers without requiring operators or agents to infer from separate cards.

3. **Research Facility quality control**
   - Improve idea generation scoring so the pipeline spends fewer runs on shallow negatives. Keep moonshots, but require stronger novelty comparison, baseline clarity, and failure-mode diversity.
   - Add an offline DSPy + GEPA optimization loop for Research Facility prompts and branching policy. This should consume Research Quality reports and run/decision traces, propose prompt or policy patches, and emit PR-ready diffs only. It must not mutate live queue, paper, or database state.

4. **Follow-up branching policy hardening**
   - Make follow-up creation more explicit: cap depth, track parent evidence, prevent repeat variants, and require a clear changed mechanism before launching adjacent work.

5. **Worker artifact contract enforcement**
   - Enforce `.enoch/project_decision.json`, `run_notes.md`, metrics, failure cases, and evidence manifests for every completed run. Fail or quarantine incomplete runs instead of letting weak artifacts propagate.

6. **Public corpus release integrity as a single pipeline**
   - Keep corpus import, count updates, GitHub metadata, docs/profile/site updates, Hugging Face sync, and validation under one deterministic release command with CI gates.

7. **Dashboard professional redesign and performance cleanup**
   - Continue moving toward a shadcn-quality operator console: stable cards, no flicker, clearer lanes, better mobile/small-screen behavior, fast paginated views, and debug-only raw states.

8. **Local Postgres operational maturity**
   - Add migrations discipline, backup restore drills, vacuum/analyze checks, index review, slow-query reports, and egress-safe local-first dashboard polling.

9. **Provider budget and model-rotation governance**
   - Track token/credit spend, success rate by provider/model/topic, quality yield, and stop conditions. Budget should shape generation cadence without silently shutting down useful work.

10. **End-to-end autonomous mode tests**
    - Add a long-haul simulation/smoke suite that validates: generate -> admit -> promote -> dispatch -> callback -> decision gate -> optional paper -> corpus import -> public count validation -> readiness remains clean.

## Future feature: offline DSPy + GEPA research-policy evolution

Problem: the Research Facility is now capable of running continuously, but many generated ideas still collapse into shallow negatives, proxy-only results, or adjacent variants of already-falsified mechanisms. Manual prompt tuning does not scale well enough for 24x7 operation.

Goal: use the same pattern seen in Hermes Agent Self-Evolution — DSPy + GEPA over traces and eval cases — but keep it offline, reviewable, and unable to mutate live automation state.

### Scope

This should optimize Research Facility prompts and policy text, not the live runtime directly.

Initial targets:

- provider idea-generation prompt;
- candidate scoring rubric;
- follow-up branching rubric;
- anti-duplicate / changed-mechanism requirements;
- evidence requirements for paper-positive decisions.

Non-targets for the first version:

- worker system prompt mutation;
- control-plane code mutation;
- direct DB writes;
- direct queue promotion;
- automatic production rollout.

### Proposed pipeline

```text
Research Quality report
  -> trace/eval dataset builder
  -> DSPy/GEPA offline optimizer
  -> candidate prompt/policy patches
  -> replay tests against known good/bad cases
  -> PR/manual review
```

### Proposed commands

```bash
scripts/build_research_quality_evalset.py \
  --database-url "$ENOCH_CONTROL_DATABASE_URL" \
  --quality-report /var/lib/enoch-control-plane/research-quality/latest-report.json \
  --output /tmp/enoch-research-quality-evalset.jsonl

scripts/evolve_research_prompt.py \
  --evalset /tmp/enoch-research-quality-evalset.jsonl \
  --target research-provider-prompt \
  --output-dir /tmp/enoch-research-prompt-evolution
```

### Guardrails

Every evolved variant must:

1. run outside the production autopilot path;
2. use an optional dependency environment, not the production control-plane venv;
3. produce a normal diff/patch, not direct writes to live config;
4. pass replay tests against known poor candidates and known useful branches;
5. preserve the boundary that generation does not queue work until promotion policy allows it;
6. preserve positive-only paper writing;
7. record the eval set, optimizer settings, and selected variant rationale.

### First useful eval cases

- candidates that looked novel but duplicated prior negative mechanisms;
- supported-but-negative decisions that should become warnings, not blockers;
- proxy-only positives that lacked enough evidence for paper writing;
- follow-up branches that reached max depth without a stronger mechanism;
- genuinely useful adjacent tests that should have been promoted.

## 10 stretch goals / nice-to-haves

1. **LLM operations advisor**
   - Feed doctor reports to a bounded LLM advisor that can explain likely root cause and propose a safe patch plan.

2. **Operator approval console for repairs**
   - Dashboard UI for proposed self-heal/LLM-advised actions: approve, reject, defer, or convert to GitHub issue.

3. **Experiment memory and anti-duplicate intelligence**
   - Semantic memory over prior negative runs so Research Facility can say, “we already tried this mechanism; here is what must change.”

4. **Research topic portfolio manager**
   - Balance idea generation across quantization, long-context, speculative decoding, tiny-VRAM training, distributed training, agent reliability, and local serving.

5. **Automatic paper quality uplift loop**
   - For positive papers, run an additional evidence/claim audit, improve weak sections, and regenerate only if the evidence ledger supports it.

6. **Artifact browser for project lineage**
   - Dashboard view that shows idea -> candidate -> project -> run -> decision -> follow-up -> paper -> corpus artifact with links to exact files.

7. **Reproducibility capsules**
   - Package runnable scripts, data generators, metrics, and environment notes per project so positive and negative runs are easier to inspect or rerun.

8. **Hardware-aware scheduler**
   - Route jobs based on GB10 state: GPU/CPU/memory pressure, USB mount health, current model cache, estimated runtime class, and overnight/daytime policies.

9. **Public transparency page for live corpus health**
   - Publish a sanitized status page: artifact count, strict audit pass count, packaging pass count, recent imports, and known limitations.

10. **Multi-worker expansion**
    - Add support for additional worker hosts with per-host capacity, health, labels, and failure isolation once the single-GB10 path stays stable.

## Implementation order suggestion

1. Doctor read-only report.
2. Dashboard/Pushover wiring for doctor output.
3. Allowlisted self-heal for timer backpressure and clean corpus no-op cases.
4. Stale active-row repair with worker proof.
5. Research Facility quality metrics and anti-duplicate memory.
6. Offline DSPy + GEPA eval-set builder for Research Facility prompt/policy evolution.
7. Long-haul simulation test.

## Research campaign evidence ladder

Current concern: 24x7 Research Facility runs are producing many clean negatives and too few paper-positive results. Two manual reference projects set the bar for what a promising project should do before it is called either a paper or a dead end:

- CoSpec: started with a small screen, escalated into confirmation runs, larger-budget checks, controls, mechanism diagnostics, and scoped claims. It became useful because the claim was narrowed and backed by persistence/control evidence rather than because it was universally groundbreaking.
- ArborealMoE: reached a credible no-paper result only after testing whether the mechanism fit, then investigating specialization collapse, alternative conditioning, longer runs, and scale/capacity limits. It identified a concrete next milestone instead of treating the first tiny negative as the whole story.

Policy direction:

1. Start every speculative idea with a small probe that can cheaply falsify the central mechanism.
2. If the small probe is promising, require a medium confirmation with a real baseline/control and direct target metrics.
3. If small and medium agree, allow a bounded full-scale validation, normally capped around 24 hours.
4. For model-training ideas, prefer GPT-2-small-class or parameter-matched baselines when feasible; a toy result should compare against a dense/standard model at the same parameter scale.
5. Use follow-up branches for promising proxy/medium results; do not write papers from proxy-only positives.
6. Keep hard negatives cheap, but do not collapse every promising result into a no-paper terminal state just because it is not publication-ready yet; classify bounded local signals as `research_outcome: useful_signal`.
7. Park scale-only results as `promising_if_scaled`/`compute_scale_blocked` instead of burning local worker time on unavailable datacenter validation.
8. Encode promising follow-ups as stronger ladder steps, not repeat tiny probes: mixed/supported `finalize_negative` results with moderate evidence, concrete evidence requirements, and follow-up depth below 3 should move to direct medium/full validation metadata while keeping the paper gate strict.
9. Use `scripts/audit_research_dedupe_loss.py` to review held/rejected near-duplicates before assuming dedupe was harmless. The audit ranks `duplicate_suppress`, `variant_hold`, and `branch_candidate` rows against prior decisions.
10. Later: add semantic clustering over prior good/bad runs so new idea generation can learn which mechanisms repeatedly fail and what changed evidence would justify another branch.
