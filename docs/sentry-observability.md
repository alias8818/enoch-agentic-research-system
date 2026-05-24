# Sentry observability

Enoch can report backend exceptions to Sentry, but this integration is intentionally narrow. Sentry is for operational failures, not research content.

## Current project

- Organization: `sentry`
- Project slug: `enoch-control-plane`
- Platform: Python / FastAPI
- Runtime env file on hosts: `/etc/enoch-control-plane/sentry.env`
- Local operator copy: `~/.config/enoch-sentry/env`

Do not commit DSNs, auth tokens, or generated env files.

## Runtime configuration

Sentry is disabled unless `SENTRY_DSN` is set in the service environment.
The checked-in control-plane systemd unit loads this optional file:

```ini
EnvironmentFile=-/etc/enoch-control-plane/sentry.env
```

The leading `-` is intentional: hosts without Sentry configuration continue to
start normally and report `sentry_configured=false` on the observability health
endpoint.

Supported environment variables:

| Variable | Purpose |
| --- | --- |
| `SENTRY_DSN` | Enables Sentry SDK exception capture. Keep in host env only. |
| `ENOCH_SENTRY_ENV` | Sentry environment label, for example `production` or `dev`. |
| `ENOCH_SENTRY_RELEASE` | Release identifier. Prefer the deployed git SHA. |
| `ENOCH_SENTRY_SERVER_NAME` | Host label, for example `enoch-core`, `gb10`, or `cpu-worker-1`. |
| `ENOCH_SENTRY_TRACES_SAMPLE_RATE` | Low trace sample rate. Default is `0.02`; bounded to `0.0..1.0`. |

## Privacy guardrails

The control plane installs a Sentry `before_send` scrubber. It filters:

- request bodies;
- query strings;
- cookies;
- authorization and secret-like headers;
- keys containing token, bearer, password, secret, credential, auth, API key, or DSN;
- prompt, artifact, evidence, paper, draft, claim, ledger, content, body, payload, project decision, and run notes fields.

Allowed operational tags/extras stay intentionally small: component, lane, operation, project/run/paper IDs, route/status/error type, request ID, and machine target.

## Smoke test

After deployment, trigger a safe synthetic exception:

```bash
TOKEN="$(sudo jq -r '.control_api_bearer_token' /etc/enoch-control-plane/config.json)"
curl -fsS \
  -H "Authorization: Bearer $TOKEN" \
  -X POST \
  http://127.0.0.1:8787/control/api/v1/observability/sentry-smoke
```

Expected response shape:

```json
{
  "ok": true,
  "source": "control_api_v1_sentry_smoke",
  "sentry_enabled": true,
  "event_id": "..."
}
```

Then verify with the Sentry MCP or UI under `sentry/enoch-control-plane`.

## Dashboard

Dashboard V2 `#observability` shows whether Sentry is configured and active, plus the environment and release labels. It does not expose the DSN.
