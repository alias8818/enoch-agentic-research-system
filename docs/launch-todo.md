# Public launch checklist

This checklist tracks the remaining work before the Enoch system, generated corpus, and source-grounded docs are made public. Completed packaging/security work has been collapsed so this page stays useful as an operator-facing launch board rather than a stale build log.

## Current status

- **Code repo:** public, packaged, CI-enabled, and protected at `alias8818/enoch-agentic-research-system`.
- **Corpus repo:** public, packaging/provenance-linted, and protected at `alias8818/enoch-ai-research-corpus`.
- **Launch site:** deployed at <https://alias8818.github.io/enoch-agentic-research-system/>.
- **Docs website:** hosted at <https://solo-09d10f60.mintlify.app/>; source repo at `alias8818/enoch-docs`.
- **Release framing:** Enoch is the system/control-plane; the corpus artifacts are AI-generated, bounded, replication-worthy outputs that demonstrate what the system can produce.

## Final gates before public visibility

- [x] Re-run final CI and secret scans on code/corpus repos and docs validation before flipping visibility.
- [x] Confirm branch protection is enabled on staged repos before visibility changes.
- [x] Flip `alias8818/enoch-agentic-research-system` public.
- [x] Flip `alias8818/enoch-ai-research-corpus` public.
- [x] Flip `alias8818/enoch-docs` public and verify hosted docs at <https://solo-09d10f60.mintlify.app/>.
- [x] Verify public anonymous access to READMEs, docs, the site, and all highlighted corpus links.
- [x] Confirm final repo/site/docs URLs are present in README, launch site copy, and announcement drafts.
- [x] Verify the credits section names the tooling accurately:
  - Enoch control plane built on LangGraph-backed orchestration/state flow.
  - Development and launch operations assisted by Codex CLI: <https://github.com/Yeachan-Heo/Codex CLI>.

## Site / story polish

- [x] Explain Enoch as an agentic research control plane.
- [x] Highlight the strongest generated artifacts from the corpus.
- [x] Use clear provenance/disclaimer language for AI-generated papers.
- [x] Link the code repo, corpus repo, and docs repo.
- [x] Add sanitized screenshots to release docs from a clean demo/dashboard instance.
- [x] Add an architecture diagram or visual explainer.
- [x] Add compact “why this matters” cards for the top highlighted papers; source is `site/highlights.json`, mirrored into the corpus `papers/highlights.json` and `papers/index.md`.

## Outreach package

- [x] Draft long-form launch announcement.
- [x] Draft short social/thread copy.
- [x] Draft GitHub repo descriptions and pinned-repo blurbs.
- [x] Create final launch post using live public URLs; see `docs/outreach/launch-announcement.md`.
- [x] Prepare 3-5 screenshots/cards for highlighted projects; use sanitized dashboard images plus `site/highlights.json` card text.
- [x] Choose launch order: GitHub/source surfaces first, then personal site/blog, social, and dev communities; see `docs/outreach/launch-announcement.md`.


## Operational TODO: reconnect new-run paper production

Status on 2026-05-06: done for the live Supabase control plane. The earlier 2026-05-02 gap was repaired, the positive/actionable backfill was drained, and the remaining completed no-paper rows are decision-gate rejected rather than papers to write. Live readiness evidence reported `write_needed = 0`, `raw_completed_no_paper_candidates = 220`, `not_writable_by_decision_gate = 220`, `publish_ready = 0`, and `published_imported = 492`.

Required follow-up:

- [x] Update paper draft eligibility so completed wake-gate runs with `next_action_hint = draft_paper_or_select_next_project` and sufficient evidence/artifacts are draft candidates; keep the old `last_run_state = finalize_positive` path.
- [x] Add automated paper recovery without starving drafts, then disable it by default: draft-next now requires explicit opt-in (`ENOCH_ENABLE_PAPER_DRAFT_NEXT=1`), the dedicated timer is not installed by default, and the queue pump leaves paper drafting off unless `queue_pump_paper_draft_enabled` is true.
- [x] Backfill paper drafts for completed paper-positive projects produced after the LangGraph cutover, preserving evidence sync, claim ledger, manifest, and publication-policy metadata; remaining completed no-paper rows are decision-gate rejected and are not writable.
- [x] Connect the publication/rewrite workflow to newly drafted papers, including targeted publication-automation backfill and GLM-5.1/Synthetic.new rewrite where configured.
- [x] Add regression tests proving a `worker_callback.wake_ready` completion becomes paper-draft eligible, existing papers prevent duplicate drafts, draft-only automation is opt-in and never dispatches, and the queue pump only drafts before dispatch when explicitly enabled.

## Follow-up quality work

- [x] Pick 10-15 strongest papers for deeper external-style inspection and summary cards; 13 launch highlights are recorded in `site/highlights.json` and the corpus highlight index.
- [x] Add per-paper “why this is interesting” summaries to the corpus index; `enoch-ai-research-corpus/papers/index.md` now has a highlighted-artifacts section generated from `papers/highlights.json`.
- [x] Add a reproducibility note explaining what artifacts are included and what private runtime state is intentionally excluded; see `enoch-ai-research-corpus/docs/reproducibility.md`.
- [x] Define the public-feedback loop: convert substantive feedback into GitHub issues first, then into queue/intake items only after source-grounded validation. Actual feedback collection starts after launch.

## Already completed packaging/security work

- [x] Added GitHub issue/PR templates, CODEOWNERS, CI, Dependabot, security policy, and protection automation.
- [x] Applied private-repo settings: issues on, discussions on, projects/wiki off, squash-only merges, branch delete on merge.
- [x] Applied branch protection on the staged code and corpus repos, with docs repo visibility tracked separately.
- [x] Kept private career-positioning notes out of public repositories.
- [x] Removed live secrets, local state DBs, production logs, and private LAN endpoints from public artifacts.
- [x] Kept old n8n/OpenClaw workflow material historical only; workflow exports are not shipped as the product.
- [x] Packaged the control-plane repo with quickstart, deployment guide, config reference, Pushover notes, and smoke tests.
- [x] Packaged the corpus repo with 377 canonical AI-generated research artifacts, provenance metadata, claim-ledger files, evidence bundles, packaging/provenance reports, and a strict claim/evidence audit report.
- [x] Stated clearly that generated papers are AI-generated artifacts and that no personal authorship credit is claimed for the paper text or results.
