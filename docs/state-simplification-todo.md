# State simplification TODO

Status: active next-phase backlog after the Supabase state-contract cleanup on 2026-05-06. State doctor command is implemented; corpus/publication/public-count reconciliation is clean across local corpus, GitHub public surfaces, and Hugging Face export. Notion-runtime retirement is now guarded for primary UI wording and source-metadata overwrite safety, and the live Supabase resume-readiness smoke passed.

The current state model is coherent and live-clean. The remaining legacy/unknown rows have been classified as historical or attention-lane residue, not active runtime drift.

## 1. Operator dashboard polish

- [x] Rework overview cards around grade-school operator questions:
  - What needs me?
  - What is running?
  - What can be written?
  - What can be published?
  - What is done / no paper?
- [x] Hide raw state/detail fields by default and keep them in debug/detail drawers only.
- [x] Keep paper cards tied to `paper_pipeline.write_needed`, `finalize_needed`, and `publish_ready`, not raw paper statuses.

## 2. State transition map

- [x] Add a one-page lifecycle map: Idea -> Queue -> Run -> Decision -> Paper -> Publication -> Corpus.
- [x] For each transition, document:
  - source of truth;
  - writer/owner;
  - validation gate;
  - impossible/invalid transitions;
  - operator lane shown in the dashboard.
- [x] Add tests or validators for any transition that is currently implicit.

## 3. Corpus/publication reconciliation

- [x] Reconcile `publication_draft`, `ready_to_publish`, corpus import ledger, and public repo count.
- [x] Verify/update Hugging Face count after the corpus repo commit is published.
- [x] Produce one canonical answer for: what is actually public locally.
- [x] Make stale public count drift fail validation/CI where possible.
- [x] Keep public labels/counts generated from a single source or deterministic manifest path.

## 4. Retire Notion assumptions

- [x] Make Supabase `ideas` the primary editable intake/workbench source of truth.
- [x] Keep Notion IDs/URLs as provenance only.
- [x] Rename primary UI/docs language away from Notion where it is no longer the runtime owner.
- [x] Audit import/re-ingest paths so source metadata cannot overwrite Supabase-owned runtime fields.

## 5. Add a state doctor command

- [x] Add one command/report that future agents run before answering state questions.
- [x] Include:
  - state contract validation;
  - normalization dry-run row count;
  - nonzero legacy/alias/migrate-after-freeze rows;
  - write-needed/raw/no-paper counts;
  - publication-ready/imported/public counts;
  - dashboard operator-count keys;
  - live service health/smoke status.
- [x] Fail loudly on mixed ledgers, stale public counts, or raw detail stages in primary operator counts.
- [x] Document the command in `docs/state-model.md` and the parent wiki.

## Preferred execution order

1. State doctor command. (done)
2. Corpus/publication reconciliation. (done)
3. Dashboard polish. (done)
4. State transition map. (done)
5. Notion-runtime retirement. (done; live Supabase resume-readiness smoke passed)

## Previous known live baseline

Last verified on 2026-05-06 before corpus-import ledger-backed dashboard semantics:

- `write_needed = 0`
- `raw_completed_no_paper_candidates = 220`
- `not_writable_by_decision_gate = 220`
- `finalize_needed = 0`
- `publish_ready = 491` under the old finalized-total semantics
- paper rows: `publication_draft = 494`, `archived = 2`, `all = 496`
- state normalization dry-run: `0` rows
- live state contract: OK
- state doctor: OK; corpus reconciliation reports 0 importable finalized publication drafts after local corpus import

## State doctor evidence

Command shape for the live validation artifact:

```bash
uv run python scripts/state_doctor.py \
  --database-url "$ENOCH_SUPABASE_DATABASE_URL" \
  --control-url "$ENOCH_CONTROL_URL" \
  --token-file /path/to/enoch-control-plane-token.txt \
  --corpus ../enoch-ai-research-corpus \
  --output path/to/state-doctor.json
```

Last observed state doctor result on 2026-05-06:

- exit code: `0`
- failure reason: none
- `state_contract.ok`: OK
- `normalization.total_rows`: `0`
- `control_plane.overview`: OK
- `paper_pipeline.write_needed`: `0`
- `paper_pipeline.raw_completed_no_paper_candidates`: `220`
- `paper_pipeline.not_writable_by_decision_gate`: `220`
- `paper_pipeline.finalize_needed`: `0`
- `paper_pipeline.publish_ready`: `491` under the old finalized-total semantics
- `corpus_reconciliation.live_finalized_publication_draft_count`: `491`
- `corpus_reconciliation.public_corpus_count`: `495`
- `corpus_reconciliation.importable_finalized_count`: `0`

## Legacy/unknown row classification

Implemented on 2026-05-06:

- `scripts/state_doctor.py` now separates legacy/internal residue from active runtime drift.
- Classified legacy rows stay visible in `legacy_runtime_context` without WARN noise when `active_queue = 0`; the doctor fails if a legacy/internal state attaches to an active queue lane (`dispatching`, `running`, `awaiting_wake`, `wake_received`, or `reconciling`).
- Last live classification:
  - `ideas.idea_status.unknown`: `12` total, `0` active queue rows, `9` attention queue rows.
  - `projects.origin_idea_status.unknown`: `132` total, `0` active queue rows, `9` attention queue rows.
  - `runs.state.unknown`: `240` total, `0` current queue rows, `0` active queue rows, `240` paper-linked historical rows.
  - `runs.gate_state.blank`: `722` total, `479` current queue runs, `0` active queue rows, `9` attention queue rows, `494` paper-linked rows.
- Interpretation: remaining unknown/blank rows are not active worker-lane state. They are provenance gaps, blocked historical rows, completed rows, or imported publication-era records.

## Hugging Face evidence

Last verified on 2026-05-06 after publishing `aliasocracy/enoch-ai-research-corpus`:

- `dataset_summary.artifact_count`: `495`
- `dataset_summary.strict_claim_evidence_total_count`: `495`
- `data/artifacts.jsonl` rows: `495`

## Dashboard polish evidence

Implemented on 2026-05-06:

- Overview now starts with `What do I need to know?` cards:
  - `What needs me?`
  - `What is running?`
  - `What can be written?`
  - `What can be published?`
  - `What is done / no paper?`
- Raw completed/no-paper and decision-gate rejection counts moved into `Debug paper counts` drill-down.
- Paper pipeline primary cards remain derived from `paper_pipeline.write_needed`, `paper_pipeline.finalize_needed`, and `paper_pipeline.publish_ready`.
- Regression evidence: `uv run pytest -q tests/test_control_plane_operator_status.py tests/test_control_plane_router.py tests/test_state_doctor.py`.
- Live deployment evidence: `enoch-control-plane.service` restarted on `192.168.1.166`; `/control/dashboard` HTML contains the new question cards and `Debug paper counts`; live `/control/api/v1/overview` still reports `write_needed=0`, `raw_completed_no_paper_candidates=220`, `not_writable_by_decision_gate=220`, `finalize_needed=0`, `publish_ready=0`.

## Dashboard shell redesign evidence

Implemented on 2026-05-06:

- `/control/dashboard` now uses a professional operator shell: sidebar navigation, top search, token/refresh controls, card/table layout, light/dark variables, and collapsed debug panels.
- The shell remains dependency-free inline HTML/CSS/JS and continues to read from bounded `/control/api/v1/*` endpoints.
- No-token browser loads now stop before authenticated API calls and show a token-required message instead of emitting repeated unauthenticated 401 requests.
- Authenticated browser smoke shows the overview cards with `write_needed=0`, `publish_ready=0`, and non-writable rows labeled as done/no-paper informational state.

## State transition map evidence

Implemented on 2026-05-06:

- Added `docs/state-transition-map.md` with the lifecycle `Idea -> Queue -> Run -> Decision -> Paper -> Publication -> Corpus`.
- Documented source of truth, writer/owner, validation gate, invalid transitions, and operator lane for each transition.
- Added `tests/test_state_transition_map.py` to lock decision-gate, publication-readiness, and operator-count invariants.

## Notion-runtime retirement evidence

Implemented on 2026-05-06:

- Dashboard/source links now render as `Source` instead of `Notion`.
- Worker project prompts now label retained URLs as `Source/provenance URL`.
- SQLite and Supabase legacy Notion re-ingest paths preserve runtime-owned `project_dir` on conflict.
- Supabase-native idea intake preserves existing source/provenance URLs instead of clearing them with blank Notion fields.
- Snapshot imports retain existing provenance when incoming source URL/page ID fields are blank.
- Regression evidence:
  - `uv run pytest -q tests/test_control_plane_store.py::ControlPlaneStoreTests::test_notion_intake_preserves_existing_queue_routing_metadata tests/test_control_plane_store.py::ControlPlaneStoreTests::test_supabase_native_intake_preserves_existing_source_provenance tests/test_control_plane_store.py::ControlPlaneStoreTests::test_legacy_notion_reingest_preserves_runtime_project_dir tests/test_control_plane_router.py::ControlPlaneRouterTests::test_control_dashboard_html_is_served_without_token tests/test_control_plane_router.py::ControlPlaneRouterTests::test_project_prompt_uses_source_provenance_instead_of_notion_authority`
  - `uv run pytest -q tests/test_supabase_runtime_cutover.py::test_supabase_legacy_notion_intake_preserves_runtime_project_dir`

## 2026-05-06 live Supabase resume-readiness evidence

Command:

```bash
python3 scripts/validate_supabase_resume_readiness.py \
  --control-url http://192.168.1.166:8787 \
  --ssh-host root@192.168.1.166 \
  --token-file <(ssh root@192.168.1.166 'cat /root/enoch-control-plane-token.txt') \
  --output /tmp/enoch-supabase-resume-readiness.json
```

Result: `ok = true`, failures = `[]`.

Evidence from `/tmp/enoch-supabase-resume-readiness.json`:

- `/enoch-core/health`: `store_backend = supabase`, `db_path = supabase`.
- Legacy Notion intake/projection endpoints return `410`.
- Supabase-native ideas workbench returns `200` and reports authority: `Supabase-native ideas workbench; Notion is provenance only`.
- Queue remains paused/maintenance-guarded after the controlled resume drill.
- Notion sync/background timers are not active: enabled states `masked`, `masked`, `disabled`, `disabled`; active states all `inactive`.
- Paper pipeline is gate-aware: `write_needed = 0`, `publish_ready = 0`, `missing_from_corpus = 0`, `published_imported = 492`, `publication_ready_total = 492`, `raw_completed_no_paper_candidates = 220`, `not_writable_by_decision_gate = 220`.


## 2026-05-06 operator label simplification evidence

Implemented after the state-model audit:

- `operator_stage_label` and `operator_detail_stage_label` now use an explicit grade-school vocabulary map instead of title-casing raw/detail state keys.
- Primary labels are: `Running`, `Ready`, `Needs Attention`, `Done / No Paper`, `Write Paper`, `Finalize Draft`, `Publish / Import`, `Published`, `Paused`, and `Historical`.
- Compatibility/detail keys can still exist for API/debug stability, but labels must not show raw phrases such as `Run Complete Draft Needed`, `Wake Ready`, `Draft Review`, `Approved`, or `Review` as first-screen workflow language.
- Live authenticated overview after deploy reports: `write_needed = 0`, `raw_completed_no_paper_candidates = 220`, `not_writable_by_decision_gate = 220`, `finalize_needed = 0`, `publish_ready = 0`, `published_imported = 492`, `publication_ready_total = 492`.
- Live blocked queue rows label as `Needs Attention` / `Needs Attention` while retaining raw keys `needs_operator` / `blocked_needs_operator` for drill-down/debug.
- State doctor after deploy: `ok = true`, state contract OK, normalization dry-run rows `0`, corpus reconciliation importable finalized count `0`; remaining legacy-internal rows are classified as historical/attention residue instead of WARN noise when `active_queue = 0`.
- Regression evidence: `uv run pytest -q tests/test_control_plane_operator_status.py tests/test_state_contract.py tests/test_state_transition_map.py tests/test_state_doctor.py tests/test_control_plane_router.py` passed with `72 passed, 13 subtests passed`.


## 2026-05-06 state doctor residue-noise correction

Implemented after the operator-label patch:

- State doctor now keeps expected legacy/internal residue visible in `legacy_runtime_context` but suppresses `WARN legacy internal rows remain` when the residue is classified as `historical_or_attention_residue` and has `active_queue = 0`.
- Active runtime attachment is still a hard failure through `legacy_runtime_context.active_runtime_drift`; unclassified legacy/internal rows still warn.
- Live read-only SQL samples showed `runs.state = unknown` is no-queue imported paper provenance, while blank `runs.gate_state` is completed/blocked/historical residue with zero active runtime rows.
- Live state doctor evidence after the patch: `ok = true`, failures `[]`, warnings `[]`, normalization dry-run rows `0`, `write_needed = 0`, `publish_ready = 0`, `raw_completed_no_paper_candidates = 220`, `not_writable_by_decision_gate = 220`.

## 2026-05-06 corpus import count correction

- Dashboard publish/import work is being corrected to be ledger-backed: `publish_ready` / `missing_from_corpus` means finalized drafts without a `corpus_imports` row.
- Historical finalized drafts already represented in the corpus move to `published_imported` / `published` and should not appear as actionable import work.
- Public release count drift was fixed by updating GitHub metadata for `alias8818/enoch-ai-research-corpus` to `496`; `validate_public_release.py` passed afterward.
