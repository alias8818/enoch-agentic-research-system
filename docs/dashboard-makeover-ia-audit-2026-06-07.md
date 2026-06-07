# Dashboard makeover rendered IA audit — 2026-06-07

Source: rendered browser QA through local bearer-injecting proxy + SSH tunnel to `enoch-core.exe.xyz`.

Access path:

- SSH tunnel: `127.0.0.1:18787 -> enoch-core.exe.xyz:127.0.0.1:8787`
- Local proxy: `http://127.0.0.1:18087/control/dashboard-v2/`
- Routes audited: `#overview`, `#projects`, `#queue`, `#runs`, `#papers`
- Console: no JS errors observed while capturing pages.

Preflight runtime state before audit:

- First readiness check briefly showed `Long-haul mode: BLOCKED — latest provider generation attempt failed`.
- Follow-up classification immediately showed latest provider generation success, `Long-haul mode: READY`, queue-alert `should_alert=false`, `fingerprint=none`, `findings=[]`.
- Dashboard audit proceeded after the blocker self-cleared and queue-alert stayed clean.

## Visual benchmark to preserve

The **Paper Material Graph / Graph briefing** card remains the strongest target:

- compact and card-native
- visual metric/orbit strip
- only two featured leads
- no packet paths/raw identifiers as top-level content
- clear human labels: `Best synthesis lead`, `Most useful negative`
- high information density without table sprawl

Use this benchmark for M0/M1/M2 implementation.

## Overview

Primary operator question: **Is Enoch safe/productive right now, and what should I do next?**

### Preserve

- Strong dark command-center visual system.
- Top nav + global search are usable.
- Data freshness and queue safety are concise and useful.
- `What is moving now?` answers active lane state in human terms.
- Worker lane cards contain valuable lane depth/current/next/action detail.
- Paper Material Graph is the polish/information-density benchmark.

### Problems

1. Readiness/next-action is duplicated across three surfaces:
   - hero: `Check readiness first`
   - `Automation readiness`: `Not checked`
   - `Primary action`: `Check readiness first`
2. The Overview has several competing top-level cards instead of one single command answer.
3. Worker lanes are useful but dense: `current`, `next`, `feed action`, queue prose, worker-confirmed prose, `lane active`, and three buttons per lane.
4. Active work is styled prominently; ensure normal active work is not confused with risk.
5. Paper pipeline is useful but visually weaker than Graph briefing; gate/archive copy is dense and less briefing-like.

### Map to slices

- ALI-167: collapse readiness/action duplication.
- ALI-168: worker lane affordance/copy cleanup and paper pipeline polish.
- ALI-165: shared operator answer / metric strip / briefing cards.
- ALI-166: details/raw demotion pattern.

## Projects

Primary operator question: **What workstreams matter, what is their health, and where should attention go?**

### Preserve

- Search/status/size controls are useful.
- Last-loaded metadata and refresh are useful.
- Raw table is useful for operator/debug work if demoted.
- Rows are clickable and support structured detail navigation.

### Problems

1. Page is table-first with no human briefing layer.
2. Copy-ID controls and truncated IDs are visually prominent in the second column.
3. `queued`, `awaiting_wake`, raw lane/status values appear before health/attention summary.
4. No above-fold grouping by workstream meaning, health, freshness, blocked/active/queued relevance, or next action.
5. The table answers “what rows exist?” before “what should I care about?”

### Map to slices

- ALI-169: project/workstream briefing cards.
- ALI-166: ID/copy controls moved into row/card drilldowns.
- ALI-174: static/raw-field guard for IDs outside debug containers.

## Queue

Primary operator question: **Can I safely dispatch, why/why not, and which queue items matter now?**

### Preserve

- Filters, saved filters, refresh, pagination, and selected-row dispatch controls are useful.
- Exact selected-row dispatch check is an important safety affordance.
- Raw table remains useful for operations/debug.

### Problems

1. Queue opens with controls and raw table, not dispatch-safety briefing.
2. `Selected queue row` card is useful but mostly empty until selection and does not summarize global dispatch safety.
3. Raw IDs/copy controls are prominent.
4. Internal hints dominate: `draft_paper_or_select_next_project`, `finalize_positive`, `viable_as_hybrid_not_pure_ssm`.
5. Machine/lane values like `192.168.1.77` are top-level, not operator-translated.

### Map to slices

- ALI-170: top dispatch safety briefing and action grouping.
- ALI-166: raw status/hints and IDs in drilldowns.
- ALI-173: selected-row empty state should guide next action.

## Runs

Primary operator question: **What happened in the run, did it succeed, and where is evidence/log detail?**

### Preserve

- Search/status filters and last-loaded refresh are useful.
- Run table has useful forensic access and row detail navigation.
- Recent timestamps are useful.

### Problems

1. Most machine-readable page: project slugs, run IDs, copy run ID controls, `wake_ready`, `worker_callback`, `exec` dominate.
2. No story/timeline layer for recent runs.
3. `STATE` and `GATE` duplicate values for many rows.
4. There is no top-level distinction between active, waiting-for-wake, callback received, completed, failed, or needs attention in human terms.
5. Forensic detail appears before outcome/evidence story.

### Map to slices

- ALI-171: run-story cards/timelines.
- ALI-166: run IDs/callback internals in detail containers.
- ALI-174: guard top-level `worker_callback` and raw run IDs.

## Papers

Primary operator question: **What publication artifacts exist, how ready are they, and what workflow action is next?**

### Preserve

- Paper workflow tabs (`Papers`, `Paper corpus import`, `Paper actions`) are promising as a workflow nav.
- Search/status/size/refresh controls are useful.
- Evidence/finalization/import columns represent important workflow truth.

### Problems

1. Papers is raw ID first: paper names are long `project:run:arxiv_draft` composite IDs.
2. `publication_draft`, `missing`, and `imported` chips are visible but not explained as readiness/action state.
3. No publication briefing or artifact hero above the raw table.
4. The page does not answer what paper is closest to publishable, what evidence is missing, or what action to take next.
5. Copy-ID controls and raw draft IDs are too prominent for a customer-facing artifact page.

### Map to slices

- ALI-172: publication briefing and evidence readiness hierarchy.
- ALI-166: raw draft IDs moved into artifact/debug details.
- ALI-173: empty/missing evidence states should be operator-friendly.

## Cross-page themes

### Preserve globally

- Existing dark visual system, spacing, and gold accent language.
- Navigation/search/theme/shortcuts.
- Real raw detail access through row selection/detail pages.
- Safety affordances: readiness checks, dry-run dispatch, pause/resume, selected dispatch.
- Backend truth; do not fix semantics with cosmetic frontend copy.

### Change globally

1. Add briefing-first page headers before tables.
2. Create shared card vocabulary for:
   - operator answer
   - metric strips
   - status/risk chips
   - action rows
   - evidence rows
   - run/story timeline
3. Demote IDs/slugs/packet paths/callback internals/copy controls into drilldowns or `details.raw-details`.
4. Add static/rendered guards for high-risk regressions:
   - `worker_callback` not visible top-level on Runs
   - raw composite paper IDs not dominant on Papers
   - copy-ID controls not prominent before drilldown on normal operator pages
   - raw JSON only inside collapsed details
5. Make red mean actual risk only.

## Recommended execution priority

1. ALI-165 + ALI-166 foundation primitives and raw-detail contract.
2. ALI-167 Overview readiness hierarchy because it affects the command center first impression.
3. ALI-168 worker lane/paper pipeline polish using Graph briefing vocabulary.
4. ALI-170 Queue dispatch briefing because it directly affects safe operations.
5. ALI-172 Papers publication briefing because it is most customer-facing and currently rawest.
6. ALI-171 Runs story layer.
7. ALI-169 Projects briefing cards.
8. ALI-173/174 hardening as components land.
