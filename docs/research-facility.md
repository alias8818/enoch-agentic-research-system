# Enoch Research Facility

The Research Facility is the auditable lane for generating ideas before they enter the worker queue. It is intentionally separate from dispatch. A generated candidate is not work until it is admitted and recorded with an admission reason.

For how this lane fits the current runtime hosts, storage, bounded ticks, and
paper-gate boundaries, see
[`current-runtime-snapshot.md`](current-runtime-snapshot.md).

## Operator model

```text
sources
  -> research candidates
  -> dedupe/history comparison
  -> score novelty + feasibility + accessibility + falsifiability
  -> admission decision
  -> optional enoch.ideas / projects / queue_items row
  -> run / decision / paper/no-paper lineage
```

This lane answers two questions the old ad-hoc process could not answer reliably:

1. Where did this idea come from?
2. Why did it get queued?

## Ledgers

| Ledger | Table | Purpose | Does it dispatch work? |
| --- | --- | --- | --- |
| Source ledger | `enoch.research_sources` | External/internal source evidence: arXiv, GitHub, blogs, HN/X, prior Enoch results, user/ChatGPT supplied batches, generated hypotheses. | No |
| Candidate ledger | `enoch.research_candidates` | Raw generated proposals before admission. Stores hypothesis, mechanism, baseline, success threshold, kill condition, artifacts, evidence, cost, failure modes, novelty comparison, dedupe key, and score. | No |
| Admission ledger | `enoch.research_admissions` | Immutable explanation for admitted/rejected/merged/needs-review decisions. This is the answer to “why did this get queued?” | No |
| Lineage ledger | `enoch.research_lineage` | Connects source -> candidate -> idea -> project -> run -> decision -> paper/no-paper -> follow-up candidate. | No |

Promotion into runtime work still happens through the existing runtime ledgers:

- `enoch.ideas`
- `enoch.projects`
- `enoch.queue_items`

## Generation modes

`enoch.research_candidates.generation_mode` is explicit and constrained:

| Mode | Required grounding | Scoring emphasis |
| --- | --- | --- |
| `fresh_grounded` | At least one `source_ids` or `source_urls` entry. | External grounding, novelty, falsifiability. |
| `followup_from_negative` | `parent_project_id` or `parent_run_id`. | Explains what changed from a prior negative/mixed result. |
| `moonshot` | Crisp falsifiable test despite low feasibility. | High novelty/accessibility, strong kill condition. |
| `implementation_gap` | Practical gap in a paper/repo/system. | Feasible experiment and baseline clarity. |
| `paper_replication_extension` | Paper/source lineage. | Bounded replication plus nontrivial extension. |
| `home_hardware_accessibility` | Local/home AI impact. | Accessibility delta and hardware cost. |
| `manual_import` | User/operator supplied. | Complete test contract, dedupe, and score. |

Database checks enforce the two easiest-to-abuse modes:

- `fresh_grounded` must include source evidence.
- `followup_from_negative` must include parent lineage.

## Candidate contract

A candidate must be a testable research proposal, not a vague idea. Required fields are:

- `hypothesis`
- `mechanism`
- `baseline_to_beat`
- `success_threshold`
- `kill_condition`
- `expected_artifacts`
- `required_evidence`
- `estimated_runtime_class`
- `expected_token_budget`
- `machine_target`
- `likely_failure_modes`
- `novelty_comparison` when similar prior projects are present

The deterministic planner in `scripts/research_facility.py` rejects candidates that miss the core contract, lack required grounding, look like shallow incremental sludge, or try to re-run known negatives without explaining the new mechanism/evidence.



## Provider budget preflight

Provider-backed generation must check quota before spending. Synthetic is supported through `scripts/research_provider_budget.py`. The simplest path reads the API key from `SYNTHETIC_API_KEY` and does not print the key:

```bash
python scripts/research_provider_budget.py \
  --provider synthetic \
  --estimated-requests 4 \
  --reserve-requests 4 \
  --min-remaining-credits 5 \
  --min-rolling-remaining 10 \
  --output /tmp/synthetic-budget.json
```

Preferred production path on exe.dev is an HTTP Proxy integration so the key does not live on `enoch-core` at all. Create/attach the integration from the exe.dev shell, using the current CLI help if flags differ:

```bash
ssh exe.dev
integrations add http-proxy --name=synthetic --target=https://api.synthetic.new --bearer=<paste-synthetic-api-key> --attach vm:enoch-core
integrations list
```

Do not export or store the Synthetic key on `enoch-core`. After the integration is attached, the VM calls the internal proxy URL and exe.dev injects the Authorization header. Then run the preflight from the VM without local auth:

```bash
python scripts/research_provider_budget.py \
  --provider synthetic \
  --base-url https://synthetic.int.exe.xyz \
  --no-auth \
  --estimated-requests 4 \
  --reserve-requests 4 \
  --output /tmp/synthetic-budget.json
```

The Research Facility should fail closed when the provider is limited, the quota endpoint is unavailable, or available credits/rolling requests fall below the configured reserve. Budget checks belong before provider-backed candidate generation, not in dispatch.

For model diversity, rotate provider-backed candidate batches across strong models such as Kimi and GLM, and vary temperature/seed as generation metadata. The deterministic planner still owns admission: model diversity can create candidates, but it cannot bypass grounding, dedupe, novelty comparison, success thresholds, or kill conditions.

## Source scanning

Use the deterministic scanner to create a grounded candidate batch without writing to the database:

```bash
python scripts/research_facility_scan.py \
  --arxiv-query 'cat:cs.LG AND all:speculative decoding' \
  --max-results 5 \
  --output /tmp/research-source-batch.json
```

The scanner can also convert saved source records, which is safer for repeatable tests and for externally supplied source lists:

```bash
python scripts/research_facility_scan.py \
  --source-json sources.json \
  --output /tmp/research-source-batch.json
```

The output contains both `sources` and `candidates`. Pass the same file into the planner; it reads the `candidates` array, preserves `source_records`, and emits source-ledger SQL before candidate/admission SQL:

```bash
python scripts/research_facility.py /tmp/research-source-batch.json \
  --history-json prior-enoch-history.json \
  --output /tmp/research-plan.json \
  --emit-sql /tmp/research-ledgers.sql
```

For live/local Postgres checks, provide `--database-url` from the service environment instead of exporting secrets into command history. The planner queries prior `ideas`, `projects`, `project_decisions`, and `research_candidates` to mark exact duplicates as `merged` and require a novelty comparison for similar prior work.

This keeps source scanning, candidate generation, history comparison, admission, and queue promotion as separate steps.

The dashboard follows the same split:

- `Generate smoke batch` dry-runs first, then writes only Research Facility source/candidate/admission/lineage rows.
- `Generate provider batch` dry-runs a provider quota preflight first. The live action spends one provider request, then writes only Research Facility source/candidate/admission/lineage rows.
- `Promote selected candidate` dry-runs first, then promotes exactly one already-admitted candidate into `enoch.ideas`, `enoch.projects`, and `enoch.queue_items`.
- `Run bounded cycle` is the first policy-gated automation layer. It requires an explicit live `enabled` flag, checks provider budget, can spend one provider request, can promote up to one admitted candidate, can optionally dispatch at most one selected queued item while preserving the global queue pause, and can optionally draft/finalize at most one paper if the completed run is decision-positive.
- Provider generation and candidate promotion never dispatch worker execution. The bounded-cycle action can dispatch exactly one item only when its dispatch option is explicitly enabled for that call.
- The systemd autopilot is a repeating bounded tick, not a broad queue drain. Each completed tick also refreshes the read-only Research Quality report at `/var/lib/enoch-control-plane/research-quality/latest-report.json` when a database URL is available; that refresh is fail-soft and does not enqueue, dispatch, draft, or mutate database state. In the current `enoch-core` deployment, `systemctl list-timers enoch-research-autopilot.timer` showed a roughly ten-minute cadence on 2026-05-10; re-check the timer before reporting live cadence because systemd overrides can differ from the checked-in unit.

The provider-backed endpoint is:

```text
POST /control/api/research/generate-provider-batch
```

It is fail-closed:

1. query provider quota through the configured proxy;
2. refuse generation if remaining credit/rolling request reserve is too low;
3. dry-run without spending a provider request;
4. live-run at most the requested bounded candidate count;
5. score candidates through the deterministic planner;
6. persist only Research Facility ledgers with `queue_admitted = false`.

The bounded-cycle endpoint is:

```text
POST /control/api/research/run-cycle
```

Default policy:

```json
{
  "enabled": false,
  "max_provider_requests_per_run": 1,
  "max_promotions_per_run": 1,
  "max_dispatches_per_run": 0,
  "wait_for_completion": false,
  "max_wait_seconds": 0,
  "max_paper_drafts_per_run": 0,
  "max_publication_rewrites_per_run": 0,
  "allowed_models": ["hf:moonshotai/Kimi-K2.6", "hf:zai-org/GLM-5.1"],
  "min_admission_score": 72,
  "require_budget_ok": true,
  "stop_if_queue_active": true,
  "stop_if_dashboard_attention": true
}
```

Live calls must set `enabled: true`; dry-runs do not spend provider requests or write rows. The endpoint records a `research.run_cycle.*` control event for blocked, dry-run, and live outcomes. It does not unpause the broad queue. Paper drafting/finalization is disabled by default and must be explicitly bounded with:

```json
{
  "max_paper_drafts_per_run": 1,
  "max_publication_rewrites_per_run": 1
}
```

That paper stage still uses the normal local decision gate. Negative, needs-review, missing, malformed, or otherwise non-positive decision artifacts produce no paper.

For unattended operation, the optional systemd tick is `enoch-research-autopilot.timer` / `enoch-research-autopilot.service`. The unit is inert unless `ENOCH_ENABLE_RESEARCH_AUTOPILOT=1` is set in a systemd override. A live tick is capped at one provider request, one promotion, one dispatch, one paper draft, and one finalization package. After the bounded cycle returns, the same script refreshes the read-only Research Quality sidecar report with `scripts/dspy_research_quality.py`; use `ENOCH_RESEARCH_QUALITY_REFRESH_ONLY=1` for a manual refresh smoke test without running a research cycle. Transient disconnects during a long bounded tick are handled conservatively: the script verifies that the control plane recovered and waits for the next tick instead of retrying a non-idempotent POST.

## Admission behavior

Use the planner first:

```bash
python scripts/research_facility.py ideas.json --output /tmp/research-plan.json
```

To generate SQL for the four Research Facility ledgers only:

```bash
python scripts/research_facility.py ideas.json \
  --output /tmp/research-plan.json \
  --emit-sql /tmp/research-ledgers.sql
```

To also queue admitted candidates, make the promotion explicit:

```bash
python scripts/research_facility.py ideas.json \
  --output /tmp/research-plan.json \
  --emit-sql /tmp/research-ledgers-and-queue.sql \
  --queue-admitted \
  --requested-by operator:jeremy
```

`--queue-admitted` is intentionally separate so review/scoring can happen without mutating runtime queue state.

## Guardrails

- The Research Facility tables do not dispatch work by themselves.
- The workbench view is `security_invoker` and the tables have RLS enabled.
- Runtime queue mutation is idempotent and refuses to overwrite in-flight queue rows.
- Dedupe uses a stable `dedupe_key`; duplicate keys in the same batch are rejected by the planner and unique in the database.
- Similar prior projects require `novelty_comparison`.
- Candidate lineage is recorded before queue promotion.

## Validation

Relevant local checks:

```bash
uv run pytest tests/test_research_facility.py -q
uv run pytest tests/test_deploy_units.py tests/test_supabase_runtime_cutover.py tests/test_research_facility.py -q
python scripts/validate_supabase_migrations.py
```

`validate_supabase_migrations.py` checks that the four Research Facility ledgers exist, RLS/policies are present, the workbench view exists, `security_invoker` is set, and the grounding/parent-lineage checks are present.
