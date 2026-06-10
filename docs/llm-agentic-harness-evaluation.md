# LLM agentic harness evaluation

ALI-124 tracks whether Enoch should add tool-aware LLM workflows with Context7,
Exa, skills, or an external agentic harness such as Pi.

## Recommendation

Keep native Enoch provider routing as the production authority.

Trial a bounded agentic sidecar for one low-risk workflow before any production
adoption. The first trial should be read-only research idea enrichment because
it can use external search or documentation without mutating queue, paper,
publication, or readiness state.

Do not replace the current LLM settings, provider-budget, model-health,
format-probe, or workflow-pool machinery until a trial proves better provider
selection, cheaper output, and cleaner telemetry under deterministic validators.

## Current workflow inventory

| Workflow | Current surface | Tool-access fit | Recommendation |
| --- | --- | --- | --- |
| Research candidate generation | `scripts/research_provider_generate.py`, `/control/api/research/run-cycle`, `deploy/enoch_research_autopilot.py` | Medium. Exa can find sources; Context7 helps only for library/framework ideas. | Trial only through a sidecar that produces candidate-source evidence, then pass through existing deterministic admission and provider-budget gates. |
| Research janitor review | `scripts/research_facility_llm_review.py`, autopilot janitor sidecar | Low. This is adjudication over existing rows, not external discovery. | Keep native. Add better telemetry before tools. |
| Paper drafting and rewrite | paper writer/rewrite routes and evidence sync gates | Medium to high. Search/docs can improve caveats, but can also inject unsupported claims. | Do not grant tools until claim/evidence validators can attribute each externally sourced assertion. |
| Evidence checks | paper package, source-lineage, strict claim/evidence validators | Low for LLM authority, medium for retrieval assistance. | Keep deterministic validators authoritative. Tool output may suggest missing evidence only. |
| Model health probes | `/control/api/settings/llm/test`, `/control/api/v1/observability/llm-models`, autopilot health sidecars | None. Health probes should remain small, bounded, and provider-direct. | No tool access. |
| Idea generation and enrichment | research provider generation, intake/backlog workflows | High. This is the best place for Context7/Exa because outputs are advisory until admitted. | First PoC target. |

## Tool policy

Tool access must be workflow-scoped and explicit.

| Tool class | Allowed first-trial workflows | Disallowed workflows | Notes |
| --- | --- | --- | --- |
| Context7 docs | `idea_generation_enrichment` when the topic names a library, SDK, API, CLI, or cloud service | model health, provider budget checks, readiness, queue dispatch | Record library query, resolved library id, docs query, and source URL/id. |
| Exa/web search | `idea_generation_enrichment`, source discovery for candidate generation | model health, queue dispatch, paper publication/import gates | Record query text, result URL, title, ranking position, and retrieval timestamp. |
| Skills | sidecar prompt planning and review only | direct state mutation, callback completion, publication decision | Skill use is provenance, not authority. |
| Pi or other harness | read-only sidecar PoC | production routing, queue mutation, paper publication, settings writes | Native Enoch remains the system boundary until parity is proven. |

## Deterministic telemetry contract

Every tool-enabled LLM workflow must emit these event types before its output can
be used by later automation:

- `llm_harness.route_decision`
- `llm_harness.tool_call`
- `llm_harness.tool_result`
- `llm_harness.output_contract`
- `llm_harness.cost_observation`

Required fields for every event:

- `workflow_id`
- `run_id` or `trace_id`
- `provider_id`
- `model_id`
- `tool_name` when a tool is involved
- `policy_id`
- `source`
- `started_at`
- `completed_at`
- `status`
- `failure_kind`
- `estimated_cost_usd`
- `input_token_count`
- `output_token_count`

Required route-decision fields:

- `candidate_provider_ids`
- `candidate_model_ids`
- `selected_provider_id`
- `selected_model_id`
- `selection_reason`
- `fallback_rank`
- `budget_gate_status`
- `health_gate_status`

Required tool-result fields:

- `result_count`
- `redacted_result_hashes`
- `source_urls`
- `source_titles`
- `retrieval_timestamp`

No raw provider response, raw tool payload, bearer token, provider secret, or API
key may be stored in these events.

## Boundary invariants

- Tool output is advisory evidence, never system truth.
- Provider routing decisions are observable before output is accepted.
- Tool allowlists are per workflow, not global.
- Budget, timeout, cooldown, and retry limits apply before any tool or provider
  call.
- Structured output must pass the existing workflow parser or schema before any
  queue, paper, or readiness state is mutated.
- Externally sourced facts must be represented as provenance fields and must not
  bypass claim/evidence validators.

## Cost and risk estimate

| Workflow | Cost risk | Integrity risk | Operational risk |
| --- | --- | --- | --- |
| Research candidate generation | Medium. Search plus model calls can multiply provider spend. | Medium. Source-looking output can still be low quality. | Medium. Needs cooldowns and source dedupe. |
| Research janitor review | Low to medium. Batch review already quota gated. | Medium. A harness may normalize bad rows too aggressively. | Low. Keep read-only first. |
| Paper drafting and rewrite | Medium. Long context plus retrieval can be expensive. | High. Unsupported external claims are release-risky. | Medium. Must preserve evidence gates. |
| Evidence checks | Low. Deterministic validators dominate. | Low if tool output stays advisory. | Low. |
| Model health probes | Low. Current probes are small. | Low. | Medium if tools are mistakenly added; they should not be. |
| Idea generation and enrichment | Medium. Search/provider calls can grow with backlog. | Medium. Admission gates contain most harm. | Medium. Best first PoC because blast radius is bounded. |

## Native versus sidecar comparison metrics

Native Enoch provider routing remains the production authority until a
deterministic comparison report has enough evidence for both native routing and
the read-only sidecar. The report must not mutate production routing, workflow
pools, queue rows, settings, paper state, or readiness state.

Required comparison metrics:

- `cost_per_admitted_candidate`
- `provider_failure_rate`
- `malformed_output_rate`
- `output_contract_pass_rate`
- `admitted_candidate_yield`
- `source_usefulness_rate`

The report decision must be `insufficient_data` when either strategy is below
the configured minimum attempt count or any required metric is unavailable.
Complete sidecar-superior evidence may only produce
`sidecar_candidate_for_manual_review`; it is not permission to replace native
routing automatically.

## Proof-of-concept plan

1. Add a read-only `idea_generation_enrichment` sidecar.
2. Allow only Context7 docs and Exa/web search in that sidecar.
3. Emit the five `llm_harness.*` event types for every route decision, tool call,
   tool result, output contract check, and cost observation.
4. Produce candidate-source suggestions only; do not mutate queue rows.
5. Feed accepted suggestions through existing research candidate planning,
   admission, provider-budget, and source-lineage validators.
6. Compare sidecar output against native generation for cost, source usefulness,
   malformed output rate, provider failure rate, and admitted candidate yield.

## Implementation issues to create

- Add a persisted `llm_harness.*` telemetry event contract and API/read-model
  surface.
- Add a read-only idea-enrichment sidecar with per-workflow tool allowlists.
- Add dashboard observability for harness route decisions, tool failures, cost,
  and output-contract pass/fail.
- Add provider-router comparison metrics that compare native routing against the
  sidecar without changing production routing.

## ALI-178 structured-output runtime decision — 2026-06-10

ALI-178 revisited the harness question after MiniMax M3 and Kimi showed different
`candidate_json` behavior. The current decision is narrower than the ALI-124
sidecar PoC: do **not** adopt Flue, PyFlue, or Pi as the production harness for
structured-output validation.

### Decision

Use a thin in-repo adapter around Enoch's existing provider calls and
`llm_harness` telemetry. Prefer library-grade pieces over a framework takeover:

- Pydantic models for typed output contracts.
- Pydantic AI only where an agent-style typed call is actually needed.
- Instructor as an optional one-shot typed extraction fallback if provider-native
  JSON/schema behavior remains inconsistent.
- Tenacity-style provider retries for transport/rate-limit/timeout failures.
- Existing Enoch `llm_harness.*` events as the authoritative telemetry and
  operator surface.

### Rejected as production harnesses

| Candidate | Decision | Reason |
| --- | --- | --- |
| Flue | Reject | TypeScript-first full agent framework; wrong language and too much surface for the Python control plane. |
| PyFlue | Reject for now | Alpha Python port with high overlap against Enoch's existing queue, dispatch, sessions, skills, and telemetry. It appears to use Pydantic AI internally, which Enoch can use directly if needed. |
| Pi / pi-llm Python ports | Reject as primary | Original TypeScript ecosystem is interesting, but Python ports are small/single-maintainer and would replace provider-call surfaces Enoch already owns. |

### Thin-adapter contract

The next implementation slice should keep this contract explicit and testable:

- **Typed validation:** every structured workflow maps to a Pydantic schema and a
  deterministic parser/validator result.
- **Retry taxonomy:** classify failures as `validation`, `recoverable_shape`,
  `rate_limit`, `timeout`, `provider_error`, `auth_error`, `schema_mismatch`, or
  `fatal` before dashboard/readiness aggregation.
- **Telemetry:** persist prompt contract, provider/model, schema mode,
  `valid_json`, `schema_ok`, `malformed_kind`, `recoverable_json_shape`, latency,
  token usage, and redacted preview in existing events.
- **Timeout/cost caps:** provider calls remain bounded before any side effect;
  validation retries must have an independent cap from transport retries.
- **Tool allowlists:** any future agent/tool path must be workflow-scoped and
  disabled for model-health probes, provider-budget checks, readiness, queue
  dispatch, and paper publication gates.
- **Rollback boundary:** validated typed output and redacted raw evidence must be
  persisted before queue, paper, readiness, or route state can be mutated.

### Post-fix probe evidence

After the `candidate_json` contract fix, live bounded probes through
`/control/api/settings/llm/test` showed:

- `moonshotai/kimi-k2.6`: `valid_json=true`, `schema_ok=true`,
  `malformed_kind=""`, `finish_reason=stop`, `visible_chars=62`, latency about
  3.7s.
- `minimax/minimax-m3`: endpoint healthy but `valid_json=false`,
  `schema_ok=false`, `malformed_kind=invalid_json`, `finish_reason=stop`,
  `visible_chars=322`, latency about 73s.

This means Kimi can be reconsidered for `candidate_json` routing only after the
normal route-safety gates, while MiniMax M3 should not be promoted from this
probe evidence. The MiniMax M3 failure was not the known recoverable legacy array
shape; it was invalid JSON under the bounded probe.

## ALI-184 provider-enforced structured-output A/B — 2026-06-10

ALI-184 tested the operator hypothesis that prompt-only JSON adherence measures a
model's formatting cognition as well as task quality, and that provider-enforced
`response_format` modes can improve consistency by moving structure enforcement
to the API endpoint.

### Implementation

The control-plane LLM test endpoint now supports these bounded modes for
`candidate_json` probes without mutating production routes:

- `prompt_only` / no `structured_output_mode`: prompt asks for JSON only.
- `json_object`: sends `response_format={"type":"json_object"}`.
- `json_schema`: sends strict JSON Schema with `candidates` and `maxItems: 1`.

The probe result and persisted health event now include deterministic candidate
completeness fields:

- `candidate_count`
- `candidate_title_complete`
- `candidate_rationale_complete`

ALI-184 also fixed a validator strictness bug found by the live matrix: the
`candidate_json` schema declares `maxItems: 1`, but the old in-repo
`schema_ok` check accepted any `len(candidates) >= 1`. The validator now requires
exactly one candidate for strict schema success. Extra candidates are valid JSON
but `schema_ok=false` / `malformed_kind=schema_mismatch`.

### Repeatable harness

`scripts/compare_structured_output_modes.py` calls the existing authenticated
`/control/api/settings/llm/test` endpoint and reports a no-mutation matrix across
prompt-only, JSON object, and strict JSON Schema modes. It records per-mode rates
for valid JSON, schema success, invalid JSON, recoverable shape, complete
candidate fields, and latency. The script intentionally does not import settings
write or queue/dispatch mutation surfaces.

### Live bounded matrix

Deployed live on `enoch-core` as described by the
[current runtime snapshot](current-runtime-snapshot.md), and run against
OpenRouter models `moonshotai/kimi-k2.6` and `minimax/minimax-m3`:

| Mode | Attempts | Valid JSON rate | Schema OK rate | Complete candidate rate | Invalid JSON | Avg latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| prompt-only | 2 | 0.50 | 0.50 | 0.50 | 1 | 7.49s |
| json_object | 2 | 1.00 | 1.00 | 1.00 | 0 | 4.93s |
| json_schema | 2 | 1.00 | 1.00 | 1.00 | 0 | 9.17s |

Model-level observations:

- Kimi passed all three modes in this small matrix.
- MiniMax M3 failed prompt-only with prose asking for more topic context
  (`valid_json=false`, `malformed_kind=invalid_json`, `visible_chars=210`) but
  passed both provider-enforced modes.
- In an earlier same-session pre-strictness run, MiniMax prompt-only returned
  three candidate objects. That exposed the old `schema_ok` bug above: extra
  candidates must not be counted as strict contract success when the schema says
  `maxItems: 1`.

### Current conclusion

Provider-enforced structured output is materially promising for Enoch model-route
probes. The first live matrix supports the hypothesis: endpoint-enforced modes
removed MiniMax M3's prompt-only formatting/prose failure while preserving bounded
visible output and complete candidate fields.

This is not yet permission to promote MiniMax M3 or mutate production routes. The
next production-safe step is to run a larger repeated matrix on representative
workflow prompts, then wire provider capability detection and per-workflow route
policy so JSON Schema/object modes are used only where the provider/model has
contract proof.
