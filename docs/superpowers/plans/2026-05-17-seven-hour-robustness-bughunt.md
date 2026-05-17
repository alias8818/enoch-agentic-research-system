# Seven-Hour Enoch Robustness Bug Hunt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Use superpowers:test-driven-development for every code change and superpowers:verification-before-completion before any completion claim. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Spend a full autonomous seven-hour session finding and fixing silent state drift, callback/evidence-sync gaps, false alerts, and fail-open behavior in the Enoch control plane without waiting for operator review.

**Architecture:** This is a reliability hardening pass, not a feature sprint. Work from the highest-risk boundaries outward: persistent store invariants, worker callback idempotency, evidence sync gates, paper-write gates, alert correctness, autopilot loops, and release/count validation. Every accepted change must have a failing regression/property test first, pass the full local test suite, be committed, pushed, and deployed only when the live lane is safe to restart.

**Tech Stack:** Python 3.14, FastAPI, local/Postgres-compatible control-plane store adapters, SQLite test store, Hypothesis property tests, pytest, ruff, Semgrep/custom rules where useful, systemd services on `enoch-core`, GB10 worker gate over Tailscale. Current topology reference: [`current-runtime-snapshot.md`](../current-runtime-snapshot.md).

---

## Operating rules for the seven-hour autonomous session

- Work in `/home/jeremy/Desktop/projects/enoch-release/enoch-agentic-research-system`.
- Do not wait for human review. If one task blocks for more than 20 minutes, document the blocker in the plan file, commit any useful test/artifact work if safe, and move to the next task.
- Do not pause the queue unless a live bug risks corrupting state or writing an evidence-free paper.
- Do not broad-drain or manually launch new work unless a task explicitly requires a dry-run or read-only live check.
- Keep commits small. Prefer one commit per fixed defect or test-harness expansion.
- Push every clean commit to `origin/main`.
- Deploy to `enoch-core` only after local full verification and only when either active work is `0` or the patch is safe enough to restart during active work. If active work is nonzero and the fix is not urgent, leave deployment notes instead of restarting.
- Never commit secrets. Before each commit, run a targeted secret/risky-file sweep for changed and untracked files.
- If generated artifacts are useful evidence, commit them under `artifacts/agentic-pbt/`; otherwise remove them before final status.
- At the end, leave the repo clean, pushed, and produce a concise final report with commits, tests, live status, deployed/not-deployed state, and remaining risks.

## Standard verification bundle

Run this bundle after each code-fix commit candidate unless the change is docs-only:

```bash
uv run ruff check .
uv run pytest -q
python3 scripts/validate_runtime_snapshot_links.py
git diff --check
```

Run this release validator before the final report and before any release-surface/count patch:

```bash
python3 scripts/validate_public_release.py \
  --system . \
  --corpus ../enoch-ai-research-corpus \
  --docs ../enoch-docs \
  --profile ../alias8818.github.io \
  --owner-profile ../alias8818 \
  --personal-site ../jeremyblankenship.dev \
  --generated-manifest /tmp/enoch-ecosystem.generated.json \
  --skip-github-metadata
```

Use the live readiness probe when checking `enoch-core`:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=8 enoch-core.exe.xyz 'TOKEN=$(sudo python3 - <<"PY"
import json
print(json.load(open("/etc/enoch-control-plane/config.json"))["control_api_bearer_token"])
PY
); curl -fsS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8787/control/api/v1/automation-readiness'
```

---

## Task 0: Session setup and live baseline

**Timebox:** 20 minutes

**Files:**
- Modify only if needed: `docs/superpowers/plans/2026-05-17-seven-hour-robustness-bughunt.md`
- Evidence/artifacts if useful: `artifacts/robustness/`

- [x] **Step 1: Confirm repo and branch state**

Run:

```bash
pwd
git status --short --branch
git log -5 --oneline
```

Expected: inside `enoch-agentic-research-system`, branch `main`, clean or only the active plan file.

- [x] **Step 2: Capture live control-plane state without mutating it**

Run the live readiness probe from the standard bundle. Also capture:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=8 enoch-core.exe.xyz \
  'systemctl is-active enoch-control-plane.service; systemctl is-active enoch-research-autopilot.timer; systemctl is-active enoch-corpus-import-autopilot.timer'
```

Expected: service active; timers active. Record active/queued counts and readiness status in the final report.

- [x] **Step 3: Run a fast local smoke baseline**

Run:

```bash
uv run ruff check .
uv run pytest -q tests/test_property_invariants.py tests/test_evidence_sync_paths.py tests/test_control_plane_store.py
```

Expected: pass. If this fails before edits, debug and fix the baseline first.

---

## Task 1: Store invariant property expansion

**Timebox:** 60 minutes

**Files:**
- Modify: `tests/test_property_invariants.py`
- Modify if a defect is found: `enoch_control_plane/control_plane/store.py`
- Modify if mirrored behavior exists: `enoch_control_plane/control_plane/supabase_store.py`

**Risk being hunted:** queue rows, run rows, and event rows silently disagree after repeated imports, callbacks, idempotent replays, or stale callbacks.

**Progress note:** Found and fixed active queue row drift from stale imports. Added callback idempotency replay coverage and active-row import preservation coverage. Full test suite passed with 474 tests.

- [x] **Step 1: Add a property for callback idempotency preserving queue state**

Add a Hypothesis test that imports a running queue row, calls `record_worker_callback()` twice with the same `idempotency_key`, and asserts:

```python
assert first_event_id == second_event_id
assert first_inserted is True
assert second_inserted is False
assert second_row == first_row
assert len(store.event_rows(entity_type="run", entity_id=run_id, limit=10)) == 1
```

Use generated safe `run_id`, `project_id`, and `event_type` values from a bounded enum: `session_started`, `wake_ready`, `session_finished_ready`, `gate_timeout`, `gate_error`, `question_pending`.

- [x] **Step 2: Run the new property and verify it fails or passes honestly**

Run:

```bash
uv run pytest -q tests/test_property_invariants.py::test_worker_callback_idempotency_replay_preserves_queue_state -vv
```

If it fails, keep the counterexample and fix the smallest root cause. If it passes, keep the test if it protects a real invariant.

- [x] **Step 3: Add a property for import snapshot not weakening active rows**

Add a property that starts with a running queue row with `current_run_id`, then imports a snapshot for the same `project_id` with older/weaker fields. Assert active fields are not accidentally blanked unless the import logic intentionally owns them. Target invariants:

```python
assert row["project_id"] == project_id
assert row["current_run_id"] in {current_run_id, imported_current_run_id}
assert row["status"] in VALID_QUEUE_STATUSES
assert row["next_action_hint"] != ""
```

If the existing contract intentionally lets imports overwrite, tighten the test to the actual intended contract after reading `import_snapshot()`.

- [x] **Step 4: Patch store adapters only if the tests reveal drift**

Patch `store.py` first. Mirror the same semantic guard in `supabase_store.py` if the method exists there. Do not invent new status values.

- [x] **Step 5: Verify and commit**

Run:

```bash
uv run ruff check .
uv run pytest -q tests/test_property_invariants.py tests/test_control_plane_store.py
```

Commit if changed:

```bash
git add enoch_control_plane/control_plane/store.py enoch_control_plane/control_plane/supabase_store.py tests/test_property_invariants.py
git commit -F /tmp/enoch-store-invariants-commit.txt
git push
```

Commit message subject if a bug was fixed: `fix: preserve queue invariants across callbacks`.

---

## Task 2: Evidence sync path and extraction hardening

**Timebox:** 75 minutes

**Files:**
- Modify: `tests/test_evidence_sync_paths.py`
- Modify: `tests/test_property_invariants.py`
- Modify if needed: `enoch_control_plane/control_plane/router.py`

**Risk being hunted:** SSH/tar fallback, worker HTTP reads, symlinks, path traversal, or partial syncs make the control plane think evidence is present when it is not trustworthy.

**Progress note:** Found and fixed SSH fallback fail-open behavior where a successful tar command reported `synced: true` even when required local paper evidence was absent. Added worker HTTP path escape coverage and evidence sync regressions. Full test suite passed with 477 tests.

- [x] **Step 1: Add property for worker HTTP returned paths staying under artifact root**

Patch `post_worker_json` in a test to return generated file paths including normal names, nested paths, `../escape`, absolute paths, Windows separators, and weird Unicode. Call `_sync_worker_http_evidence()`. Assert every written file resolves under `artifact_root` and no unsafe path is created outside it.

- [x] **Step 2: Add regression for HTTP partial sync truthfulness**

Create a test where HTTP returns only optional `results/smoke.json` and no `run_notes.md` or decision artifact. Assert `_sync_remote_project_evidence()` does not report `method == "worker_http"` with `synced == True` unless `_local_paper_evidence_present()` is actually true under the hardened gate.

- [x] **Step 3: Add regression for SSH tar extraction symlink edge**

Use a local tar stream fixture or patched `subprocess.Popen` double if practical. The target invariant is: after fallback extraction, `_sync_remote_project_evidence()` must compute `synced` from `_local_paper_evidence_present(artifact_root)`, not from tar return code alone. If current code returns `synced: True` solely on command success, fix it.

Expected patch shape if defective:

```python
local_present = _local_paper_evidence_present(artifact_root)
return {
    "enabled": True,
    "synced": local_present,
    "reason": "synced" if local_present else "synced_without_required_evidence",
    "method": "worker_http+ssh",
    "remote_dir": remote_dir,
    "local_evidence_present": local_present,
    "http_sync": http_sync,
}
```

- [x] **Step 4: Verify evidence sync tests**

Run:

```bash
uv run pytest -q tests/test_evidence_sync_paths.py tests/test_property_invariants.py
```

Expected: pass.

- [x] **Step 5: Commit and push**

Commit subject if a bug was fixed: `fix: require evidence presence after sync fallback`.

---


**Additional paper-writer URL hardening:** Applied the shared HTTP URL guard to the Synthetic/OpenAI-compatible paper writer endpoint. Added a regression proving an unsafe provider URL falls back deterministically without calling `urlopen`.

## Task 3: Paper-write gate fail-closed audit

**Timebox:** 60 minutes

**Files:**
- Modify: `tests/test_paper_artifacts.py` or create focused test file if existing tests do not fit
- Modify if needed: `enoch_control_plane/control_plane/router.py`
- Modify if needed: `enoch_control_plane/enoch_core/logic.py`

**Risk being hunted:** a paper is written for a negative, proxy-only, malformed, stale, or evidence-missing run.

**Progress note:** Added fail-closed paper gate coverage for legacy positive rows without evidence and proxy/useful-signal `finalize_positive` artifacts. Fixed the decision gate so useful-signal positives require explicit bounded-paper readiness. Full test suite passed with 479 tests.

- [x] **Step 1: Locate paper draft endpoints and gate functions**

Read the relevant sections around:

```bash
grep -RIn "draft-next\|rewrite-draft\|paper_draft_decision_gate\|_local_paper_evidence_present" enoch_control_plane tests | head -200
```

- [x] **Step 2: Add tests for no paper without evidence**

Create or extend a test that imports a `completed`/`wake_ready` queue item with `last_run_state=finalize_positive`, but with no local evidence. Call `/control/papers/draft-next` with `dry_run: false` and assert it returns blocked/noop/424 rather than writing a paper row.

- [x] **Step 3: Add tests for bounded paper-ready vs broad finalize-positive**

Use decision JSON variants:

```json
{"project_decision":"finalize_positive","research_outcome":"useful_signal","bounded_paper_ready":false}
```

and:

```json
{"project_decision":"finalize_positive","research_outcome":"positive","bounded_paper_ready":true,"claim_scope":"toy/local benchmark only"}
```

Assert the first does not write a paper unless policy explicitly allows useful-signal papers; assert the second can proceed only with evidence present.

- [x] **Step 4: Patch only to fail closed**

If ambiguity exists, choose no-paper/noop over paper generation. Do not weaken gates to increase positives.

- [x] **Step 5: Verify and commit**

Run:

```bash
uv run pytest -q tests/test_paper_artifacts.py tests/test_control_plane_router.py tests/test_evidence_sync_paths.py
```

Commit subject if changed: `fix: fail closed on paper draft evidence gates`.

---


**Additional alert URL hardening:** Applied the HTTP(S)-only URL guard to Pushover delivery. Added a regression proving a poisoned `pushover_api_url=file://...` is rejected before `urlopen` runs.

## Task 4: Queue alert false-positive and backpressure audit

**Timebox:** 60 minutes

**Files:**
- Modify: `deploy/enoch_queue_alert_check.py`
- Modify or add: tests around queue alert behavior, likely `tests/test_queue_alerts.py` or existing queue-alert test file
- Modify docs only if operator semantics change: `docs/operator-runbook.md`

**Risk being hunted:** alerts fire while the system is healthy, causing noise and eroding trust.

**Progress note:** Existing alert predicates already suppressed healthy active lanes and cooldown duplicates. Added a live non-dry-run regression proving healthy active work does not persist queue-alert events or send Pushover. No alert code patch was required. Full test suite passed with 480 tests.

- [x] **Step 1: Locate existing alert tests and alert event rules**

Run:

```bash
grep -RIn "Queue Alert\|Backpressure\|queue_alert\|enoch_queue_alert_check" deploy tests enoch_control_plane | head -240
```

- [x] **Step 2: Add a regression for active work not being an alert by itself**

Build the smallest fake API/read model used by `enoch_queue_alert_check.py`. Assert:

```python
active == 1
queued == 0
readiness == "ready"
needs_attention == 0
```

does not emit Pushover and does not append a `Queue Alert Detected` event.

- [x] **Step 3: Add a regression for backpressure cooldown/deduping**

Simulate repeated backpressure samples within `queue_alert_cooldown_sec`. Assert at most one alert is sent and subsequent samples produce non-alert telemetry only.

- [x] **Step 4: Patch the smallest alert predicate**

Healthy active work should be telemetry, not alert. Alert only when there is sustained blocked/attention/hang evidence or readiness is blocked for a real reason.

- [x] **Step 5: Verify and commit**

Run:

```bash
uv run pytest -q tests/*alert* tests/test_longhaul_readiness.py
```

If shell glob fails because no files match, use the exact discovered test files. Commit subject: `fix: suppress healthy queue alert noise`.

---


**Additional alert-noise fix:** Bucketed Research Facility backpressure event idempotency by active lane signature and one-hour cooldown. A normal long-running active lane no longer writes a fresh `research.run_cycle.backpressure` event on every timer tick for the same run. Added a regression that calls the live run-cycle twice under active-lane backpressure and verifies only one event row is inserted.

## Task 5: Research autopilot fail-safe and budget invariant audit

**Timebox:** 60 minutes

**Files:**
- Modify: `scripts/research_facility.py`
- Modify: `scripts/research_facility_llm_review.py`
- Modify: `scripts/research_provider_budget.py`
- Modify or add tests: `tests/test_research_autopilot.py`, `tests/test_research_facility*.py`

**Risk being hunted:** autopilot silently stops, spends provider budget incorrectly, promotes malformed candidates, or lets janitor/review loops starve actual work.

**Progress note:** Existing tests already covered budget fail-closed behavior, malformed provider retries/history, branch-first follow-up priority, and quota-gated janitor behavior. Re-ran the research/autopilot/queue-pump suite: 46 tests passed. No code patch required.

- [x] **Step 1: Add tests for budget fail-closed behavior**

Mock provider quota responses:

```python
{"rollingFiveHourLimit":{"remaining":0,"limited":true},"weeklyTokenLimit":{"remainingCredits":"$0.10"}}
```

Assert generation/review returns a no-op result with explicit reason and does not enqueue/promote/dispatch.

- [x] **Step 2: Add tests for malformed LLM candidate containment**

Feed malformed JSON, missing required fields, and extra decision fields into the review/admission path. Assert malformed candidates go to rejected/needs-attention maintenance state and are not promoted.

- [x] **Step 3: Add test for branch-first prioritization**

Given follow-up candidates and fresh ideas, assert the autopilot chooses bounded follow-up/branch work first unless there is a safety blocker.

- [x] **Step 4: Patch only deterministic ordering/fail-closed gaps**

Do not add new statuses unless absolutely required. Prefer existing `rejected`, `needs_attention`, `admitted`, and explicit reason fields.

- [x] **Step 5: Verify and commit**

Run:

```bash
uv run pytest -q tests/test_research_autopilot.py tests/test_research_facility*.py tests/test_longhaul_readiness.py
```

Commit subject: `fix: harden research autopilot admission gates`.

---

## Task 6: Release/count drift and public manifest guard audit

**Timebox:** 45 minutes

**Files:**
- Modify if needed: `scripts/validate_public_release.py`
- Modify if needed: `scripts/generate_ecosystem_manifest.py`
- Modify if needed: `scripts/update_public_release_counts.py`
- Modify tests: existing release/count tests

**Risk being hunted:** dashboard/corpus/README/site counts drift again or strict evidence manifest fields become stale.

**Progress note:** Ran public release validation with generated manifest and skip-github-metadata; it passed. No release/count drift was detected in this pass.

- [x] **Step 1: Run strict local release validation with generated manifest**

Run the release validator from the standard bundle. If it fails, inspect the exact field drift.

- [x] **Step 2: Add a regression for the last observed manifest drift class**

The last known failure was:

```text
strict_claim_evidence_pass_count: 3 != generated 388
strict_claim_evidence_gate_status: blocked_audit_gaps != strict_pass
README.md packaging pass lacks nearby strict audit context
```

Add a test that fails if committed manifest values differ from generated values without the validator catching it.

- [x] **Step 3: Patch generator or committed surfaces, not both blindly**

If generated values are correct, update committed manifest/public docs through the existing scripts. If generator is wrong, patch generator and tests.

- [x] **Step 4: Verify cross-repo cleanliness**

Run:

```bash
git status --short --branch
for d in ../enoch-ai-research-corpus ../enoch-docs ../alias8818.github.io ../alias8818 ../jeremyblankenship.dev; do echo "--- $d"; git -C "$d" status --short --branch; done
```

Do not commit in sibling repos unless the release validator requires a coordinated count update.

---


**Additional Research Facility robustness fix:** Hardened Research Facility dashboard generation/provider/run-cycle numeric policy knobs against malformed JSON/env values. Before this, bad values such as `"max_provider_requests_per_run": "not-an-int"` could raise a 500 and turn a long-haul tick into an exit-code failure. Added regressions for smoke generation, provider generation, and run-cycle parsing; targeted router tests and ruff passed.


**Additional provider URL hardening:** Applied the HTTP(S)-only URL guard to Synthetic quota fetches and OpenAI-compatible provider generation calls. Added regressions proving `file://` provider URLs are rejected before `urllib.urlopen` runs; targeted provider tests and ruff passed.


**Additional URL parser hardening:** Extended the shared HTTP URL guard to reject control characters such as CR/LF before `urllib.Request` construction. Added regression coverage for header-injection-shaped URLs.

## Task 7: Static-analysis bug sweep

**Timebox:** 45 minutes

**Files:**
- Modify only if a real bug is found.
- Artifacts if useful: `artifacts/static-analysis/`

**Risk being hunted:** shell injection, unsafe path handling, unsafe deserialization, auth gaps, and broad exception swallowing in control-plane-critical paths.

**Progress note:** Semgrep was installed through `uvx --from semgrep semgrep --config auto --error --timeout 30 enoch_control_plane scripts deploy tests`. It reported broad URL/SQL audit findings; most were operator-configured URLs or allowlisted SQL composition, but one core reliability/security boundary was hardened: callback delivery and worker HTTP helpers now reject non-HTTP(S) URLs before `urllib` can handle local schemes such as `file://`.

- [x] **Step 1: Run Semgrep/custom rules if configured**

Run:

```bash
semgrep --config auto --error . || true
```

If Semgrep is unavailable or too noisy, run targeted grep instead:

```bash
grep -RIn "shell=True\|pickle\.loads\|yaml\.load\|eval(\|exec(\|subprocess\.Popen\|subprocess\.run\|tar -x\|rmtree\|unlink" enoch_control_plane scripts deploy tests | head -300
```

- [x] **Step 2: Triage only exploitable or reliability-relevant findings**

Ignore purely theoretical style findings. Focus on untrusted input to command/path/file/HTTP sinks.

- [x] **Step 3: Add tests before patches**

For each real finding, add the smallest regression test first. Examples:

```python
assert unsafe_path_result["reason"] == "unsafe_path"
assert no_file_was_written_outside_root
assert subprocess_args_are_list_not_shell_string_for_untrusted_input
```

- [x] **Step 4: Patch and commit**

Commit subject format: `fix: harden <boundary> against <risk>`.

---


**Additional static-analysis fix:** Added `enoch_control_plane/url_safety.py` and regression tests so callback delivery, callback sender, and worker HTTP adapter reject `file://`, missing-host, and non-HTTP(S) URLs before network/file handling. Verification: targeted URL/callback/worker tests passed; full suite passed with `496 passed, 5 warnings, 29 subtests passed`; `uv run ruff check .`, runtime snapshot validation, and `git diff --check` passed.


**Additional migration-script hardening:** The SQLite-to-Postgres backfill helper now validates table names and `order_by` columns against a fixed allowlist before composing SQLite SQL. Added regressions for malicious table/order strings; targeted backfill tests and ruff passed.

## Task 8: Deploy decision and live smoke

**Timebox:** 35 minutes

**Files:**
- No code changes expected.
- If deploy script is missing or unsafe, document but do not invent a new deploy system in this task.

- [x] **Step 1: Check live active lane before deploy**
- [x] **Step 1: Check live active lane before deploy**

Live readiness was `ready`, but active count was `1`, so deployment/restart was deferred to avoid interrupting active work.

Run the live readiness probe and inspect active count. If active is nonzero, decide:

- Urgent corruption/paper-safety fix: deploy with restart and document why.
- Non-urgent hardening: leave deployment pending and document exact commits to deploy.

- [x] **Step 2: If deploying, use the established install/sync path**

Preferred safe path from local repo if service can tolerate restart:

```bash
ssh enoch-core.exe.xyz 'sudo systemctl stop enoch-control-plane.service'
rsync -a --delete \
  --exclude .git --exclude .venv --exclude .pytest_cache --exclude __pycache__ --exclude "*.egg-info" \
  ./ enoch-core.exe.xyz:/opt/enoch-control-plane/
ssh enoch-core.exe.xyz 'cd /opt/enoch-control-plane && uv venv --python /usr/bin/python3 .venv && uv pip install --python .venv/bin/python -e . && sudo systemctl start enoch-control-plane.service && systemctl is-active enoch-control-plane.service'
```

Only run this if you have verified the destination path and active-lane risk.

- [x] **Step 3: Live smoke after deploy or no-deploy decision**

Run:

```bash
ssh enoch-core.exe.xyz 'curl -fsS http://127.0.0.1:8787/healthz'
```

Then run live readiness probe. Expected: readiness `ready` or a clearly understood blocker unrelated to this work.

---


**Agentic-PBT sweep:** Re-ran checked-in property proposals for alert behavior, provider-budget logic, and store/callback idempotency. All three returned `no_counterexample`; transient reports were removed after inspection to keep the repo clean.

**Additional callback/state filename hardening:** Found and fixed two filesystem persistence edge cases: missing-key worker callbacks now dedupe exact retries without conflicting on changed retry payloads, callback outbox files cap/hash oversized run IDs, and worker `StateStore` run-state files sanitize path separators plus oversized names. Added regressions for each boundary and reran the callback/state targeted tests plus the full suite.

**Additional Agentic-PBT sweep:** Executed checked-in proposals for `enoch_core.logic`, store callback invariants, alert behavior, and provider-budget gating under the project virtualenv. All four returned `no_counterexample`; reports were kept under `artifacts/agentic-pbt/`.

**Additional alert/path hardening:** Bucketed paper evidence-sync blocked alerts by project/run/reason/hour so repeated draft attempts do not spam Pushover for the same missing-evidence condition. Also hardened worker paper manifest writes to resolve `run_id` through the same project-relative path guard as artifact writes, blocking path traversal in generated manifest paths.

**Additional finalization artifact hardening:** Paper finalization now treats artifact paths as readable only when they resolve under the paper project directory in both SQLite and Supabase-backed stores. Added regressions for imported absolute/outside paths so public package generation fails closed instead of packaging unrelated host files.

**Additional Supabase callback parity hardening:** Mirrored the SQLite fallback idempotency-key behavior in the Supabase store so worker callbacks missing explicit keys dedupe exact retries by run/event/session/payload instead of creating timestamp-keyed duplicate control events.

**Additional worker HTTP evidence hardening:** Worker-returned evidence paths now require a real file target under an existing artifact directory. Empty, dot, directory, traversal, absolute escape, and invalid-byte paths are skipped as unsafe instead of creating the artifact root as a file or crashing sync. Sync also fails closed with an operator-readable reason when the artifact root is unusable.

**Additional paper writer path hardening:** The paper writer shared file-emission helper now rejects empty, dot, directory, invalid, and escaping artifact paths with a controlled 400 instead of surfacing filesystem exceptions during paper rewrite/backfill.

**Additional evidence packaging memory hardening:** Evidence bundle generation now streams source evidence for hashing and only keeps the public preview bytes in memory, preserving full byte counts and hashes while bounding large log/result files during paper rewrite/backfill.

**Additional worker state persistence hardening:** Worker run-state writes now recreate the run-state directory if it disappears and use same-directory atomic replacement, reducing crash/restart corruption risk in the local worker gate state store.

**Additional provider budget fail-closed hardening:** Synthetic quota parsing now treats malformed numeric quota fields as budget failures instead of raising out of the budget status helper, keeping research autopilot decisions operator-readable and fail-closed.

**Additional provider generation retry hardening:** Provider-backed idea generation now applies the bounded retry loop to transient provider call failures as well as malformed JSON responses, preserving the existing no-ledger-write failure boundary.

**Additional Research Facility janitor race hardening:** Janitor apply now writes admission ledger rows only when the candidate status update actually matched a live needs-review row, preventing stale/racing actions from creating misleading admissions.

**Additional Research Facility contract hardening:** Candidate normalization now strips blank list entries and rejects explicitly blank artifact/evidence/failure-mode contracts instead of silently defaulting them into admitted candidates.

## Task 9: Final verification, cleanup, and report

**Timebox:** 25 minutes

**Files:**
- Update this plan with a short completion log if useful.

- [ ] **Step 1: Run final full verification bundle**

Run:

```bash
uv run ruff check .
uv run pytest -q
python3 scripts/validate_runtime_snapshot_links.py
git diff --check
python3 scripts/validate_public_release.py \
  --system . \
  --corpus ../enoch-ai-research-corpus \
  --docs ../enoch-docs \
  --profile ../alias8818.github.io \
  --owner-profile ../alias8818 \
  --personal-site ../jeremyblankenship.dev \
  --generated-manifest /tmp/enoch-ecosystem.generated.json \
  --skip-github-metadata
```

- [ ] **Step 2: Ensure all intended changes are committed and pushed**

Run:

```bash
git status --short --branch
git log --oneline origin/main~10..origin/main
```

Expected: clean working tree, local `main` equals `origin/main`.

- [ ] **Step 3: Produce final operator report**

Report exactly:

```markdown
## Executive verdict
SAFE / SAFE WITH DEPLOY PENDING / NOT SAFE

## Bugs found and fixed
- commit SHA: summary, files changed, tests

## Tests and validators
- command: result

## Live state
- service state
- automation readiness
- active/queued counts
- deployed commit or deployment deferred reason

## Remaining risks
- only concrete risks

## Next best target
- one concrete next task
```

---

## Expected time allocation

| Segment | Target duration |
|---|---:|
| Setup/live baseline | 20 min |
| Store invariants | 60 min |
| Evidence sync hardening | 75 min |
| Paper-write gates | 60 min |
| Queue alerts | 60 min |
| Research autopilot | 60 min |
| Release/count drift | 45 min |
| Static analysis sweep | 45 min |
| Deploy/live smoke | 35 min |
| Final report | 25 min |
| Buffer for hard bugs | 35 min |
| **Total** | **520 min max planned / choose highest-value tasks for 420 min session** |

For a seven-hour run, execute tasks in order and use the buffer by continuing deeper within the current highest-risk boundary. If time runs short, prioritize Tasks 0-4, 8, and 9 over lower-risk release/static-analysis work.

---

**Additional callback outbox path hardening:** Added a containment guard to `deliver_pending_file()` so direct calls cannot replay or mutate JSON files outside the callback outbox. Regression coverage proves an outside path is rejected before payload mutation or network delivery.

---

**Additional active-lane alert false-positive hardening:** Suppressed expired `stale_after` queue alerts when the worker observation model proves the matching run is still live. This keeps the alert lane focused on actual hangs rather than long-running but healthy work.

---

**Additional provider-output bounding:** Capped provider-returned candidate lists to the requested `max_candidates` before returning the batch. Regression coverage prevents a provider from over-admitting extra candidates beyond the quota-gated request size.

---

**Additional janitor LLM review closure hardening:** Normalized missing or invalid per-candidate LLM decisions into low-confidence `keep_for_later` decisions. This prevents partial LLM responses from leaving rows indefinitely stuck in `needs_review` while still failing closed instead of admitting uncertain work.

---

**Additional malformed callback idempotency hardening:** Made missing-identifier worker callbacks dedupe by deterministic payload hash in both SQLite and Supabase stores instead of timestamp. Exact malformed retries now append one event instead of creating unbounded duplicate unknown callbacks.

---

**Additional Agentic-PBT provider safety hardening:** Applied the shared HTTP URL guard to provider-backed property proposal generation and removed a duplicated `proposal_count` result key. Regression coverage proves unsafe provider URLs are rejected before any network call.

---

**Additional paper claim-ledger strictness hardening:** Tightened generated claim ledgers so weak fallback context links do not produce `claims_reference_evidence` pass status. A claim ledger now passes only when every extracted claim has a positive lexical support match, keeping public strict-evidence counts conservative.

---

**Additional worker-preflight malformed telemetry hardening:** Worker dashboard numeric fields now parse fail-closed instead of raising. Malformed GPU/memory/active-run counts produce failed preflight checks and release the dispatch path cleanly rather than crashing after a dispatch claim.

---

**Additional dispatch-claim release hardening:** Wrapped unexpected worker-preflight exceptions after a queue claim and release the claim with a diagnostic 409 backpressure response. A malformed or crashing preflight can no longer strand a queued item in dispatching state.

## Additional pass: public evidence secret redaction

- Root cause: paper evidence packaging streamed previews of worker artifacts verbatim into public `evidence_bundle.json`. If a worker log, prompt, or run note accidentally contained an API key or bearer token, the paper lane could preserve that token in a public artifact.
- Fix: redact common secret/token forms before storing public evidence content while preserving raw source file byte counts and source SHA for provenance.
- Tests: added `test_evidence_bundle_redacts_secret_like_tokens_from_public_content`.

## Additional pass: stricter local paper evidence predicate

- Root cause: `_local_paper_evidence_present` treated any local `results/*.json` as enough paper evidence. That could let a paper rewrite proceed with a metric file but no run notes or decision context, recreating the “paper without enough evidence” failure mode.
- Fix: source-result evidence now requires `run_notes.md` plus at least one safe result JSON. Already-generated paper evidence counts only when both `evidence_bundle.json` and `claim_ledger.json` are present in the same paper directory. Symlink protections remain.
- Tests: added `test_local_paper_evidence_requires_notes_with_result_files` and reran evidence-sync/property/router paper-gate tests.

## Additional pass: malformed callback cannot disturb active lane

- Root cause: a worker callback containing a `project_id` but no `run_id` could mutate an active queue item into `needs_review` because stale-callback protection only ran when a callback supplied a run id.
- Fix: callback handling now checks the current queue row whenever `project_id` is present. If the project has an active `current_run_id` and the callback omits or mismatches `run_id`, the callback is recorded as ignored and the queue item is left untouched. Applied to SQLite and Supabase store implementations.
- Tests: added SQLite and Supabase regression tests for missing-run callbacks against active projects.

## Additional pass: queue alert event-store failures still notify

- Root cause: queue alert notification treated any `append_event` exception like a duplicate/cooldown condition. A transient event-store failure could suppress Pushover even though findings were real.
- Fix: preserve event append errors in the response and still attempt notification when alert findings exist. Cooldown suppression only applies when event append succeeds as a duplicate/no-insert path.
- Tests: added `test_queue_alert_notify_does_not_treat_event_store_failure_as_cooldown`.

## Additional worker artifact write hardening

- Root cause: worker-gate prompt/artifact writes used direct target writes. A crash or filesystem error during overwrite could leave a partially rewritten prompt/artifact file in the project workspace.
- Fix: `_write_text` now writes to a same-directory temporary file and atomically replaces the destination, preserving the prior file if replacement fails and cleaning temporary files.
- Tests: added `test_write_text_preserves_existing_file_when_replace_fails` plus existing overwrite/path tests.

## Additional paper artifact atomic-write hardening

- Root cause: paper-writer artifact emission used direct target writes. A failure during overwrite could corrupt an existing draft/evidence/claim/manifest artifact.
- Fix: `_write_files` now writes to a same-directory temporary file and atomically replaces each artifact target, preserving existing artifacts if replacement fails and cleaning temp files.
- Tests: added `test_write_files_preserves_existing_artifact_when_replace_fails`.

## Additional finalization package atomic-write hardening

- Root cause: finalization manifest writes used direct target writes in the SQLite and Supabase review stores. A filesystem failure during manifest overwrite could leave a partial finalization package on disk.
- Fix: added shared `_atomic_write_text` for finalization manifests and used it in both store adapters.
- Tests: extended finalization package commit/retry coverage to prove existing manifests survive write failure.

## Additional worker HTTP evidence atomic-write hardening

- Root cause: worker HTTP evidence sync wrote returned artifact content directly to target paths. A partial filesystem failure could corrupt previously synced evidence before a paper rewrite.
- Fix: worker HTTP evidence sync now uses the shared same-directory atomic writer for each copied evidence file.
- Tests: added `test_sync_worker_http_evidence_preserves_existing_file_when_write_fails`.

### Additional atomic-write hardening: dashboard snapshots, prepare metadata, legacy deterministic paper artifacts

- Found remaining direct write boundaries in `enoch_control_plane/app.py` and legacy deterministic paper writing in `control_plane/router.py`.
- Added regression coverage proving existing files survive simulated atomic replace failures for:
  - dashboard queue snapshot writes,
  - dashboard paper snapshot writes,
  - worker `prepare-project` metadata writes,
  - legacy deterministic paper artifact writes.
- Switched those paths to the existing atomic writer helpers instead of direct `Path.write_text` replacement.
- Verification: `uv run ruff check . && uv run pytest -q` passed with `547 passed, 5 warnings, 31 subtests passed`.

### Additional callback hardening: project-only callbacks against active rows with missing current run ids

- Found another state-drift edge: if an active queue row had an empty `current_run_id`, a project-only worker callback could still complete or mutate the row.
- Fix: SQLite and Supabase callback handlers now treat any callback without a `run_id` for an active-status queue item as ignored/stale, even when the row's `current_run_id` is empty.
- Tests: added SQLite and Supabase regression coverage for active rows with empty `current_run_id`; existing active-run mismatch coverage still passes.
- Verification: `uv run ruff check . && uv run pytest -q` passed with `549 passed, 5 warnings, 31 subtests passed`.

### Additional dashboard snapshot hardening: count all active lifecycle states

- Found a dashboard snapshot drift edge: `wake_received` and `reconciling` are active control-plane lifecycle states but the worker dashboard snapshot only counted `dispatching`, `awaiting_wake`, and `running`.
- Fix: queue snapshot active-row derivation now includes `wake_received` and `reconciling` and accepts either `queue_status` or `status` fields.
- Test: added `test_queue_snapshot_counts_all_active_lifecycle_statuses`.
- Verification: `uv run ruff check . && uv run pytest -q` passed with `550 passed, 5 warnings, 31 subtests passed`.

### Additional active-lane invariant hardening: reconciling states are active everywhere

- Found a second active-state drift edge: core logic still treated only `dispatching`, `awaiting_wake`, and `running` as active, even though the state contract includes `wake_received` and `reconciling`.
- Fix: `enoch_core.logic.ACTIVE_QUEUE_STATUSES` now matches the state contract; worker dashboard JavaScript fallbacks now count and visually warn on `wake_received`/`reconciling` too.
- Test: added `test_reconciling_states_count_as_active_lane`.
- Verification: `uv run ruff check . && uv run pytest -q` passed with `551 passed, 5 warnings, 31 subtests passed`.

### Additional paper-evidence alert hardening: notify even when event append fails

- Found an alerting fail-open edge: paper evidence-sync blocked notifications depended on appending a control event first. If the event store failed, the request raised before sending Pushover.
- Fix: `paper.evidence_sync_blocked` now attempts notification even if event append raises, and returns event-store failure details in the alert result instead of crashing the no-paper path.
- Tests: added `test_missing_evidence_alert_still_notifies_when_event_store_fails`; strengthened bucketed-alert coverage with varied evidence-sync detail under the same reason bucket.
- Verification: `uv run ruff check . && uv run pytest -q` passed with `552 passed, 5 warnings, 31 subtests passed`.
