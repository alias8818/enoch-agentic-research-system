# Public launch checklist

Use this as the final go/no-go checklist immediately before changing the code, corpus, and docs repositories from private to public.

## Repository readiness

- [x] README explains the project, system architecture, and generated-corpus story in a short first pass.
- [x] Quickstart and smoke-test instructions are present for a fresh clone.
- [x] Deployment guide covers control-plane VM and worker-machine setup.
- [x] Configuration reference documents required tokens and optional integrations without committing values.
- [x] Historical workflow-tool notes are isolated under `docs/historical/`; no n8n/OpenClaw workflow exports are shipped.
- [x] License is present.
- [x] Private career/application notes are excluded from the public repositories.
- [x] Live secrets, local state DBs, production logs, private LAN endpoints, and generated private runtime state are excluded from public artifacts.
- [x] Credits identify key enabling systems accurately, including LangGraph and oh-my-codex/OMX.

## Verification to run before flipping public

- [x] Code repo: `uv run pytest -q`
- [x] Code repo: `python3 -m compileall -q omx_wake_gate tests`
- [x] Code repo: `scripts/smoke-test-local.sh` or documented equivalent smoke path. Live evidence on 2026-05-06: `validate_supabase_resume_readiness.py` passed, and `scripts/smoke-test-local.sh` completed against `http://192.168.1.166:8787` with the bounded status endpoint.
- [x] Code repo: GitHub Actions `tests` and `secret-scan` pass on `main`.
- [x] Corpus repo: `python3 scripts/build_index.py`
- [x] Corpus repo: `python3 scripts/quality_scan.py`
- [x] Corpus repo: GitHub Actions `quality` and `secret-scan` pass on `main`.
- [x] Fresh anonymous read test passes after visibility changes.
- [x] Docs repo validates and hosted docs resolve at <https://solo-09d10f60.mintlify.app/>.

## External integrations

All integration credentials must remain outside git and be configured through environment variables, local `.env` files, or the deployment host secret manager.

- [x] Pushover integration is documented without app token/user key values.
- [x] Synthetic.new or other OpenAI-compatible provider configuration is documented without API keys.
- [x] Supabase-native idea intake is documented; historical Notion provenance is documented without Notion tokens or database IDs that should remain private.
- [x] Worker machine/control-plane API tokens are documented as required deployment secrets, not repository contents.

## Corpus release

- [x] Corpus imported into the separate corpus repo.
- [x] Corpus packaging/provenance scan passes for the staged corpus.
- [x] Corpus README explains AI-generated/no-human-authorship framing.
- [x] Strongest generated artifacts are selected for the launch site.
- [x] Optional: add extra summary cards for the strongest 10-15 papers after public launch. Completed as 13 highlighted artifacts in `site/highlights.json` and the corpus highlighted-artifacts index.

## Visibility flip sequence

1. Confirm the code, corpus, and docs repos still have branch protection enabled. ✅
2. Make `alias8818/enoch-agentic-research-system` public. ✅
3. Make `alias8818/enoch-ai-research-corpus` public. ✅
4. Make `alias8818/enoch-docs` public. ✅
5. Open the site and docs in a private/incognito browser and verify public links resolve. ✅
6. Update launch posts with the final public URLs.
