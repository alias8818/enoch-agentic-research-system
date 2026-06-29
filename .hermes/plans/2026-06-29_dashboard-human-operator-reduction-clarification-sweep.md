# Dashboard human-operator reduction and clarification sweep

## Goal

Make Dashboard V2 provide meaningful human-operation state at a glance without becoming an agent/debug console.

Important distinction:

- Enoch's paper/publication pipeline should remain human-removed: deterministic gates decide whether generated outputs advance.
- The dashboard itself is for a human operator: it should answer operational questions in plain status language, surface useful counts and blockers, and hide agent/internal/debug detail until the operator intentionally drills down.

## Linear / source of truth

- Umbrella: `ALI-157` — Corral and polish Enoch dashboard information architecture.
- Active follow-up: `ALI-212` — Dashboard reduction follow-up: collapse workflow chrome and strengthen human-operation status hierarchy.
- Completed prior sweep: `ALI-210` — Dashboard reduction sweep: human-operation statuses over agent/debug surfaces.
- Keep the existing paper wording invariant from `ALI-209`: use automation-gate language for publication flow, not review/attention/manual approval language.

## Design principles for this sweep

1. **Human operation first**
   - Each top-level card answers a human question: Is it running? Is it blocked? What is progressing? What changed? What gate failed?
   - Avoid raw agent words as the headline: `operator_action`, `operator_next_step`, `run_id`, `payload`, `event_id`, `JSON`, `diagnostic`, `callback`, etc.
   - Keep raw terms available in drilldowns, not primary surfaces.

2. **Statuses must be meaningful, not decorative**
   - Replace vague labels with concrete state classes:
     - `Running normally`
     - `Blocked by gate`
     - `Waiting for lane capacity`
     - `Import caught up`
     - `Generated output pending corpus import`
     - `Telemetry stale`
     - `No current work in this slice`
   - A status should imply why the operator should care.

3. **Reduction beats rewording**
   - Remove duplicate cards before polishing copy.
   - Collapse secondary details behind `details` or row drilldowns.
   - Prefer one strong card + 2–4 supporting metrics over multiple adjacent cards saying similar things.

4. **Raw/debug detail stays accessible but subordinate**
   - Raw JSON, event payloads, composite IDs, filesystem paths, exact API source, and copied identifiers remain in detail panels/debug folds.
   - They should not be visible in first-screen cards unless the page is explicitly a forensic/debug page.

5. **Paper/publication copy must preserve automation semantics**
   - Use: `publication automation gates`, `gate-blocked`, `evidence-gate completion`, `corpus import`, `generated output`.
   - Avoid for paper flow: `review`, `attention`, `approval`, `human-first`, `customer-facing copy`.

## Audit targets

### 1. Overview / command center

Files:

- `dashboard/src/App.tsx`
- `dashboard/src/components/CommandHero.tsx`
- `dashboard/src/components/PaperMiniStrip.tsx`
- `dashboard/src/components/WorkbenchSummary.tsx`
- `dashboard/src/activeWorkDisplay.tsx`

Questions to answer:

- Does the first screen answer: **Can I leave Enoch running?**
- Does it show why in one sentence with active/queued counts?
- Are paper pipeline counts framed as automation gates, not human review?
- Are secondary workbench counts collapsed unless they change the operator decision?

Candidate changes:

- Rename any remaining `operator`-centric visible labels where they mean human-facing operation state.
- Convert paper strip labels from `Write / Finalize / Publish` if they are ambiguous into gate labels such as `Draft generation`, `Finalization gate`, `Corpus import`.
- Collapse non-decision count folds further if they compete visually with the hero.

Acceptance checks:

- Overview has exactly one dominant readiness/running answer.
- Paper pipeline strip uses automation-gate vocabulary.
- No raw IDs/paths/JSON visible above the fold.

### 2. Resource workflow pages: Projects / Queue / Runs / Papers

Files:

- `dashboard/src/components/ResourcePages.tsx`
- `dashboard/src/components/ResourcePages.test.tsx`
- `dashboard/src/resourceStatePresentation.ts`
- `dashboard/src/tablePresentation.ts`

Questions to answer:

- Projects: Which workstreams are progressing, blocked, or waiting?
- Queue: Can queued work dispatch, and if not, which deterministic blocker prevents it?
- Runs: Which runs are active, completed, or failed by gate/callback?
- Papers: Which visible generated outputs are imported, gate-blocked, or ready for corpus flow?

Candidate changes:

- Replace visible `attention`/`operator` labels where they are not literally about the human operating the dashboard.
- Reduce three-card briefings when a single card plus metric strip is enough.
- Move `Raw detail access` cards lower or collapse them; keep raw affordances but stop promoting them as equal to the status summary.
- Rename `Forensic detail` where it is not forensic; reserve forensic language for actual failure inspection.
- Ensure empty/loading/stale states say what the human can conclude, not what an agent should inspect.

Acceptance checks:

- Source search for old confusing terms has explicit allowlist/denylist.
- Tests assert visible status language, not only component existence.
- Page cards answer human operational questions before raw table controls.

### 3. Detail panels and drilldowns

Files:

- `dashboard/src/components/DetailPanel.tsx`
- `dashboard/src/components/ui/RawJsonDetails.tsx` if present under `ui`
- `dashboard/src/components/DataTable.tsx`

Questions to answer:

- When a human opens a detail view, what is the conclusion first?
- Are raw fields grouped under clear headings?
- Can the operator copy IDs/paths without those IDs dominating the page?

Candidate changes:

- Add a compact `Status summary` section before related rows/raw JSON.
- Keep copy buttons, but make labels like `Copy run id ...` visually subordinate.
- Group raw JSON under `Debug payload` or `Raw API payload`, collapsed by default.

Acceptance checks:

- Detail pages do not open with raw JSON as the dominant content.
- Related rows are titled by meaningful labels when available, not IDs first.

### 4. Navigation and page naming

Files:

- `dashboard/src/App.tsx`
- `dashboard/src/routes.ts`
- `dashboard/src/components/PaperWorkflowNav.tsx`

Questions to answer:

- Does navigation match human operation concepts?
- Are agent/internal concepts moved under `More` or renamed?

Candidate changes:

- Consider renaming `Candidate generation` to `Generation health` or `Idea generation` depending on page content.
- Consider renaming `Idea intake` to `Idea intake ledger` if the page is ledger-like, or `Recommended ideas` if it is decision-like.
- Clarify `Papers` subnav details:
  - `Papers`: generated outputs and gate state
  - `Paper corpus import`: corpus-import coverage
  - `Paper actions`: automation controls and gate commands

Acceptance checks:

- Nav labels map to human questions.
- Page titles do not require knowing internal agent architecture.

### 5. Observability / research / intake pages

Files:

- `dashboard/src/components/ResearchPage.tsx`
- `dashboard/src/components/ObservabilityPage` if split, otherwise `ResourcePages.tsx`
- `dashboard/src/components/SettingsPage.tsx`

Questions to answer:

- Are these pages operationally useful, or just telemetry dumps?
- Does each page summarize health before listing events/models/rows?

Candidate changes:

- Use health summaries like:
  - `Model pool healthy`
  - `Generation degraded: no usable candidate JSON from latest provider`
  - `Telemetry stale`
  - `No admitted ideas waiting`
- Collapse verbose model/event payloads below a summary.
- Keep provider/model IDs available but not as the leading text when a label or health state exists.

Acceptance checks:

- Human can tell healthy/degraded/stale from the top card.
- Raw telemetry remains available for debugging.

## Static guardrails to add

Add or update tests/static source guards around dashboard visible copy.

Suggested denylist for primary dashboard surfaces:

- Paper flow denylist:
  - `Publication briefing`
  - `visible evidence review`
  - `need evidence review`
  - `operator attention`
  - `publication review`
  - `human-first`
  - `human approval`
- General first-screen denylist, except raw/debug components:
  - `Raw JSON` above first summary region
  - `payload` as a card title
  - `operator_action` visible literally
  - `operator_next_step` visible literally
  - filesystem path or composite ID in card title

Suggested positive assertions:

- Overview contains a dominant `Can I leave this running?` answer.
- Papers contains `Publication automation gates` and `visible gate-blocked`.
- Queue contains a dispatch-safety human summary.
- Runs contains active/completed/blocked state language before IDs.
- Detail views expose raw payload only in a collapsed/debug section.

## Implementation slices

### Slice A — Audit + static guardrails

1. Search dashboard source for confusing terms and raw/internal labels.
2. Add test helpers that classify allowed raw/debug surfaces vs primary cards.
3. Create failing tests for the highest-priority visible wording/hierarchy issues.
4. No visual redesign yet except test fixtures if necessary.

Verification:

- `npm --prefix dashboard run test -- ResourcePages CommandHero App`
- `npm --prefix dashboard run lint`

### Slice B — Overview + paper strip reduction

1. Polish `CommandHero` / `PaperMiniStrip` copy for human operation.
2. Demote secondary count folds that do not affect the main answer.
3. Update tests for the one-answer hierarchy and automation-gate labels.

Verification:

- Targeted tests for `CommandHero`, `App`, paper strip.
- Build assets.

### Slice C — Workflow page cards

1. Reduce Projects/Queue/Runs/Papers briefing grids.
2. Move raw-access explanation to drilldown/help regions instead of equal top cards.
3. Clarify empty/loading/stale states.
4. Update duplicate-title and visible-copy tests.

Verification:

- `npm --prefix dashboard run test -- ResourcePages`
- Rendered page smoke with representative fixtures or live data.

### Slice D — Detail/debug containment

1. Ensure detail pages lead with status summary.
2. Collapse raw JSON/debug payloads by default.
3. Keep copy controls but make them subordinate.

Verification:

- DetailPanel tests.
- Rendered detail route smoke.

### Slice E — Live deploy + rendered QA

1. Build committed dashboard assets.
2. Deploy with `ENOCH_CONTROL_SMOKE=1 scripts/deploy-enoch-runtime.sh --profile control`.
3. Run deterministic live bundle string checks for key terms.
4. Run rendered/browser QA if bearer path is available.
5. Record evidence in Linear and close the slice only after deployed verification.

## Commands

```bash
# Source audit
rg -n "Publication briefing|visible evidence review|need evidence review|operator attention|publication review|human-first|human approval|Raw JSON|payload|operator_action|operator_next_step" dashboard/src

# Targeted tests
npm --prefix dashboard run test -- ResourcePages CommandHero App
npm --prefix dashboard run lint
npm --prefix dashboard run build

# Runtime deploy/smoke, after code is ready
ENOCH_CONTROL_SMOKE=1 scripts/deploy-enoch-runtime.sh --profile control
```

## Done definition

- New Linear child/slice exists under the dashboard polish umbrella.
- Dashboard source has no unapproved visible wording that implies agent/debug-first or manual paper review/approval semantics.
- Tests assert human-operation status language and raw-detail demotion.
- Dashboard assets are rebuilt.
- Deployed dashboard smoke passes.
- Live bundle/rendered checks confirm old confusing terms are absent and new human-operation statuses are present.
