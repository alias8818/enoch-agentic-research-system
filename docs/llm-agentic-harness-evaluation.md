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
