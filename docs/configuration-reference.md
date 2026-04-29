# Configuration reference

Primary config is a JSON file loaded from `OMX_WAKE_GATE_CONFIG`.

## Required fields

| Field | Purpose |
|---|---|
| `omx_inbound_bearer_token` | Authenticates dashboard/control API calls and OMX event posts. |
| `completion_callback_url` | URL called when a wake-gated run is complete. |
| `completion_callback_token` | Bearer token used for completion callback delivery. |
| `state_dir` | Local durable service state directory. |
| `project_root` | Root for project workspaces and paper artifacts. |
| `dispatch_script_path` | Script used by the control plane to launch agent runs. |

## Worker fields

| Field | Purpose |
|---|---|
| `worker_wake_gate_url` | Base URL for the worker wake-gate API. |
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
