# Historical migration notes

These documents describe the earlier n8n-era migration path and shadow-protocol experiments that informed the current system design.

They are retained as engineering history only. The release project is **not** an n8n workflow package and does not include OpenClaw workflow configuration.

Current workflow authority lives in the LangGraph-era control plane, wake gate, worker preflight, queue/status APIs, evidence synchronization, and paper artifact pipeline described in the main README and `docs/system-workflow.md`.

Historical files in this directory include:

- `langgraph_hard_cutover_mvp.md` — first hard-cutover notes.
- `enoch_core_shadow_adr.md` — early shadow-protocol ADR.
- `enoch_core_protocol.md` — early shadow protocol API notes.
- `n8n_migration_notes.md` — migration notes from the earlier automation stack.
- `enoch_core_failure_playbook.md` — early failure-mode notes.
