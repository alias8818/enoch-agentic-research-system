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
  - Development and launch operations assisted by oh-my-codex/OMX: <https://github.com/Yeachan-Heo/oh-my-codex>.

## Site / story polish

- [x] Explain Enoch as an agentic research control plane.
- [x] Highlight the strongest generated artifacts from the corpus.
- [x] Use clear provenance/disclaimer language for AI-generated papers.
- [x] Link the code repo, corpus repo, and docs repo.
- [x] Add sanitized screenshots to release docs from a clean demo/dashboard instance.
- [x] Add an architecture diagram or visual explainer.
- [ ] Add compact “why this matters” cards for the top highlighted papers.

## Outreach package

- [x] Draft long-form launch announcement.
- [x] Draft short social/thread copy.
- [x] Draft GitHub repo descriptions and pinned-repo blurbs.
- [ ] Create final launch post using live public URLs.
- [ ] Prepare 3-5 screenshots/cards for highlighted projects.
- [ ] Choose launch order: GitHub, personal site/blog, Hacker News/Reddit, LinkedIn/X, and relevant AI/dev communities.


## Operational TODO: reconnect new-run paper production

Live check on 2026-05-02 showed that the LangGraph-era idea execution path is progressing, but new completed runs are not automatically becoming new paper rows. The control plane had hundreds of completed `wake_ready` runs with `next_action_hint = draft_paper_or_select_next_project`, while the paper table was still capped at the imported/rewrite-era 242 rows and had no `paper.drafted` events.

Required follow-up:

- [x] Update paper draft eligibility so completed wake-gate runs with `next_action_hint = draft_paper_or_select_next_project` and sufficient evidence/artifacts are draft candidates; keep the old `last_run_state = finalize_positive` path.
- [x] Add automated paper recovery without starving drafts, then disable it by default: draft-next now requires explicit opt-in (`ENOCH_ENABLE_PAPER_DRAFT_NEXT=1`), the dedicated timer is not installed by default, and the queue pump leaves paper drafting off unless `queue_pump_paper_draft_enabled` is true.
- [ ] Backfill paper drafts for completed no-paper projects produced after the LangGraph cutover, preserving evidence sync, claim ledger, manifest, and publication-policy metadata.
- [x] Connect the publication/rewrite workflow to newly drafted papers, including targeted publication-automation backfill and GLM-5.1/Synthetic.new rewrite where configured.
- [x] Add regression tests proving a `worker_callback.wake_ready` completion becomes paper-draft eligible, existing papers prevent duplicate drafts, draft-only automation is opt-in and never dispatches, and the queue pump only drafts before dispatch when explicitly enabled.

## Follow-up quality work

- [ ] Pick 10-15 strongest papers for deeper external-style inspection and summary cards.
- [ ] Add per-paper “why this is interesting” summaries to the corpus index.
- [ ] Add a reproducibility note explaining what artifacts are included and what private runtime state is intentionally excluded.
- [ ] Track public feedback as GitHub issues and convert useful critiques into queue items.

## Already completed packaging/security work

- [x] Added GitHub issue/PR templates, CODEOWNERS, CI, Dependabot, security policy, and protection automation.
- [x] Applied private-repo settings: issues on, discussions on, projects/wiki off, squash-only merges, branch delete on merge.
- [x] Applied branch protection on the staged code and corpus repos, with docs repo visibility tracked separately.
- [x] Kept private career-positioning notes out of public repositories.
- [x] Removed live secrets, local state DBs, production logs, and private LAN endpoints from public artifacts.
- [x] Kept old n8n/OpenClaw workflow material historical only; workflow exports are not shipped as the product.
- [x] Packaged the control-plane repo with quickstart, deployment guide, config reference, Pushover notes, and smoke tests.
- [x] Packaged the corpus repo with 495 AI-generated research artifacts, provenance metadata, claim-ledger files, evidence bundles, packaging/provenance reports, and a strict claim/evidence audit report.
- [x] Stated clearly that generated papers are AI-generated artifacts and that no personal authorship credit is claimed for the paper text or results.
