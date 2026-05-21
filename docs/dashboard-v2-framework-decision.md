# Dashboard V2 framework decision

Status: **accepted** (2026-05-21).

```yaml
decision: stay-with-vite
revisit_when:
  - public-seo-pages-required
  - server-rendered-auth-required
  - separate-dashboard-host-required
```

## Symptom / risk

Parking-lot work could stall on an open-ended “should we migrate to Next.js?” question while operator UX gaps remain. Without a recorded decision, parallel agents may assume a framework migration is imminent and over-build abstractions or defer Vite-native improvements.

## Invariant

> Dashboard V2 remains a Vite-built operator SPA whose production bundle is committed under `enoch_control_plane/control_plane/dashboard_v2/` and served by the control plane at `/control/dashboard-v2`, until an explicit revisit trigger in this document is met.

## Context

- **Audience:** internal operators on the reference control VM; not a public marketing site.
- **Data:** bounded read-model JSON from `/control/api/v1/*` and legacy `/control/api/status`; backend read models are truth.
- **Auth:** operator bearer token in browser storage; no cookie/session SSR requirement.
- **Deploy:** static assets rsync with the control-plane package ([`dashboard-v2-deploy.md`](dashboard-v2-deploy.md)); CI hash-validates committed bundles ([`dashboard-v2-asset-clca.md`](dashboard-v2-asset-clca.md)).
- **Tests:** Vitest DOM guards, Playwright smoke, Python smoke script — all wired in CI.

## Evaluation criteria

| Criterion | Vite SPA (current) | Next.js |
| --- | --- | --- |
| Operator question focus | Matches: thin client over read models | Same possible, no operator gain |
| SSR / SEO | Not required | Adds build/deploy complexity without benefit |
| Hosting | Served from FastAPI static mount | Needs Node runtime or export pipeline separate from control plane |
| Asset model | Committed `dashboard_v2/` hashes in PR CI | Would require new commit/validate contract |
| CI cost | `npm test`, typecheck, lint, e2e, asset pairing | New toolchain + likely slower PRs |
| Team surface | React 19 + Vite 7 already in repo | Migration churn across routes/tests/assets |
| Security boundary | Token-gated API; static shell has no secrets | Same; SSR does not remove token-in-browser pattern |

## Decision

**Stay with Vite.** A Next.js migration is **not justified** for Dashboard V2 as of 2026-05-21.

Rationale in one sentence: the dashboard is a hash-guarded static operator console mounted inside the control plane; operator value comes from read-model semantics and UX, not from a full-stack React framework.

## What to do instead of a framework migration

1. **Component system (Vite-native):** small shared primitives and layout patterns under `dashboard/src/components/` — see parking-lot follow-up in [`dashboard-v2-todo-2026-05-21.md`](dashboard-v2-todo-2026-05-21.md).
2. **DTO alignment:** optional schema extraction from backend read models — separate parking-lot item.
3. **Operator PRs:** hero/movement/lane/backlog semantics per [`dashboard-v2-cursor-instructions.md`](dashboard-v2-cursor-instructions.md).

## Revisit triggers (explicit)

Re-open this decision only if **all** of the following are false and a new requirement appears:

- Dashboard remains operator-only behind control-plane auth.
- Production continues to ship as committed static assets beside FastAPI.
- No product requirement for SSR, ISR, or public SEO pages on the same app shell.

Examples that **would** justify reconsideration:

- A public, indexed documentation/marketing site must share the same codebase and routing as the operator console.
- Auth policy requires server-rendered session gates before any client bundle loads.
- Dashboard must run on a separate host/runtime that cannot serve static files from the control-plane package.

## Verification

- Deterministic doc guard: [`tests/test_dashboard_v2_framework_decision.py`](../tests/test_dashboard_v2_framework_decision.py)
- Linked from [`dashboard-redesign-plan.md`](dashboard-redesign-plan.md) follow-up slices.
