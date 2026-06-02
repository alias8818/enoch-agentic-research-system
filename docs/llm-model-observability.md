# LLM model observability

Status: active ALI-104 first-slice contract.

Dashboard V2 treats model health as operator evidence, not as a generic provider
explorer. A model can answer the endpoint smoke test and still be unsafe for
structured automation if it returns no visible text, exhausts output budget, or
fails a format/schema probe.

## Health vocabulary

| Dimension | Meaning | Example operator action |
| --- | --- | --- |
| `endpoint_health` | Provider/model can return a bounded response. | Fix auth, base URL, model ID, rate limit, or provider outage. |
| `visible_output_health` | The latest successful response produced visible text. | Increase output budget or disable the model for visible-output workflows. |
| `reasoning_budget_health` | The latest response did not stop because of output length. | Increase `max_tokens` or move strict-output workflows away from the model. |
| `format_health` | Measured structured-output probes satisfy JSON/schema contracts. | Keep endpoint health separate from automation usefulness and inspect malformed output. |
| `workflow_health` | Workflow-specific probes satisfy the workflow prompt contract. | Keep the model out of that workflow pool until the contract passes. |

## Event fields

`settings.llm.model_test` events may include these redacted, bounded fields:

- `finish_reason`
- `visible_chars`
- `response_preview_redacted`
- `input_tokens`
- `output_tokens`
- `reasoning_tokens`
- `workflow_id`
- `prompt_contract`
- `valid_json`
- `schema_ok`
- `malformed_kind`
- `sanitized_or_refusal_detected`

Raw provider responses and provider secrets must not be stored or shown in the
dashboard. Previews are capped and scrubbed before event persistence.

## Read model

`/control/api/v1/observability/llm-models` joins configured enabled models with
recent `settings.llm.model_test` events and returns:

- endpoint issue count;
- structural/usefulness issue count;
- the health vocabulary above for each model;
- bounded latest preview evidence;
- a model-level `operator_action`.

The existing `/control/api/settings/llm/health` remains available for settings
workflows. Dashboard V2 uses the v1 Observability endpoint so model health lives
with route, memory, and support signals instead of creating another page.

## Deterministic invariants

- Endpoint health must not imply automation usefulness.
- Successful responses with `visible_chars == 0` are structurally unhealthy.
- `finish_reason == "length"` is a reasoning/output-budget warning.
- Format/schema failures can degrade `format_health` while `endpoint_health`
  remains `healthy`.
- Raw JSON and redacted previews remain inside collapsed dashboard details.
