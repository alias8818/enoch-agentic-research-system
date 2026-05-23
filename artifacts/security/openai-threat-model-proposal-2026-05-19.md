# Enoch threat model proposal and review notes

Date: 2026-05-19
Repository: `alias8818/enoch-agentic-research-system`
Prepared for: Codex Security threat model feedback

## Short verdict

The generated threat model is directionally accurate. It correctly identifies Enoch as a private, operator-administered FastAPI control plane plus worker gate, not a public multi-tenant SaaS. It also correctly centers the highest-risk boundaries: bearer-token auth, worker dispatch, filesystem/evidence artifacts, callback state, release/publication integrity, provider APIs, and the worker host running high-agency Codex jobs.

The main improvements I would make are:

1. Treat **publication/evidence integrity** as a first-class security asset, not only an operational correctness issue.
2. Separate **control-plane trust** from **worker trust** more sharply. The worker is trusted to execute, but its artifacts and callbacks still need deterministic validation.
3. Clarify that **LLM/provider output is adversarial input** even when produced by paid/provider infrastructure.
4. Mention the current local-Postgres/native-Codex topology and avoid stale OMX/Supabase-as-runtime assumptions.
5. Add an explicit invariant: no LLM interpretation becomes system truth unless enforced later by a deterministic test, schema, validator, or gate.
6. Add release/public-count drift and corpus-publication overclaim as modeled risks, because this project has a public trust surface.

## Specific critique of the provided model

### Accurate / keep

- Correctly states that this is a private operator tool, not public SaaS.
- Correctly identifies the bearer token as the primary authorization boundary.
- Correctly elevates worker dispatch and Codex execution as an intended high-agency/RCE-like capability.
- Correctly calls out path traversal, command injection, evidence poisoning, callback poisoning, SQL injection, SSRF, token leakage, XSS, and publication leakage.
- Correctly calibrates many authenticated issues as lower severity than they would be in a public multi-tenant product, while still treating auth bypass as critical.

### Needs tightening

- “Generated research is reviewed before public release” should be softened. The intended system direction is agentic automation. The security invariant should be positive-gated, evidence-backed, deterministic-publication checks, not human review.
- “A compromised worker can poison evidence because the worker is trusted” is true, but incomplete. The worker is trusted to run jobs, but worker output must still be treated as untrusted evidence until validated by schema, path, freshness, and publication gates.
- “Supabase migrations/RLS” should be described as historical/compatibility unless discussing migration tooling. Current runtime authority is local Postgres/control-plane storage on `enoch-core`.
- Dashboard token query parameters should be marked as a risk to phase out or restrict to local/operator-only use.
- SSRF should mention the authenticated operator-token risk explicitly: anyone with the control token can already do powerful things, but SSRF can expand blast radius to internal metadata/services.
- The paper pipeline needs stronger wording: private/unproven evidence publication is a security/trust failure, not just a bad paper.

## Proposed revised threat model

### 1. System overview

Enoch is a private, operator-administered control plane for agentic AI research. It ingests research ideas, maintains queue/run/decision/paper/corpus ledgers, dispatches native Codex jobs to a worker machine, receives worker callbacks, synchronizes evidence artifacts, and may draft, finalize, and publish research artifacts when strict gates pass.

Current production topology is:

- `enoch-core`: FastAPI control plane, dashboard/API, automation timers, paper/corpus tooling, local Postgres/control-plane storage.
- GB10 worker: native Codex worker gate that executes project prompts and writes `.enoch/project_decision.json` plus evidence artifacts.
- Public release/corpus surfaces: generated papers, release metadata, public counts, corpus import ledger, website/social/repo metadata.

This is not a public multi-tenant SaaS. There is no fine-grained RBAC. The control-plane bearer token is effectively operator authority. Severity should be calibrated around whether an attacker can obtain operator power, escape configured roots, execute commands, poison state/evidence, leak secrets/private research, or cause public release of unsupported/private artifacts.

### 2. Primary assets

- Control-plane bearer token.
- Worker-gate token and callback token.
- Provider/API keys and exe.dev integration credentials.
- Local Postgres credentials and database contents.
- Queue, run, decision, paper, and corpus ledgers.
- Project prompts, generated artifacts, logs, metrics, and unpublished evidence.
- Worker host execution capability, including Codex runs with broad project-workspace permissions.
- Public corpus/release metadata and counts.
- Evidence bundles, claim ledgers, paper manifests, and finalization packages.
- Operator trust and public trust in published artifacts.

### 3. Trust boundaries

#### Network/API boundary

Unauthenticated callers should learn at most service liveness from intentionally public health/shell endpoints. All state-changing or data-bearing control APIs must require the bearer token.

Relevant surfaces include:

- `/control/*`
- `/enoch-core/*`
- `/dashboard/api*`
- `/prepare-project`
- `/dispatch`
- `/project-paper/*`
- `/control/api/worker-callback`

#### Worker execution boundary

Dispatching a project intentionally gives Codex high agency inside a project workspace. That is expected behavior, but only authorized, admitted, and single-lane-controlled work should reach this boundary. Queue/project fields must not become shell syntax, filesystem escape paths, or unsafe worker paths.

#### Filesystem/artifact boundary

Project files must stay under configured `project_root`. Runtime state must stay under configured `state_dir`. Evidence sync and paper artifact writes must fail closed on path traversal, symlinks, uninspectable files, oversized payloads, stale evidence, malformed manifests, or missing required evidence.

#### Callback/state boundary

Worker callbacks are authenticated but still untrusted as data. They must be idempotent, tied to the intended run/project, resistant to stale replay, and unable to mark unrelated runs complete or paper-ready.

#### LLM/provider boundary

LLM/provider output is adversarial input. Generated candidates, review decisions, prompts, and project artifacts must not become system truth without deterministic enforcement. Provider quota/budget checks should fail closed before spend.

#### Publication/release boundary

Publication is a public trust boundary. A paper, corpus import, public count, or release claim must be backed by deterministic gates and evidence. No paper should be written or published unless the run is independently positive/useful-signal eligible and the evidence bundle/claim ledger is complete.

### 4. Attacker-controlled inputs

- HTTP JSON bodies, query parameters, and headers.
- Bearer tokens if leaked.
- Worker callback payloads.
- Worker HTTP responses and remote evidence tarballs.
- Codex/LLM-generated `.enoch/project_decision.json`, logs, metrics, papers, manifests, and other artifacts.
- Imported idea/source rows and research candidates.
- Provider model responses.
- Public corpus/release metadata when consumed by validators.
- Local script arguments in developer/release workflows.

### 5. Operator-controlled inputs

- `ENOCH_CONFIG`, environment variables, and systemd units.
- `project_root`, `state_dir`, `dispatch_script_path`.
- Worker/callback/provider URLs.
- SSH evidence-sync host/root.
- API keys, local Postgres URL, provider credentials, and exe.dev integration settings.
- Automation limits, allowed models, and live-dispatch flags.

Operator-controlled SSRF is mostly deployment policy. Authenticated API SSRF still matters because bearer-token compromise should not automatically expand to arbitrary internal network access.

### 6. Core invariants

1. No unauthenticated caller can mutate queue, run, decision, paper, corpus, or release state.
2. No LLM/provider/worker interpretation becomes durable system truth unless a deterministic schema, validator, test, or gate enforces it later.
3. Dispatch executes only one intended queued/admitted project at a time unless explicitly configured otherwise.
4. Project and artifact paths never escape configured roots.
5. Worker callbacks are authenticated, idempotent, run-bound, and stale-replay resistant.
6. Evidence sync never reuses stale evidence when current evidence is empty/missing.
7. Paper writing is positive/useful-signal gated and evidence gated.
8. Public corpus imports and public counts match deterministic ledgers.
9. Secrets are never committed, printed in argv/logs, embedded in public artifacts, or returned in API errors.
10. Provider spend is bounded by quota checks and automation caps.

### 7. High-risk attacker stories

#### Auth bypass to operator control

An internet or LAN attacker bypasses bearer-token checks or obtains a token from logs, query strings, public artifacts, browser history, or command output. Impact is full operator-equivalent control: dispatch, artifact access, state mutation, and possible worker execution.

Mitigations:

- Require strong bearer tokens for all state/data APIs.
- Prefer Authorization headers over token query parameters.
- Redact tokens from logs, argv, public release files, and errors.
- Validate release artifacts for secret patterns.

#### Dispatch command/path injection

A malicious idea row or queued project field reaches shell execution, worker path construction, or SSH evidence sync. Impact can be command execution, project-root escape, or worker compromise.

Mitigations:

- Slug/bound project and candidate IDs.
- Use argv arrays, not shell strings.
- Refuse project-local Codex binaries.
- Keep dispatch scripts deterministic and test shell assumptions.

#### Evidence poisoning or stale evidence reuse

A worker returns malformed, empty, stale, symlinked, oversized, or partial evidence, and the paper pipeline still drafts or publishes. Impact is unsupported public claims or private/unfavorable evidence omission.

Mitigations:

- Fail closed on unreadable/uninspectable evidence.
- Delete stale local targets when current sync returns empty content.
- Restrict public evidence bundles to allowed file classes.
- Require claim ledgers/evidence manifests before finalization.

#### Callback state poisoning

A worker or bearer-token holder submits callbacks that mark unrelated runs complete, bypass paper gates, or replay stale state. Impact is queue corruption, false positives, or unintended publication.

Mitigations:

- Idempotency keys with payload identity checks.
- Run/project binding.
- Terminal-state precedence rules.
- Generic external errors with detailed internal audit logs.

#### Public release overclaim

Release tooling publishes incorrect counts, stale ledgers, private paths, missing strict-audit context, or unsupported paper claims. Impact is public trust damage and possible secret leakage.

Mitigations:

- Public release validator checks counts, strict audit context, corpus ledger, and secret patterns.
- Bundle preflight runs before cross-repo pushes.
- Public metadata updates should be generated from canonical ledgers, not hand-edited.

### 8. Severity calibration

#### Critical

- Unauthenticated mutation of control-plane state.
- Auth bypass for dispatch, callback, paper, or release APIs.
- Arbitrary command execution from attacker-controlled queue/project fields.
- Arbitrary file read/write outside configured roots exposing secrets or enabling code execution.
- Production credential leakage in public artifacts, logs, or committed files.
- Automated public release of private artifacts at scale.

#### High

- Authenticated SQL injection that alters ledgers or extracts private artifacts.
- SSRF to sensitive internal services from authenticated APIs.
- Dashboard/artifact XSS that steals bearer tokens or mutates queue state.
- Callback bugs that mark unrelated runs complete or bypass paper gates.
- DoS that wedges the single active worker lane or corrupts durable state.

#### Medium

- Token-in-query leakage risk.
- Excessive error detail to authenticated callers.
- Stale/replay bugs requiring operator repair but not bypassing gates.
- Provider prompt injection that degrades research quality without escaping deterministic gates.
- Missing rate limits when strong bearer tokens are still required.

#### Low

- Unauthenticated health metadata.
- Timing differences in bearer comparison with high-entropy tokens.
- Developer-local script issues requiring trusted local execution.
- Cosmetic dashboard escaping issues without token/data impact.
- Optional observability/alerting failures that do not affect auth, dispatch, or publication.

### 9. Recommended model additions for Codex Security

The generated model is good, but future scans should explicitly prioritize these classes:

1. Evidence freshness and fail-closed publication behavior.
2. Callback idempotency and run/project binding.
3. Public release/corpus overclaim and count drift.
4. Provider/LLM output becoming durable state without deterministic validation.
5. Secret leakage through argv, logs, public artifacts, and query parameters.
6. Stale references to removed OMX/Supabase runtime paths.
7. Worker-dispatch path/command injection from admitted candidates.
8. Authenticated SSRF to internal services.
9. Dashboard XSS that can steal or replay operator bearer tokens.
10. Automation loops that spend provider budget or drain work without bounded caps.
