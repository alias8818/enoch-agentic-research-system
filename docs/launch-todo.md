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
