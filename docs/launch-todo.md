# Launch TODO

This is the working launch checklist for taking Enoch and the generated research corpus from private staging to public release.

## Release gates

- [x] Keep private career-positioning notes out of public repositories.
- [x] Remove live secrets, local state DBs, production logs, and private LAN endpoints from public artifacts.
- [x] Keep old n8n/OpenClaw workflow material historical only; do not ship workflow exports as the product.
- [x] Package the control-plane repo with quickstart, deployment guide, config reference, Pushover notes, and smoke tests.
- [x] Package the corpus repo with 120 AI-generated research artifacts, provenance metadata, claim ledgers, evidence bundles, and quality reports.
- [x] State clearly that generated papers are AI-generated artifacts and that no personal authorship credit is claimed for the paper text or results.
- [ ] Flip `alias8818/enoch-agentic-research-system` public.
- [ ] Flip `alias8818/enoch-ai-research-corpus` public.
- [ ] Enable GitHub Pages or another static host for `site/`.
- [ ] Add final public URLs to README and launch copy after visibility changes.

## Site / story

- [x] Create a static launch site explaining Enoch as an agentic research control plane.
- [x] Highlight selected stronger/promising projects from the corpus.
- [x] Include clear provenance/disclaimer language.
- [x] Include links to code repo and corpus repo.
- [ ] Add screenshots or short GIFs of the dashboard once repos are public and a clean demo instance is available.
- [ ] Add a one-minute architecture diagram or visual explainer.

## Outreach drafts

- [x] Draft long-form launch announcement.
- [x] Draft short social post/thread copy.
- [x] Draft GitHub repo descriptions / pinned repo blurbs.
- [ ] Create final launch post after public URLs are live.
- [ ] Prepare 3-5 screenshots or cards for the highlighted projects.
- [ ] Decide where to post first: GitHub, personal site/blog, Hacker News/Reddit, LinkedIn/X, relevant Discord/Slack communities.

## Follow-up quality work

- [ ] Pick 10-15 strongest papers for deeper external-style review and summary cards.
- [ ] Add per-paper “why this is interesting” summaries to the corpus index.
- [ ] Add a reproducibility note explaining what artifacts are included and what private runtime state is intentionally excluded.
- [ ] Track public feedback as GitHub issues and convert useful critiques into queue items.
