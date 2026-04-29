# Public launch checklist

## Repository readiness

- [ ] README explains the project in one minute.
- [ ] Quickstart works from a fresh clone.
- [ ] Deployment guide covers control VM and worker setup.
- [ ] Configuration reference documents required tokens and optional integrations.
- [x] Historical workflow-tool notes are isolated under `docs/historical/`; no n8n/OpenClaw workflow exports are shipped.
- [ ] License is present.
- [ ] No private career/application notes are present.
- [ ] No live secrets, local state DBs, production logs, or generated private artifacts are present.

## Verification

- [ ] `uv run pytest -q`
- [ ] `scripts/smoke-test-local.sh` against a local server
- [ ] gitleaks scan returns 0 findings
- [ ] trufflehog scan returns 0 findings
- [ ] fresh clone has expected single public-ready history

## Optional integrations

- [ ] Pushover app token/user key configured outside git
- [ ] Synthetic.new or other OpenAI-compatible provider key configured outside git
- [ ] Notion intake token configured outside git if using Notion sync
- [ ] Worker machine API token configured outside git

## Corpus release

- [ ] Paper rewrite loop complete
- [ ] Corpus imported into separate corpus repo
- [ ] Corpus quality scan passes or failures are triaged
- [ ] Corpus README explains AI-generated/no-human-authorship framing
