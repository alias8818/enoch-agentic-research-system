# Public launch checklist

This checklist tracks the remaining work before the Enoch system and generated corpus are made public. Completed packaging/security work has been collapsed so this page stays useful as an operator-facing launch board rather than a stale build log.

## Current status

- **Code repo:** public, packaged, CI-enabled, and protected at `alias8818/enoch-agentic-research-system`.
- **Corpus repo:** public, quality-scanned, and protected at `alias8818/enoch-ai-research-corpus`.
- **Launch site:** deployed at <https://alias8818.github.io/enoch-agentic-research-system/>.
- **Release framing:** Enoch is the system/control-plane; the corpus artifacts are AI-generated, bounded, replication-worthy outputs that demonstrate what the system can produce.

## Final gates before public visibility

- [x] Re-run final CI and secret scans on both repos immediately before flipping visibility.
- [x] Confirm branch protection is enabled on both staged repos before visibility changes.
- [x] Flip `alias8818/enoch-agentic-research-system` public.
- [x] Flip `alias8818/enoch-ai-research-corpus` public.
- [x] Verify public anonymous access to both READMEs, the site, and all highlighted corpus links.
- [x] Confirm final repo/site URLs are present in README, launch site copy, and announcement drafts.
- [x] Verify the credits section names the tooling accurately:
  - Enoch control plane built on LangGraph-backed orchestration/state flow.
  - Development and launch operations assisted by oh-my-codex/OMX: <https://github.com/Yeachan-Heo/oh-my-codex>.

## Site / story polish

- [x] Explain Enoch as an agentic research control plane.
- [x] Highlight the strongest generated artifacts from the corpus.
- [x] Use clear provenance/disclaimer language for AI-generated papers.
- [x] Link the code repo and corpus repo.
- [ ] Add screenshots or short GIFs from a clean demo/dashboard instance.
- [ ] Add a one-minute architecture diagram or visual explainer.
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
- [x] Add automated paper recovery without starving drafts: a dedicated draft/publication timer calls `/control/papers/draft-next`, and the queue pump drafts/rewrite-kicks before dispatch when the lane is idle and safe.
- [ ] Backfill paper drafts for completed no-paper projects produced after the LangGraph cutover, preserving evidence sync, claim ledger, manifest, and publication-policy metadata.
- [x] Connect the publication/rewrite workflow to newly drafted papers, including targeted review backfill and GLM-5.1/Synthetic.new rewrite where configured.
- [x] Add regression tests proving a `worker_callback.wake_ready` completion becomes paper-draft eligible, existing papers prevent duplicate drafts, the draft-only timer never dispatches, and the queue pump drafts before dispatch but still dispatches when no draft candidate exists.

## Follow-up quality work

- [ ] Pick 10-15 strongest papers for deeper external-style review and summary cards.
- [ ] Add per-paper “why this is interesting” summaries to the corpus index.
- [ ] Add a reproducibility note explaining what artifacts are included and what private runtime state is intentionally excluded.
- [ ] Track public feedback as GitHub issues and convert useful critiques into queue items.

## Already completed packaging/security work

- [x] Added GitHub issue/PR templates, CODEOWNERS, CI, Dependabot, security policy, and protection automation.
- [x] Applied private-repo settings: issues on, discussions on, projects/wiki off, squash-only merges, branch delete on merge.
- [x] Applied branch protection on both staged private repos.
- [x] Kept private career-positioning notes out of public repositories.
- [x] Removed live secrets, local state DBs, production logs, and private LAN endpoints from public artifacts.
- [x] Kept old n8n/OpenClaw workflow material historical only; workflow exports are not shipped as the product.
- [x] Packaged the control-plane repo with quickstart, deployment guide, config reference, Pushover notes, and smoke tests.
- [x] Packaged the corpus repo with 120 AI-generated research artifacts, provenance metadata, claim ledgers, evidence bundles, and quality reports.
- [x] Stated clearly that generated papers are AI-generated artifacts and that no personal authorship credit is claimed for the paper text or results.
