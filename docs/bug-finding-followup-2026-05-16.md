# Bug-finding follow-up - 2026-05-16

Follow-up after adding Hypothesis, Schemathesis, Pyright, Semgrep, and the
agentic property-based testing harness.

## Semgrep triage

Initial report-only Semgrep findings were all from `enoch-silent-broad-exception`.

| Location | Triage | Resolution |
| --- | --- | --- |
| `enoch_control_plane/callback_outbox.py` pending metadata merge | Real bug / weak observability. A corrupt pending file caused metadata preservation to silently fall through. | `write_pending` now records a `last_error` explaining the unreadable prior pending metadata. Regression added in `tests/test_callback_outbox.py`. |
| `enoch_control_plane/telemetry.py` NVML memory read | Expected platform behavior on UMA/iGPU systems, but the rule usefully forced a clearer fallback. | The exception path now annotates `memory_source` with the unavailable NVML memory exception type while retaining UMA meminfo as the operator-visible fallback. |
| `enoch_control_plane/telemetry.py` NVML shutdown | Expected best-effort shutdown behavior. | The exception path no longer silently passes; it marks NVML not ready and keeps the exception object local for debugger visibility without failing service shutdown. |

After the patch, `uv run semgrep --config .semgrep/enoch-guardrails.yml --metrics=off --no-git-ignore .` reports zero findings.

## Pyright triage

Pyright remains report-only. The current surface is useful but not clean enough
to block CI. Latest total: 269 diagnostics.

Top bug-relevant classes:

1. `reportAttributeAccessIssue` - 86 diagnostics. Mostly store union/protocol
   drift where read-only and writable stores expose different methods.
2. `reportArgumentType` - 76 diagnostics. Mostly dynamic row/model coercion into
   `Literal` fields and pydantic models.
3. `reportOptionalMemberAccess` - 54 diagnostics. Mostly nullable row/query/API
   payload handling that should be narrowed before access.
4. `reportCallIssue` - 26 diagnostics. Mostly stale or divergent method
   signatures, including API/store calls.
5. `reportIndexIssue` / `reportOptionalSubscript` - 12 combined diagnostics.
   Mostly dynamic JSON/DB rows typed as `object` or possibly `None`.

Small bounded fix made: `_is_followup_candidate` now explicitly returns `bool`
rather than relying on Python `and` returning the last truthy string. This removed
the corresponding `read_models.py` return-type diagnostic and makes the read
model contract explicit.

## Agentic-PBT prompt

Generated a high-risk prompt for `enoch_control_plane/control_plane/paper_writer.py`:

- `artifacts/agentic-pbt/paper-writer-prompt.md`

No LLM proposal JSON was present locally, so no generated tests were executed in
this pass. Next manual/LLM step: feed that prompt to the configured research LLM,
save the returned JSON as `artifacts/agentic-pbt/paper-writer-proposals.json`,
and execute it with:

```bash
uv run python scripts/agentic_property_testing.py \
  --target enoch_control_plane/control_plane/paper_writer.py \
  --proposal-file artifacts/agentic-pbt/paper-writer-proposals.json \
  --execute-proposals
```

Any non-zero run is a candidate counterexample only; validate it before patching.
