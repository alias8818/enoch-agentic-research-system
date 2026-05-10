# Configuration reference

Primary config is a JSON file loaded from `ENOCH_CONFIG`.

## Required fields

| Field | Purpose |
|---|---|
| `control_api_bearer_token` | Authenticates dashboard, control API, worker dispatch, and callback calls. |
| `completion_callback_url` | URL called when a worker-gated run is complete. |
| `completion_callback_token` | Bearer token used for completion callback delivery. |
| `state_dir` | Local durable service state directory. |
| `project_root` | Root for project workspaces and paper artifacts. |
| `dispatch_script_path` | Script used by the control plane to launch agent runs. |

## Worker fields

| Field | Purpose |
|---|---|
| `worker_wake_gate_url` | Base URL for the worker-gate API. The field name is retained for compatibility. |
| `worker_wake_gate_bearer_token` | Bearer token for worker API checks and dispatch. |
| `paper_evidence_sync_enabled` | Enables evidence sync before rewriting paper artifacts. |
| `paper_evidence_sync_ssh_host` | Optional SSH target for fallback evidence sync. |
| `paper_evidence_sync_remote_root` | Worker project root used by fallback evidence sync. |

## Pushover alert fields

| Field | Purpose |
|---|---|
| `pushover_alerts_enabled` | Enables queue hang/stoppage notifications. |
| `pushover_app_token` | Pushover application token. |
| `pushover_user_key` | Pushover user/group key. |
| `pushover_api_url` | Pushover API endpoint. Defaults to the public messages endpoint. |
| `queue_alert_cooldown_sec` | Minimum time between duplicate alerts. |
| `queue_alert_hang_after_sec` | Active-run age threshold before hang alerts are considered. |
| `queue_pump_enabled` | Enables the timer-driven queue pump that dispatches queued projects when the lane is safe. |
| `queue_pump_followup_launch_enabled` | Optional flag for letting the queue pump dry-run and launch one bounded follow-up investigation when the lane is safe and no queued candidate exists; defaults off. |
| `queue_pump_paper_draft_enabled` | Optional compatibility flag for drafting/rewrite-kicking one eligible paper before dispatch; defaults off so execution-only queues are not starved by paper production. |

## Route observability fields

These fields are for private operator diagnostics. Keep them disabled by default unless collecting a memory or latency baseline.

| Field | Purpose |
|---|---|
| `route_observability_enabled` | Enables lightweight per-route timing, response-size, and RSS observations. Defaults off. |
| `route_observability_log_path` | Optional JSONL path for route observations. Defaults to `route_observations.jsonl` under `state_dir` when observability is enabled. |
| `route_observability_slow_ms` | Marks route observations as slow at or above this duration. |
| `route_observability_memory_warn_rss_mib` | Marks observations when current RSS exceeds this threshold. `0` disables the memory warning flag. |

The middleware does not record request bodies, response bodies, query strings, or bearer tokens. Use `scripts/dashboard_memory_smoke.py` to collect repeatable endpoint timing and server RSS-header evidence during dashboard redesign work.

## Paper writer fields

| Field | Purpose |
|---|---|
| `paper_writer_provider` | `deterministic` or `synthetic.new`. |
| `paper_writer_base_url` | OpenAI-compatible provider base URL. |
| `paper_writer_model` | Model identifier. |
| `paper_writer_api_key` | Provider API key. Do not commit. |
| `paper_writer_timeout_sec` | Provider request timeout. |
| `paper_writer_temperature` | Generation temperature. |
| `paper_writer_max_tokens` | Maximum output tokens. |
| `paper_writer_fallback_enabled` | Falls back to deterministic template if provider fails. |

## Deprecated compatibility aliases

Early private prototypes used callback fields named after a workflow tool. The public config should use `completion_callback_*`. The aliases are still accepted for old local configs but should not appear in new examples.

## Local Postgres idea intake

New deployments should use the control-plane ideas API rather than Notion sync. The current production runtime stores the ledgers in local Postgres on `enoch-core`; older `supabase_*` setting names remain compatibility names for the Postgres/Supabase adapter layer and migration tooling.

```json
{
  "control_plane_store_backend": "supabase",
  "enoch_core_store_backend": "control_plane",
  "supabase_database_url": "set-from-root-only-env",
  "legacy_notion_api_enabled": false
}
```

`enoch_core_store_backend` defaults to `control_plane`, so `/enoch-core/*` shadow/proposal snapshots follow the control-plane backend: SQLite in local development configs and the configured Postgres adapter in production. Pin it to `sqlite` only for isolated tests.

`legacy_notion_api_enabled` defaults to `false`. Leave it disabled unless you are deliberately running a one-off historical compatibility import in a quarantined environment. Live Notion tokens, database IDs, and sync timers are not part of the supported runtime path.
