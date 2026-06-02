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

Long-haul readiness consumes this same read model. A configured model with an
unhealthy endpoint, degraded format health, empty visible output, or
length-limited output is an unattended-mode blocker until the model recovers,
is disabled, or is removed from the workflows that require structured output.

The existing `/control/api/settings/llm/health` remains available for settings
workflows. Dashboard V2 uses the v1 Observability endpoint so model health lives
with route, memory, and support signals instead of creating another page.

## Format probes

The bounded provider/model test endpoint supports optional format probes:

```json
{
  "provider_id": "openrouter",
  "model_id": "openrouter/owl-alpha",
  "prompt_contract": "strict_json"
}
```

Supported first-slice contracts:

| Contract | Expected output | Failure examples |
| --- | --- | --- |
| `strict_json` | A compact JSON object matching `{"ok": true, "items": [1, 2]}` with no Markdown wrapper. | prose, fenced JSON, invalid JSON, schema mismatch, empty output |
| `markdown_fenced_json` | A Markdown heading plus a `json` fenced block containing the same probe object. | missing fence, invalid fenced JSON, schema mismatch |
| `candidate_json` | A compact JSON array with at least one candidate object containing `title` and `rationale`. | object instead of array, missing fields, invalid JSON |

When `prompt_contract` is set, the endpoint records the event as
`source=format_probe` and persists the deterministic parser result in
`valid_json`, `schema_ok`, and `malformed_kind`.

The research autopilot can run the same probes as a bounded sidecar when
explicitly enabled:

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `ENOCH_LLM_MODEL_FORMAT_PROBES_ENABLED` | `0` | Opt-in switch for scheduled format probes. |
| `ENOCH_LLM_MODEL_FORMAT_PROBE_LIMIT` | `2` | Maximum probe requests per finalized autopilot tick. |
| `ENOCH_LLM_MODEL_FORMAT_PROBE_MIN_INTERVAL_SECONDS` | `86400` | Cooldown before re-probing a model with recent format evidence. |
| `ENOCH_LLM_MODEL_FORMAT_PROBE_CONTRACTS` | `strict_json,markdown_fenced_json,candidate_json` | Contracts eligible for scheduled probing. |
| `ENOCH_LLM_MODEL_FORMAT_PROBE_TIMEOUT_SECONDS` | `45` | Per-request timeout for scheduled probe calls. |

The sidecar skips endpoint-unhealthy models and probes only stale, unmeasured, or
cooldown-expired degraded format rows. This keeps endpoint recovery separate from
format usefulness checks and avoids repeated provider calls on every tick.

## Deterministic invariants

- Endpoint health must not imply automation usefulness.
- Successful responses with `visible_chars == 0` are structurally unhealthy.
- `finish_reason == "length"` is a reasoning/output-budget warning.
- Format/schema failures can degrade `format_health` while `endpoint_health`
  remains `healthy`.
- Raw JSON and redacted previews remain inside collapsed dashboard details.
